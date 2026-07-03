import os
import json
import asyncio
import decky
import struct
import bson

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS: dict = {"port": 12345, "autostart": True}


class Plugin:
    _process: asyncio.subprocess.Process | None = None
    _client = None
    _polling_task: asyncio.Task | None = None
    _devices: dict = {}
    _settings: dict = {}
    _startup_delay: float = 2.0

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
        bridge_enabled: bool | None = None, bridge_intensity_scale: float | None = None,
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
        if bridge_enabled is not None:
            await self.set_bridge_enabled(bridge_enabled)
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

    # ── Public callables ──────────────────────────────────────────────────────

    async def start_engine(self) -> dict:
        try:
            await self._start_subprocess()
            await asyncio.sleep(self._startup_delay)
            await self._connect_client()
            await decky.emit("engine_status_changed", True, True, self._settings["port"])
            return {"success": True}
        except Exception as e:
            decky.logger.error(f"start_engine failed: {e}")
            await decky.emit("error", str(e))
            return {"success": False, "error": str(e)}

    async def stop_engine(self) -> dict:
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

    # ── HapticsBridge ────────────────────────────────────────────────
    # Intercept FF effects via haptics-probe, translate to haptic points,
    # and forward as ScalarCmd calls to all connected toys.

    class HapticsBridge:
        def __init__(self) -> None:
            self._client = None
            self._scale: float = 1.0
            self._device_map: dict[str, list[int]] = {}  # device_id → [device_index]s
            self._process: asyncio.subprocess.Process | None = None
            self._reader: asyncio.StreamReader | None = None
            self._sequence_tasks: dict[str, asyncio.Task] = {}
            self._throttle: float = 0.10  # seconds between frames
            self._throttle_timer: asyncio.TimerHandle | None = None

        async def start(self, client, settings: dict) -> None:
            self._client = client
            self._scale = float(settings.get("bridge_intensity_scale", 1.0))
            self._device_map = settings.get("bridge_device_map", {})

            bin_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
            r_fd, w_fd = os.pipe()
            self._process = await asyncio.create_subprocess_exec(
                bin_path,
                stdout=asyncio.streams.StreamReader(),
                stderr=asyncio.streams.StreamReader(),
            )
            self._reader = self._process.stdout
            writer = asyncio.StreamWriter(self._process.stdout)
            # (writer not needed — we just read stdout)

            self._reader_task = asyncio.create_task(self._read_loop())
            await decky.emit("bridge_status_changed", True, "")

        async def _read_loop(self) -> None:
            """Read BSON frames from haptics-probe and dispatch to toys."""
            assert self._client is not None
            assert self._reader is not None
            data = b""

            while self._process is not None and self._process.returncode is None:
                try:
                    chunk = await asyncio.wait_for(self._reader.read(65536), timeout=1.0)
                    if not chunk:
                        break

                    data += chunk
                    offset = 0
                    while offset < len(data):
                        if len(data) - offset < 4:
                            break

                        doc_len = struct.unpack("!i", data[offset:offset+4])[0]
                        payload = data[offset+4:offset+4+doc_len]

                        if len(payload) < doc_len:
                            break

                        doc = bson.loads(payload)

                        if "type" not in doc:
                            decky.logger.error(f"Skipping doc missing 'type': {doc}")
                            continue

                        device_id: str = doc["device"]
                        htype = doc.get("type")

                        if htype == "haptic":
                            points: list[dict] = doc.get("points", [])
                            asyncio.create_task(self._emit_haptic(device_id, points))

                        elif htype == "stop":
                            asyncio.create_task(self._emit_stop(device_id))

                        elif htype == "device_added":
                            decky.logger.info(f"Bridge: device_added {device_id}")

                        offset += 4 + doc_len

                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    decky.logger.exception(f"Reader error: {e}")
                    break

            await decky.emit("bridge_status_changed", False, "haptics-probe exited")

        async def _emit_haptic(self, effect_id: int, points: list[dict]) -> None:
            """Schedule ScalarCmd calls for routed toy, respecting device map."""
            # Cancel any in-flight sequence for this effect_id
            if effect_id in self._sequence_tasks:
                task = self._sequence_tasks[effect_id]
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                del self._sequence_tasks[effect_id]

            # Cancel throttle timer if running
            if self._throttle_timer is not None:
                self._throttle_timer.cancel()
                self._throttle_timer = None

            if not points:
                return

            if self._client is None:
                return

            scaled = [p["intensity"] * self._scale for p in points]
            toy_index = 0

            # Lookup toy index from device map, or fallback to next_available
            if self._device_map:
                toy_index = self._get_toy_index_for_effect(effect_id)
            else:
                # Round-robin if no map
                toy_index = self._next_available_toy_index()
            
            async def dispatch(points: list[dict]) -> None:
                for point in points:
                    if self._client is None:
                        continue
                    intensity = point["intensity"]
                    cmd = self._client.make_cmd(
                        "ScalarCmd",
                        {"DeviceIndex": toy_index},
                        {"Scalars": [{"Scalar": intensity}]}
                    )
                    try:
                        await self._client.send(cmd, timeout=5000)
                        decky.logger.debug(f"Sent ScalarCmd intensity={intensity} to {toy_index}")
                    except Exception as e:
                        decky.logger.error(f"ScalarCmd failed: {e}")
                self._throttle_timer = asyncio.get_event_loop().call_later(
                    self._throttle, lambda: asyncio.create_task(self._read_loop())
                )

            self._sequence_tasks[effect_id] = asyncio.create_task(dispatch(scaled))

        async def _emit_stop(self, device_id: str) -> None:
            """Cancel sequence and send final zero."""
            if device_id in self._sequence_tasks:
                self._sequence_tasks[device_id].cancel()
                try:
                    await self._sequence_tasks[device_id]
                except asyncio.CancelledError:
                    pass
                del self._sequence_tasks[device_id]
            # Send final zero to all devices
            async def clear() -> None:
                for idx in [self._next_device_index()]:
                    cmd = self._client.make_cmd(
                        "ScalarCmd",
                        {"DeviceIndex": idx},
                        {"Scalars": [{"Scalar": 0.0}]}
                    )
                    try:
                        await self._client.send(cmd)
                    except Exception:
                        pass
            await clear()

        def _get_toy_index_for_effect(self, effect_id: int) -> int:
            """Look up toy index for effect_id from device map."""
            mapping = self._device_map.get(effect_id)
            if mapping:
                try:
                    return int(mapping[0])
                except (KeyError, TypeError, ValueError):
                    pass
            # Fallback: round-robin through available toys
            return self._next_available_toy_index()

        def _next_available_toy_index(self) -> int:
            """Return next available toy index for round-robin."""
            idx = 0
            for d in self._client.devices.values():
                for a in d.actuators:
                    if hasattr(a, "index"):
                        idx += 1
            return idx

    # ── Bridge settings/methods wrappers ───────────────────────────────────

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
        bridge_enabled: bool | None = None, bridge_intensity_scale: float | None = None,
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
        if bridge_enabled is not None:
            await self.set_bridge_enabled(bridge_enabled)
        return {"success": True}

    # ── Bridge lifecycle methods ───────────────────────────────────────────────

    async def start_haptics_bridge(self) -> dict:
        """Start haptics-probe subprocess and bridge logic."""
        self._bridge = HapticsBridge()
        try:
            await self._bridge.start(self._client, self._settings)
        except Exception as e:
            decky.logger.error(f"Failed to start haptics bridge: {e}")
        return {"success": True}

    async def stop_haptics_bridge(self) -> dict:
        """Stop haptics bridge and release resources."""
        if hasattr(self, "_bridge"):
            try:
                if self._bridge._process is not None:
                    self._bridge._process.terminate()
                    await self._bridge._process.wait()
            except Exception:
                pass
            self._bridge._process = None
            self._bridge._reader = None
            decky.logger.info("Stopped haptics bridge")
        return {"success": True}

    async def set_bridge_enabled(self, enabled: bool) -> dict:
        """Enable or disable the haptics bridge."""
        self._settings["bridge_enabled"] = enabled
        if enabled:
            await self.set_bridge_scale(self._settings.get("bridge_intensity_scale", 1.0))
        return {"success": True}

    async def set_bridge_scale(self, scale: float) -> dict:
        """Set intensity scaling for the haptics bridge (0.0–1.0)."""
        scale = float(scale)
        self._settings["bridge_intensity_scale"] = scale
        if hasattr(self, "_bridge"):
            self._bridge._scale = scale
        await self._save_settings()
        return {"success": True}

    async def set_bridge_device_map(self, device_map: dict) -> dict:
        """Set device mapping: effect_id → toy_index for routing."""
        self._settings["bridge_device_map"] = device_map
        if hasattr(self, "_bridge"):
            self._bridge._device_map = device_map
        await self._save_settings()
        return {"success": True}

    # ── Lifecycle wrappers ────────────────────────────────────────────

    async def start_engine(self) -> dict:
        try:
            await self._start_subprocess()
            await asyncio.sleep(self._startup_delay)
            await self._connect_client()
            await decky.emit("engine_status_changed", True, True, self._settings["port"])
            
            if self._settings.get("bridge_enabled", False):
                await self.start_haptics_bridge()
            
            return {"success": True}
        except Exception as e:
            decky.logger.error(f"start_engine failed: {e}")
            await decky.emit("error", str(e))
            return {"success": False, "error": str(e)}

    async def stop_engine(self) -> dict:
        await self._disconnect_client()
        await self.stop_haptics_bridge()
        await self._stop_subprocess()
        await decky.emit("engine_status_changed", False, False, self._settings["port"])
        return {"success": True}

    # ── Lifecycle methods ─────────────────────────────────────────────

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

