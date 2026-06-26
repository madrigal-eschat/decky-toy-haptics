import os
import json
import asyncio
import decky

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
        self, port: int | None = None, autostart: bool | None = None
    ) -> dict:
        if port is not None:
            self._settings["port"] = port
        if autostart is not None:
            self._settings["autostart"] = autostart
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
        self._client = Client("decky-intiface", ProtocolSpec.v3)
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
        decky.logger.info("decky-intiface starting")
        await self._load_settings()
        if self._settings.get("autostart", True):
            await self.start_engine()

    async def _unload(self) -> None:
        decky.logger.info("decky-intiface unloading")
        await self.stop_engine()

    async def _uninstall(self) -> None:
        decky.logger.info("decky-intiface uninstalled")

    async def _migration(self) -> None:
        pass

