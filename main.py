import os
import json
import asyncio
import struct
import decky
import bson
from datetime import datetime

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS: dict = {
    "port": 12345,
    "autostart": True,
    "bridge_enabled": True,
    "bridge_device_map": {},
    "bridge_intensity_scale": 1.0,
}


def _find_process_by_exe(bin_path: str) -> int | None:
    """Scan /proc for any running process whose executable resolves to bin_path.
    Returns its pid, or None if no such process is running."""
    try:
        target = os.path.realpath(bin_path)
    except OSError:
        return None
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            exe = os.readlink(f"/proc/{entry}/exe")
        except OSError:
            continue
        if exe == target:
            return int(entry)
    return None


async def _port_in_use(port: int) -> bool:
    """True if something is already accepting TCP connections on 127.0.0.1:port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=0.5
        )
    except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return True


class FileLogger:
    """Dedicated, append-mode log file for a subprocess/subsystem, kept
    separate from the main plugin log so each component's output can be
    tailed on its own."""

    def __init__(self, filename: str) -> None:
        self._path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, filename)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._file = open(self._path, "a")

    def write(self, text: str) -> None:
        ts = datetime.now().isoformat(timespec="milliseconds")
        self._file.write(f"[{ts}] {text}\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


# ── HapticsBridge ────────────────────────────────────────────────────────────
# Spawns haptics-probe, reads translated haptic point sequences over BSON
# on stdout, and forwards them as Buttplug ScalarCmd calls to connected toys.

class HapticsBridge:
    def __init__(self) -> None:
        self._client = None
        self._scale: float = 1.0
        self._device_map: dict = {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._sequence_tasks: dict[str, asyncio.Task] = {}  # device_id → running sequence
        self._log: FileLogger | None = None
        self._monitor_task: asyncio.Task | None = None
        self._on_exit = None
        self._stopping = False

    async def start(self, client, settings: dict, on_exit=None) -> None:
        bin_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
        existing_pid = _find_process_by_exe(bin_path)
        if existing_pid is not None:
            raise RuntimeError(
                f"haptics-probe is already running (pid {existing_pid}), not started by this plugin"
            )

        self._client = client
        self._scale = float(settings.get("bridge_intensity_scale", 1.0))
        self._device_map = settings.get("bridge_device_map", {})
        self._log = FileLogger("haptics-probe.log")
        self._on_exit = on_exit
        self._stopping = False

        self._process = await asyncio.create_subprocess_exec(
            bin_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._log_stderr())
        self._monitor_task = asyncio.create_task(self._monitor_process())

    async def _monitor_process(self) -> None:
        proc = self._process
        if proc is None:
            return
        returncode = await proc.wait()
        if self._stopping:
            return
        if self._log is not None:
            self._log.write(f"haptics-probe exited unexpectedly (code {returncode})")
        if self._on_exit is not None:
            await self._on_exit()

    async def _log_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            async for line in self._process.stderr:
                self._log.write(line.decode(errors='replace').rstrip())
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self._stopping = True
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        seq_tasks = list(self._sequence_tasks.values())
        for task in seq_tasks:
            task.cancel()
        if seq_tasks:
            await asyncio.gather(*seq_tasks, return_exceptions=True)
        self._sequence_tasks.clear()

        if self._client is not None:
            for dev in self._client.devices.values():
                if hasattr(dev, "actuators") and dev.actuators:
                    try:
                        await dev.actuators[0].command(0.0)
                    except Exception:
                        pass

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process is not None:
            if self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._process.kill()
            self._process = None

        if self._log is not None:
            self._log.close()
            self._log = None

        self._client = None

    async def update_scale(self, scale: float) -> None:
        self._scale = max(0.0, min(1.0, scale))

    async def _reader_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        reader = self._process.stdout
        self._log.write("reader loop started")
        try:
            while True:
                header = await reader.readexactly(4)
                length = struct.unpack_from("<i", header)[0]
                if length < 5:
                    self._log.write(f"bogus BSON length {length}, skipping")
                    continue
                rest = await reader.readexactly(length - 4)
                doc = bson.loads(header + rest)
                await self._dispatch(doc)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            self._log.write("reader loop ended (stream closed)")
        except Exception as e:
            self._log.write(f"reader error: {e}")

    async def _dispatch(self, doc: dict) -> None:
        msg_type = doc.get("type")
        self._log.write(f"received doc type={msg_type!r} device={doc.get('device')!r}")
        if msg_type == "haptic":
            device = doc.get("device", "")
            points = doc.get("points", [])
            if points:
                self._schedule_sequence(device, points)
            else:
                self._log.write("haptic doc had no points, ignoring")
        elif msg_type == "stop":
            device = doc.get("device", "")
            await self._send_stop(device)

    def _schedule_sequence(self, device: str, points: list) -> None:
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
        task = asyncio.create_task(self._play_sequence(device, points))
        self._sequence_tasks[device] = task

    @staticmethod
    def _interpolate_points(points: list, step_ms: int = 10) -> list:
        """Always hit each point's exact wall-time boundary; fill the gaps
        between boundaries with linearly-interpolated samples every step_ms
        so ramps read smoothly instead of jumping between sparse points."""
        schedule: list = []
        prev_dt = None
        prev_intensity = None
        for point in points:
            dt_ms = int(point.get("dt_ms", 0))
            intensity = float(point.get("intensity", 0.0))
            if prev_dt is not None:
                span = dt_ms - prev_dt
                t = prev_dt + step_ms
                while t < dt_ms:
                    frac = (t - prev_dt) / span
                    schedule.append((t, prev_intensity + (intensity - prev_intensity) * frac))
                    t += step_ms
            schedule.append((dt_ms, intensity))
            prev_dt, prev_intensity = dt_ms, intensity
        return schedule

    async def _play_sequence(self, device: str, points: list) -> None:
        send_task: asyncio.Task | None = None
        try:
            loop = asyncio.get_event_loop()
            start = loop.time()
            for t_ms, intensity in self._interpolate_points(points):
                delay = start + (t_ms / 1000.0) - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                # at most one send in flight per device: a stale send
                # completing late must never be able to clobber a fresher
                # one, so supersede rather than let them stack up
                if send_task is not None and not send_task.done():
                    send_task.cancel()
                send_task = asyncio.create_task(self._send_scalar(device, intensity * self._scale))
            if send_task is not None:
                await send_task
        except asyncio.CancelledError:
            if send_task is not None:
                send_task.cancel()
            raise
        finally:
            # only remove our own entry: a newer sequence may already have
            # replaced this one in the dict by the time we get here after
            # being cancelled, and popping unconditionally would delete the
            # newer task's bookkeeping, leaving it unable to be cancelled
            # by any subsequent retrigger (orphaned task keeps running).
            if self._sequence_tasks.get(device) is asyncio.current_task():
                self._sequence_tasks.pop(device, None)

    async def _send_stop(self, device: str) -> None:
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
            self._sequence_tasks.pop(device, None)
        await self._send_scalar(device, 0.0)

    async def _send_scalar(self, device: str, intensity: float) -> None:
        if self._client is None:
            self._log.write(f"send_scalar({device!r}, {intensity}): no client, dropping")
            return
        targets = self._device_map.get(device)  # None = all
        intensity = max(0.0, min(1.0, intensity))
        sent = 0
        for dev in self._client.devices.values():
            if targets is not None and dev.index not in targets:
                continue
            try:
                if hasattr(dev, "actuators") and dev.actuators:
                    t0 = asyncio.get_event_loop().time()
                    await dev.actuators[0].command(intensity)
                    rtt_ms = (asyncio.get_event_loop().time() - t0) * 1000.0
                    self._log.write(
                        f"ScalarCmd device={dev.index} ({dev.name}) intensity={intensity:.3f} rtt={rtt_ms:.1f}ms"
                    )
                    sent += 1
                else:
                    self._log.write(f"device {dev.index} ({dev.name}) has no actuators, skipping")
            except Exception as e:
                self._log.write(f"ScalarCmd failed for device {dev.index}: {e}")
        if sent == 0:
            self._log.write(f"send_scalar({device!r}, {intensity}): no matching toy received it (client has {len(self._client.devices)} device(s))")


class Plugin:
    _process: asyncio.subprocess.Process | None = None
    _process_log_task: asyncio.Task | None = None
    _process_log_tail: list = []
    _engine_log: "FileLogger | None" = None
    _engine_monitor_task: asyncio.Task | None = None
    _engine_stopping: bool = False
    _client = None
    _scanning: bool = False
    _scan_task: asyncio.Task | None = None
    _devices: dict = {}
    _settings: dict = {}
    _startup_delay: float = 2.0
    _bridge: "HapticsBridge | None" = None

    # ── Settings ──────────────────────────────────────────────────────────────

    async def _load_settings(self) -> None:
        path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, SETTINGS_FILE)
        if os.path.exists(path):
            with open(path) as f:
                self._settings = {**DEFAULT_SETTINGS, **json.load(f)}
        else:
            self._settings = dict(DEFAULT_SETTINGS)

    async def _save_settings(self) -> None:
        path = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, SETTINGS_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._settings, f)

    async def update_settings(
        self, port: int | None = None, autostart: bool | None = None,
        bridge_enabled: bool | None = None,
        bridge_intensity_scale: float | None = None,
        bridge_device_map: dict | None = None,
    ) -> dict:
        if port is not None:
            self._settings["port"] = port
        if autostart is not None:
            self._settings["autostart"] = autostart
        if bridge_enabled is not None:
            self._settings["bridge_enabled"] = bridge_enabled
        if bridge_intensity_scale is not None:
            self._settings["bridge_intensity_scale"] = bridge_intensity_scale
        if bridge_device_map is not None:
            self._settings["bridge_device_map"] = bridge_device_map
        await self._save_settings()
        return {"success": True}

    # ── Subprocess ────────────────────────────────────────────────────────────

    async def _start_subprocess(self) -> None:
        bin_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "intiface-engine")

        if self._process is not None and self._process.returncode is None:
            raise RuntimeError("intiface-engine is already running")

        existing_pid = _find_process_by_exe(bin_path)
        if existing_pid is not None:
            raise RuntimeError(
                f"intiface-engine is already running (pid {existing_pid}), not started by this plugin"
            )

        port = self._settings["port"]
        if await _port_in_use(port):
            raise RuntimeError(f"port {port} is already in use by another process")

        self._engine_stopping = False
        self._process = await asyncio.create_subprocess_exec(
            bin_path,
            "--websocket-port", str(port),
            "--use-bluetooth-le",
            "--use-lovense-dongle-hid",
            "--use-lovense-connect",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._engine_log = FileLogger("intiface-engine.log")
        self._process_log_task = asyncio.create_task(self._log_subprocess_output())
        self._engine_monitor_task = asyncio.create_task(self._monitor_engine())

    async def _monitor_engine(self) -> None:
        proc = self._process
        if proc is None:
            return
        returncode = await proc.wait()
        if self._engine_stopping:
            return
        decky.logger.warning(f"intiface-engine exited unexpectedly (code {returncode})")
        self._process = None
        if self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None
        await self._disconnect_client()
        await decky.emit("engine_status_changed", False, False, self._settings["port"])

    async def _log_subprocess_output(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            async for line in self._process.stdout:
                text = line.decode(errors='replace').rstrip()
                self._engine_log.write(text)
                self._process_log_tail.append(text)
                if len(self._process_log_tail) > 20:
                    self._process_log_tail.pop(0)
        except asyncio.CancelledError:
            pass

    async def _stop_subprocess(self) -> None:
        self._engine_stopping = True
        if self._engine_monitor_task is not None:
            self._engine_monitor_task.cancel()
            try:
                await self._engine_monitor_task
            except asyncio.CancelledError:
                pass
            self._engine_monitor_task = None
        if self._process_log_task is not None:
            self._process_log_task.cancel()
            try:
                await self._process_log_task
            except asyncio.CancelledError:
                pass
            self._process_log_task = None
        if self._process is not None:
            if self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        decky.logger.warning("intiface-engine did not die even after SIGKILL")
            self._process = None
        if self._engine_log is not None:
            self._engine_log.close()
            self._engine_log = None

    # ── Buttplug client ───────────────────────────────────────────────────────

    async def _connect_client_with_retry(self, attempts: int = 5, initial_delay: float = 0.5) -> None:
        delay = initial_delay
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            if self._process is not None and self._process.returncode is not None:
                tail = "\n".join(self._process_log_tail) or "no output captured"
                raise RuntimeError(
                    f"intiface-engine exited before connecting (code {self._process.returncode}): {tail}"
                )
            try:
                await self._connect_client()
                return
            except Exception as e:
                last_err = e
                decky.logger.warning(
                    f"connect attempt {attempt}/{attempts} failed: {e}, retrying in {delay:.1f}s"
                )
                self._client = None
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5.0)
        raise last_err

    async def _connect_client(self) -> None:
        from buttplug import Client, WebsocketConnector, ProtocolSpec  # lazy import
        port = self._settings["port"]
        self._client = Client("decky-toy-haptics", ProtocolSpec.v3)
        connector = WebsocketConnector(f"ws://127.0.0.1:{port}")
        await self._client.connect(connector)
        decky.logger.info(f"Connected to buttplug server at ws://127.0.0.1:{port}")

        # Emit device_added for any devices already known after connect
        # (buttplug-py populates client.devices from RequestDeviceList on connect)
        for dev_id, dev in self._client.devices.items():
            actuators = len(dev.actuators) if hasattr(dev, "actuators") else 0
            self._devices[dev_id] = dev
            decky.logger.info(f"Device already known on connect: {dev.name} (id={dev_id}, actuators={actuators})")
            await decky.emit("device_added", dev_id, dev.name, actuators)

        decky.logger.info(f"Initial device count: {len(self._devices)}")
        # Scanning is off by default — the frontend must explicitly call
        # start_scan() to begin looking for new devices.

    async def start_scan(self) -> dict:
        if self._client is None:
            return {"success": False, "error": "engine not running"}
        if self._scanning:
            return {"success": True}
        await self._client.start_scanning()
        self._scanning = True
        self._scan_task = asyncio.create_task(self._scan_watch())
        await decky.emit("scan_status_changed", True)
        decky.logger.info("Scan started")
        return {"success": True}

    async def stop_scan(self) -> dict:
        if not self._scanning:
            return {"success": True}
        self._scanning = False
        if self._scan_task is not None:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        if self._client is not None:
            try:
                await self._client.stop_scanning()
            except Exception as e:
                decky.logger.warning(f"stop_scanning failed: {e}")
        await decky.emit("scan_status_changed", False)
        decky.logger.info("Scan stopped")
        return {"success": True}

    async def _scan_watch(self) -> None:
        """While scanning is active, periodically diff client.devices and emit changes."""
        try:
            while self._scanning and self._client is not None:
                await asyncio.sleep(2.0)
                current = self._client.devices
                current_ids = set(current.keys())
                known_ids = set(self._devices.keys())
                added = current_ids - known_ids
                removed = known_ids - current_ids
                for dev_id in added:
                    dev = current[dev_id]
                    actuators = len(dev.actuators) if hasattr(dev, "actuators") else 0
                    self._devices[dev_id] = dev
                    decky.logger.info(f"Device added: {dev.name} (id={dev_id}, actuators={actuators})")
                    await decky.emit("device_added", dev_id, dev.name, actuators)
                for dev_id in list(removed):
                    decky.logger.info(f"Device removed: id={dev_id}")
                    del self._devices[dev_id]
                    await decky.emit("device_removed", dev_id)
        except asyncio.CancelledError:
            pass

    async def _disconnect_client(self) -> None:
        if self._scanning:
            await self.stop_scan()
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._devices = {}

    # ── Haptics bridge callables ─────────────────────────────────────────────

    async def _on_bridge_exit(self) -> None:
        decky.logger.warning("haptics-probe exited unexpectedly")
        self._bridge = None
        device = self._settings.get("bridge_evdev_device")
        await decky.emit("bridge_status_changed", False, device)

    async def set_bridge_enabled(self, enabled: bool) -> dict:
        try:
            if enabled and self._client is not None and self._bridge is None:
                bridge = HapticsBridge()
                await bridge.start(self._client, self._settings, on_exit=self._on_bridge_exit)
                self._bridge = bridge
            elif not enabled and self._bridge is not None:
                await self._bridge.stop()
                self._bridge = None
        except Exception as e:
            decky.logger.error(f"set_bridge_enabled({enabled}) failed: {e}")
            return {"success": False, "error": str(e)}

        self._settings["bridge_enabled"] = enabled
        await self._save_settings()
        device = self._settings.get("bridge_evdev_device")
        await decky.emit("bridge_status_changed", enabled, device)
        return {"success": True}

    async def list_evdev_devices(self) -> list:
        bin_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
        try:
            proc = await asyncio.create_subprocess_exec(
                bin_path, "--list-devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return json.loads(stdout.decode())
        except Exception as e:
            decky.logger.error(f"list_evdev_devices failed: {e}")
            return []

    async def set_bridge_scale(self, scale: float) -> dict:
        self._settings["bridge_intensity_scale"] = scale
        await self._save_settings()
        if self._bridge is not None:
            await self._bridge.update_scale(scale)
        return {"success": True}

    # ── Public callables ──────────────────────────────────────────────────────

    async def start_engine(self) -> dict:
        self._process_log_tail.clear()
        try:
            await self._start_subprocess()
            await asyncio.sleep(self._startup_delay)

            if self._process is not None and self._process.returncode is not None:
                tail = "\n".join(self._process_log_tail) or "no output captured"
                raise RuntimeError(
                    f"intiface-engine exited immediately (code {self._process.returncode}): {tail}"
                )

            await self._connect_client_with_retry()
            await decky.emit("engine_status_changed", True, True, self._settings["port"])

            if self._settings.get("bridge_enabled", False) and self._bridge is None:
                bridge = HapticsBridge()
                await bridge.start(self._client, self._settings, on_exit=self._on_bridge_exit)
                self._bridge = bridge

            return {"success": True}
        except Exception as e:
            decky.logger.error(f"start_engine failed: {e}")
            await self._stop_subprocess()
            await decky.emit("engine_status_changed", False, False, self._settings["port"])
            await decky.emit("error", str(e))
            return {"success": False, "error": str(e)}

    async def stop_engine(self) -> dict:
        if self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None
        await self._disconnect_client()
        await self._stop_subprocess()
        await decky.emit("engine_status_changed", False, False, self._settings["port"])
        return {"success": True}

    async def get_status(self) -> dict:
        running = self._process is not None and self._process.returncode is None
        connected = self._client is not None
        return {
            "running": running,
            "connected": connected,
            "scanning": self._scanning,
            "port": self._settings.get("port", DEFAULT_SETTINGS["port"]),
            "bridge_enabled": self._settings.get("bridge_enabled", False),
            "bridge_scale": self._settings.get("bridge_intensity_scale", 1.0),
            "bridge_device_map": self._settings.get("bridge_device_map", {}),
        }

    async def get_devices(self) -> list:
        return [
            {
                "id": dev.index,
                "name": dev.name,
                "actuators": len(dev.actuators) if hasattr(dev, "actuators") else 0,
            }
            for dev in self._devices.values()
        ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _main(self) -> None:
        decky.logger.info("decky-toy-haptics starting")
        await self._load_settings()
        if self._settings.get("autostart", True):
            await self.start_engine()

    async def _unload(self) -> None:
        decky.logger.info("decky-toy-haptics unloading")
        await self.stop_engine()

    async def _uninstall(self) -> None:
        decky.logger.info("decky-toy-haptics uninstalled")
        await self.stop_engine()

    async def _migration(self) -> None:
        pass
