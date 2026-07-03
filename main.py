import os
import json
import asyncio
import struct
import decky
import bson

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS: dict = {
    "port": 12345,
    "autostart": True,
    "bridge_enabled": True,
    "bridge_device_map": {},
    "bridge_intensity_scale": 1.0,
}


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
        self._sequence_tasks: dict[str, asyncio.Task] = {}  # device_id → running sequence

    async def start(self, client, settings: dict) -> None:
        self._client = client
        self._scale = float(settings.get("bridge_intensity_scale", 1.0))
        self._device_map = settings.get("bridge_device_map", {})

        bin_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
        self._process = await asyncio.create_subprocess_exec(
            bin_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def stop(self) -> None:
        for task in self._sequence_tasks.values():
            task.cancel()
        self._sequence_tasks.clear()

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._process is not None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

        self._client = None

    async def update_scale(self, scale: float) -> None:
        self._scale = max(0.0, min(1.0, scale))

    async def _reader_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        reader = self._process.stdout
        try:
            while True:
                header = await reader.readexactly(4)
                length = struct.unpack_from("<i", header)[0]
                if length < 5:
                    continue
                rest = await reader.readexactly(length - 4)
                doc = bson.loads(header + rest)
                await self._dispatch(doc)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception as e:
            decky.logger.warning(f"HapticsBridge reader error: {e}")

    async def _dispatch(self, doc: dict) -> None:
        msg_type = doc.get("type")
        if msg_type == "haptic":
            device = doc.get("device", "")
            points = doc.get("points", [])
            if points:
                self._schedule_sequence(device, points)
        elif msg_type == "stop":
            device = doc.get("device", "")
            await self._send_stop(device)

    def _schedule_sequence(self, device: str, points: list) -> None:
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
        task = asyncio.create_task(self._play_sequence(device, points))
        self._sequence_tasks[device] = task

    async def _play_sequence(self, device: str, points: list) -> None:
        try:
            prev_dt = 0
            for point in points:
                dt_ms = int(point.get("dt_ms", 0))
                intensity = float(point.get("intensity", 0.0))
                delta_ms = max(0, dt_ms - prev_dt)
                if delta_ms > 0:
                    await asyncio.sleep(delta_ms / 1000.0)
                prev_dt = dt_ms
                await self._send_scalar(device, intensity * self._scale)
        except asyncio.CancelledError:
            pass
        finally:
            self._sequence_tasks.pop(device, None)

    async def _send_stop(self, device: str) -> None:
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
            self._sequence_tasks.pop(device, None)
        await self._send_scalar(device, 0.0)

    async def _send_scalar(self, device: str, intensity: float) -> None:
        if self._client is None:
            return
        targets = self._device_map.get(device)  # None = all
        intensity = max(0.0, min(1.0, intensity))
        for dev in self._client.devices.values():
            if targets is not None and dev.index not in targets:
                continue
            try:
                if hasattr(dev, "actuators") and dev.actuators:
                    await dev.actuators[0].command(intensity)
            except Exception as e:
                decky.logger.warning(f"ScalarCmd failed for device {dev.index}: {e}")


class Plugin:
    _process: asyncio.subprocess.Process | None = None
    _client = None
    _polling_task: asyncio.Task | None = None
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
        self._process = await asyncio.create_subprocess_exec(
            bin_path,
            "--websocket-port", str(self._settings["port"]),
            "--use-bluetooth-le",
            "--use-hid",
            "--use-lovense-dongle-hid",
            "--use-lovense-connect",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _stop_subprocess(self) -> None:
        if self._process is not None:
            self._process.terminate()
            await self._process.wait()
            self._process = None

    # ── Buttplug client ───────────────────────────────────────────────────────

    async def _connect_client(self) -> None:
        from buttplug import Client, WebsocketConnector, ProtocolSpec  # lazy import
        port = self._settings["port"]
        self._client = Client("decky-toy-haptics", ProtocolSpec.v3)
        connector = WebsocketConnector(f"ws://127.0.0.1:{port}")
        await self._client.connect(connector)

        # Emit device_added for any devices already known after connect
        # (buttplug-py populates client.devices from RequestDeviceList on connect)
        for dev_id, dev in self._client.devices.items():
            actuators = len(dev.actuators) if hasattr(dev, "actuators") else 0
            self._devices[dev_id] = dev
            await decky.emit("device_added", dev_id, dev.name, actuators)

        # Start background scan loop for ongoing discovery
        self._polling_task = asyncio.create_task(self._scan_loop())

    async def _scan_loop(self) -> None:
        """Periodically scan for device changes."""
        while self._client is not None:
            await asyncio.sleep(10.0)
            if self._client is None:
                break
            try:
                scan_future = await self._client.start_scanning()
                await asyncio.wait_for(asyncio.shield(scan_future), timeout=5.0)
                current = self._client.devices
                current_ids = set(current.keys())
                known_ids = set(self._devices.keys())
                for dev_id in current_ids - known_ids:
                    dev = current[dev_id]
                    actuators = len(dev.actuators) if hasattr(dev, "actuators") else 0
                    self._devices[dev_id] = dev
                    await decky.emit("device_added", dev_id, dev.name, actuators)
                for dev_id in list(known_ids - current_ids):
                    del self._devices[dev_id]
                    await decky.emit("device_removed", dev_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                decky.logger.warning(f"Scan loop error: {e}")

    async def _disconnect_client(self) -> None:
        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._devices = {}

    # ── Haptics bridge callables ─────────────────────────────────────────────

    async def set_bridge_enabled(self, enabled: bool) -> dict:
        self._settings["bridge_enabled"] = enabled
        await self._save_settings()
        if enabled and self._client is not None and self._bridge is None:
            self._bridge = HapticsBridge()
            await self._bridge.start(self._client, self._settings)
        elif not enabled and self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None
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
        try:
            await self._start_subprocess()
            await asyncio.sleep(self._startup_delay)
            await self._connect_client()
            await decky.emit("engine_status_changed", True, True, self._settings["port"])

            if self._settings.get("bridge_enabled", False) and self._bridge is None:
                self._bridge = HapticsBridge()
                await self._bridge.start(self._client, self._settings)

            return {"success": True}
        except Exception as e:
            decky.logger.error(f"start_engine failed: {e}")
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

    async def _migration(self) -> None:
        pass
