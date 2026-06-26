# decky-intiface MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Decky Loader plugin that manages an `intiface-engine` subprocess, connects to it via the Buttplug v3 protocol, and exposes a minimal Steam QAM UI showing engine status and connected devices — with a full two-tier test suite.

**Architecture:** The Python `Plugin` class manages the `intiface-engine` subprocess and a `buttplug-py` client; it exposes callables (`start_engine`, `stop_engine`, `get_status`, `get_devices`, `update_settings`) and emits events (`engine_status_changed`, `device_added`, `device_removed`, `error`) to the React frontend. Backend tests use a decky runtime shim and a mock Buttplug v3 WebSocket server; frontend tests run the React components in a Vite harness with a mocked `@decky/api`.

**Tech Stack:** Python 3.x · `buttplug-py` · `asyncio` · `pytest` + `pytest-asyncio` + `websockets` (backend tests) · React + TypeScript + `@decky/ui` + `@decky/api` · Vite + Playwright + Chromium (frontend tests).

**Scope:** Phase 1 (MVP) only. Phase 2 (evdev haptics bridge) and Phase 3 (full UI) are separate plans.

---

## File Structure

### Created
- `tests/backend/__init__.py`
- `tests/backend/requirements.txt`
- `tests/backend/pytest.ini`
- `tests/backend/decky_mock.py`
- `tests/backend/mock_intiface.py`
- `tests/backend/conftest.py`
- `tests/backend/test_settings.py`
- `tests/backend/test_lifecycle.py`
- `tests/backend/test_devices.py`
- `tests/frontend/harness/index.html`
- `tests/frontend/harness/main.tsx`
- `tests/frontend/harness/vite.config.ts`
- `tests/frontend/mocks/decky-api.ts`
- `tests/frontend/playwright.config.ts`
- `tests/frontend/connect.spec.ts`
- `tests/frontend/devices.spec.ts`

### Modified
- `main.py` — complete rewrite
- `src/index.tsx` — complete rewrite
- `backend/Makefile` — download intiface-engine binary instead of building C
- `plugin.json` — update name, remove debug flag
- `package.json` — add Vite, Playwright, React devDeps and test scripts

---

## Tasks

### Task 1: Backend test directory structure and configuration

**Files:**
- Create: `tests/backend/__init__.py`
- Create: `tests/backend/requirements.txt`
- Create: `tests/backend/pytest.ini`

- [ ] **Step 1: Create directories**

```bash
mkdir -p tests/backend tests/frontend/harness tests/frontend/mocks
touch tests/backend/__init__.py
```

Expected: directories created, no output from `touch`.

- [ ] **Step 2: Create requirements file**

Create `tests/backend/requirements.txt`:

```
pytest>=8.0
pytest-asyncio>=0.23
websockets>=12.0
buttplug-py>=0.4.0
```

- [ ] **Step 3: Create pytest configuration**

Create `tests/backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests/backend
```

- [ ] **Step 4: Install test dependencies**

```bash
pip install -r tests/backend/requirements.txt
```

Expected: packages install cleanly.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "chore: add backend test directory structure and configuration"
```

---

### Task 2: Decky runtime shim

**Files:**
- Create: `tests/backend/decky_mock.py`

- [ ] **Step 1: Create the shim**

Create `tests/backend/decky_mock.py`:

```python
import logging
from types import ModuleType
from pathlib import Path


class EmitRecorder:
    """Records decky.emit() calls so tests can assert on them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def __call__(self, event: str, *args) -> None:
        self.calls.append((event, args))

    def events_named(self, name: str) -> list[tuple]:
        return [args for ev, args in self.calls if ev == name]

    def reset(self) -> None:
        self.calls.clear()


emit_recorder = EmitRecorder()


def make_decky_mock(settings_dir: Path) -> ModuleType:
    """Return a module object that stands in for the runtime `decky` module."""
    mod = ModuleType("decky")
    mod.logger = logging.getLogger("decky_mock")
    mod.emit = emit_recorder
    mod.DECKY_HOME = str(settings_dir)
    mod.DECKY_USER_HOME = str(settings_dir)
    mod.DECKY_PLUGIN_SETTINGS_DIR = str(settings_dir / "settings")
    mod.DECKY_PLUGIN_RUNTIME_DIR = str(settings_dir / "runtime")
    mod.DECKY_PLUGIN_LOG_DIR = str(settings_dir / "logs")
    mod.DECKY_PLUGIN_DIR = str(settings_dir / "plugin")
    mod.DECKY_PLUGIN_NAME = "decky-intiface"
    mod.migrate_logs = lambda *a, **kw: {}
    mod.migrate_settings = lambda *a, **kw: {}
    mod.migrate_runtime = lambda *a, **kw: {}
    return mod
```

- [ ] **Step 2: Verify importable**

```bash
python -c "from tests.backend.decky_mock import make_decky_mock, emit_recorder; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add tests/backend/decky_mock.py
git commit -m "test: add decky runtime shim"
```

---

### Task 3: Mock Intiface (Buttplug v3) WebSocket server

**Files:**
- Create: `tests/backend/mock_intiface.py`

- [ ] **Step 1: Create the mock server**

Create `tests/backend/mock_intiface.py`:

```python
import json
from dataclasses import dataclass, field
import websockets
import websockets.server


def _device_messages_schema() -> dict:
    return {
        "ScalarCmd": [
            {"StepCount": 20, "ActuatorType": "Vibrate", "FeatureDescriptor": ""}
        ]
    }


@dataclass
class FakeDevice:
    index: int
    name: str


class MockIntifaceServer:
    """Minimal Buttplug v3 WebSocket server for use in tests."""

    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.received_commands: list[dict] = []
        self._fake_devices: list[FakeDevice] = []
        self._server: websockets.server.WebSocketServer | None = None

    def add_fake_device(self, index: int, name: str) -> None:
        self._fake_devices.append(FakeDevice(index=index, name=name))

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, websocket) -> None:
        async for raw in websocket:
            for msg in json.loads(raw):
                msg_type, payload = next(iter(msg.items()))
                await self._dispatch(websocket, msg_type, payload)

    async def _dispatch(self, websocket, msg_type: str, payload: dict) -> None:
        msg_id = payload.get("Id", 0)

        if msg_type == "RequestServerInfo":
            await websocket.send(json.dumps([{
                "ServerInfo": {
                    "Id": msg_id,
                    "MessageVersion": 3,
                    "MaxPingTime": 0,
                    "ServerName": "mock-intiface",
                }
            }]))

        elif msg_type == "RequestDeviceList":
            devices = [
                {
                    "DeviceIndex": d.index,
                    "DeviceName": d.name,
                    "DeviceDisplayName": d.name,
                    "DeviceMessageTimingGap": 0,
                    "DeviceMessages": _device_messages_schema(),
                }
                for d in self._fake_devices
            ]
            await websocket.send(json.dumps([
                {"DeviceList": {"Id": msg_id, "Devices": devices}}
            ]))

        elif msg_type == "StartScanning":
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))
            for d in self._fake_devices:
                await websocket.send(json.dumps([{
                    "DeviceAdded": {
                        "Id": 0,
                        "DeviceIndex": d.index,
                        "DeviceName": d.name,
                        "DeviceDisplayName": d.name,
                        "DeviceMessageTimingGap": 0,
                        "DeviceMessages": _device_messages_schema(),
                    }
                }]))
            await websocket.send(json.dumps([{"ScanningFinished": {"Id": 0}}]))

        elif msg_type == "StopScanning":
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))

        elif msg_type in ("ScalarCmd", "VibrateCmd", "StopAllDevices"):
            self.received_commands.append({msg_type: payload})
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))

        else:
            await websocket.send(json.dumps([{"Ok": {"Id": msg_id}}]))
```

- [ ] **Step 2: Smoke-test the server**

Save this as a temp script and run it:

```python
# /tmp/smoke_mock.py
import asyncio, json, websockets

async def smoke():
    from tests.backend.mock_intiface import MockIntifaceServer
    s = MockIntifaceServer()
    await s.start()
    async with websockets.connect(s.ws_url) as ws:
        await ws.send(json.dumps([{"RequestServerInfo": {"Id": 1, "ClientName": "test", "MessageVersion": 3}}]))
        resp = json.loads(await ws.recv())
        assert resp[0]["ServerInfo"]["ServerName"] == "mock-intiface", resp
    await s.stop()
    print("smoke passed")

asyncio.run(smoke())
```

```bash
python /tmp/smoke_mock.py
```

Expected: `smoke passed`

- [ ] **Step 3: Commit**

```bash
git add tests/backend/mock_intiface.py
git commit -m "test: add mock Buttplug v3 WebSocket server"
```

---

### Task 4: Shared fixtures (conftest.py)

**Files:**
- Create: `tests/backend/conftest.py`

- [ ] **Step 1: Create conftest**

Create `tests/backend/conftest.py`:

```python
import sys
import asyncio
import os
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

from tests.backend.decky_mock import make_decky_mock, emit_recorder
from tests.backend.mock_intiface import MockIntifaceServer


@pytest.fixture(scope="session", autouse=True)
def inject_decky(tmp_path_factory):
    """Inject the decky shim into sys.modules before any test imports main."""
    tmp = tmp_path_factory.mktemp("decky_root")
    mock = make_decky_mock(tmp)
    sys.modules["decky"] = mock
    yield mock


@pytest_asyncio.fixture
async def mock_server():
    server = MockIntifaceServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def mock_subprocess(monkeypatch):
    """Prevent tests from launching the real intiface-engine binary."""
    proc = MagicMock()
    proc.returncode = None
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return proc


@pytest_asyncio.fixture
async def plugin(inject_decky, tmp_path):
    """Fresh Plugin instance per test with its own isolated settings dir."""
    sys.modules.pop("main", None)
    import main  # noqa: PLC0415

    inject_decky.DECKY_PLUGIN_SETTINGS_DIR = str(tmp_path / "settings")
    inject_decky.DECKY_PLUGIN_DIR = str(tmp_path / "plugin")
    os.makedirs(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    emit_recorder.reset()

    p = main.Plugin()
    p._startup_delay = 0.0
    yield p

    try:
        await p.stop_engine()
    except Exception:
        pass


async def wait_for_emit(event_name: str, timeout: float = 2.0) -> list[tuple]:
    """Poll until at least one event with the given name has been recorded."""
    import asyncio as _aio
    deadline = _aio.get_event_loop().time() + timeout
    while _aio.get_event_loop().time() < deadline:
        events = emit_recorder.events_named(event_name)
        if events:
            return events
        await _aio.sleep(0.05)
    raise TimeoutError(f"No '{event_name}' event received within {timeout}s")
```

- [ ] **Step 2: Verify collection succeeds (no tests yet)**

```bash
pytest tests/backend/ --collect-only 2>&1 | tail -5
```

Expected: `no tests ran` or similar, no import errors.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/conftest.py
git commit -m "test: add shared backend test fixtures"
```

---

### Task 5: Settings management — TDD

**Files:**
- Create: `tests/backend/test_settings.py`
- Modify: `main.py` (first version — settings only)

- [ ] **Step 1: Write failing settings tests**

Create `tests/backend/test_settings.py`:

```python
import json
import os


async def test_load_settings_uses_defaults_when_no_file(plugin):
    await plugin._load_settings()

    assert plugin._settings["port"] == 12345
    assert plugin._settings["autostart"] is True


async def test_load_settings_reads_from_file(plugin, inject_decky):
    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path, "w") as f:
        json.dump({"port": 7777, "autostart": False}, f)

    await plugin._load_settings()

    assert plugin._settings["port"] == 7777
    assert plugin._settings["autostart"] is False


async def test_load_settings_merges_missing_keys_with_defaults(plugin, inject_decky):
    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path, "w") as f:
        json.dump({"port": 6666}, f)  # no autostart key

    await plugin._load_settings()

    assert plugin._settings["port"] == 6666
    assert plugin._settings["autostart"] is True  # filled from defaults


async def test_update_settings_persists_port(plugin, inject_decky):
    result = await plugin.update_settings(port=9999)

    assert result == {"success": True}
    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path) as f:
        saved = json.load(f)
    assert saved["port"] == 9999


async def test_update_settings_persists_autostart(plugin, inject_decky):
    await plugin.update_settings(autostart=False)

    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path) as f:
        saved = json.load(f)
    assert saved["autostart"] is False


async def test_get_status_returns_configured_port(plugin):
    plugin._settings = {"port": 8888, "autostart": True}

    status = await plugin.get_status()

    assert status["port"] == 8888
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/backend/test_settings.py -v 2>&1 | tail -10
```

Expected: errors (`ImportError` or `AttributeError`) — Plugin not yet implemented.

- [ ] **Step 3: Write main.py with settings + stub methods**

Replace `main.py` entirely:

```python
import os
import json
import asyncio
import decky

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS: dict = {"port": 12345, "autostart": True}


class Plugin:
    _process: asyncio.subprocess.Process | None = None
    _client = None
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

        async def on_device_added(emitter, dev) -> None:
            actuators = len(dev.actuators) if hasattr(dev, "actuators") else 0
            self._devices[dev.index] = dev
            await decky.emit("device_added", dev.index, dev.name, actuators)

        async def on_device_removed(emitter, dev) -> None:
            self._devices.pop(dev.index, None)
            await decky.emit("device_removed", dev.index)

        self._client.device_added_handler += on_device_added
        self._client.device_removed_handler += on_device_removed

        connector = WebsocketConnector(f"ws://127.0.0.1:{port}")
        await self._client.connect(connector)

    async def _disconnect_client(self) -> None:
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
            "port": self._settings["port"],
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
```

- [ ] **Step 4: Run settings tests — expect pass**

```bash
pytest tests/backend/test_settings.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/backend/test_settings.py
git commit -m "feat: add Plugin settings management with TDD"
```

---

### Task 6: Engine lifecycle — TDD

**Files:**
- Create: `tests/backend/test_lifecycle.py`

- [ ] **Step 1: Write failing lifecycle tests**

Create `tests/backend/test_lifecycle.py`:

```python
import json
import os
from tests.backend.decky_mock import emit_recorder


async def test_get_status_not_running_before_start(plugin):
    status = await plugin.get_status()

    assert status["running"] is False
    assert status["connected"] is False


async def test_start_engine_returns_success(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}

    result = await plugin.start_engine()

    assert result["success"] is True


async def test_start_engine_creates_subprocess(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}

    await plugin.start_engine()

    assert plugin._process is not None


async def test_start_engine_emits_status_event(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}

    await plugin.start_engine()

    events = emit_recorder.events_named("engine_status_changed")
    assert len(events) == 1
    running, connected, port = events[0]
    assert running is True
    assert connected is True
    assert port == mock_server.port


async def test_get_status_running_after_start(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    status = await plugin.get_status()

    assert status["running"] is True
    assert status["connected"] is True


async def test_stop_engine_terminates_subprocess(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    result = await plugin.stop_engine()

    assert result == {"success": True}
    mock_subprocess.terminate.assert_called_once()


async def test_stop_engine_emits_disconnected_event(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()
    emit_recorder.reset()

    await plugin.stop_engine()

    events = emit_recorder.events_named("engine_status_changed")
    assert len(events) == 1
    running, connected, _ = events[0]
    assert running is False
    assert connected is False


async def test_get_status_not_running_after_stop(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()
    await plugin.stop_engine()

    status = await plugin.get_status()

    assert status["running"] is False
    assert status["connected"] is False


async def test_main_starts_engine_when_autostart_true(
    plugin, mock_subprocess, mock_server, inject_decky
):
    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path, "w") as f:
        json.dump({"port": mock_server.port, "autostart": True}, f)

    await plugin._main()

    assert plugin._process is not None
    status = await plugin.get_status()
    assert status["running"] is True


async def test_main_does_not_start_engine_when_autostart_false(
    plugin, mock_subprocess, mock_server, inject_decky
):
    settings_path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(settings_path, "w") as f:
        json.dump({"port": mock_server.port, "autostart": False}, f)

    await plugin._main()

    assert plugin._process is None


async def test_start_engine_returns_error_on_connection_failure(
    plugin, mock_subprocess
):
    # Port 1 is not listening — connection will be refused
    plugin._settings = {"port": 1, "autostart": False}

    result = await plugin.start_engine()

    assert result["success"] is False
    assert "error" in result


async def test_start_engine_emits_error_event_on_failure(plugin, mock_subprocess):
    plugin._settings = {"port": 1, "autostart": False}

    await plugin.start_engine()

    errors = emit_recorder.events_named("error")
    assert len(errors) == 1
```

- [ ] **Step 2: Run to confirm tests fail or error**

```bash
pytest tests/backend/test_lifecycle.py -v 2>&1 | tail -15
```

Expected: failures (the implementation exists but the mock_server fixture interaction may not be wired yet).

- [ ] **Step 3: Run the full backend suite to confirm all tests pass**

The implementation already exists in `main.py` from Task 5. Run all backend tests:

```bash
pytest tests/backend/ -v
```

Expected: all tests pass. If any lifecycle test fails due to buttplug-py API mismatch (handler signature, `ProtocolSpec` enum, etc.), adjust `_connect_client` in `main.py` to match the actual library API. Common fixes:
- `ProtocolSpec.v3` may be `ProtocolSpec.V3` — check with `python -c "from buttplug import ProtocolSpec; print(dir(ProtocolSpec))"`
- Handler signature `on_device_added(emitter, dev)` may need to be `on_device_added(dev)` — try both

- [ ] **Step 4: Commit**

```bash
git add tests/backend/test_lifecycle.py
git commit -m "test: add engine lifecycle tests"
```

---

### Task 7: Device discovery — TDD

**Files:**
- Create: `tests/backend/test_devices.py`

- [ ] **Step 1: Write failing device tests**

Create `tests/backend/test_devices.py`:

```python
import asyncio
from tests.backend.conftest import wait_for_emit
from tests.backend.decky_mock import emit_recorder


async def test_get_devices_empty_before_connect(plugin):
    devices = await plugin.get_devices()

    assert devices == []


async def test_device_appears_after_scanning(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Test Vibrator")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    await plugin._client.start_scanning()
    await wait_for_emit("device_added")

    devices = await plugin.get_devices()
    assert len(devices) == 1
    assert devices[0]["name"] == "Test Vibrator"
    assert devices[0]["id"] == 0


async def test_device_added_event_emitted(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Test Vibrator")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    await plugin._client.start_scanning()
    events = await wait_for_emit("device_added")

    device_id, device_name, actuators = events[0]
    assert device_name == "Test Vibrator"
    assert device_id == 0


async def test_multiple_devices_discovered(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Vibrator A")
    mock_server.add_fake_device(1, "Vibrator B")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    await plugin._client.start_scanning()
    # Wait for both device_added events
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        if len(emit_recorder.events_named("device_added")) >= 2:
            break
        await asyncio.sleep(0.05)

    devices = await plugin.get_devices()
    assert len(devices) == 2
    names = {d["name"] for d in devices}
    assert names == {"Vibrator A", "Vibrator B"}
```

- [ ] **Step 2: Run the device tests**

```bash
pytest tests/backend/test_devices.py -v
```

Expected: all pass. If `plugin._client.start_scanning()` is not the correct API, check with `python -c "from buttplug import Client; help(Client)"` and adjust.

- [ ] **Step 3: Run the full backend suite**

```bash
pytest tests/backend/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/backend/test_devices.py
git commit -m "test: add device discovery tests"
```

---

### Task 8: Bundle buttplug-py into py_modules

**Files:**
- Modify: `py_modules/` (populated by pip)

- [ ] **Step 1: Install buttplug-py and its dependencies into py_modules**

```bash
pip install --target py_modules --no-deps buttplug-py
pip install --target py_modules websockets
```

`--no-deps` avoids pulling in packages already available in SteamOS Python (e.g. `asyncio`, `logging`). `websockets` is the key runtime dependency.

- [ ] **Step 2: Verify the bundle**

```bash
ls py_modules/ | grep -E "buttplug|websockets"
```

Expected: `buttplug` and `websockets` directories (or similar).

- [ ] **Step 3: Add py_modules contents to .gitignore or commit selectively**

If you want to commit py_modules (acceptable for small plugins): `git add py_modules/`.

If you want to use a build step instead, add `py_modules/` to `.gitignore` and document the install step in `README.md`. Committing is simpler for now.

```bash
git add py_modules/
git commit -m "chore: bundle buttplug-py and websockets into py_modules"
```

---

### Task 9: Update backend Makefile to download intiface-engine

**Files:**
- Modify: `backend/Makefile`

- [ ] **Step 1: Find the correct release URL**

Browse to https://github.com/intiface/intiface-engine/releases/latest and find the Linux x86_64 binary filename. It will be something like `intiface-engine-linux-x64` or `intiface-engine_linux_amd64`. Note the exact filename and the latest version tag.

- [ ] **Step 2: Update the Makefile**

Replace `backend/Makefile` with (substituting the actual version and filename you found):

```makefile
INTIFACE_ENGINE_VERSION ?= v1.4.0
INTIFACE_ENGINE_FILENAME = intiface-engine-linux-x64
INTIFACE_ENGINE_URL = https://github.com/intiface/intiface-engine/releases/download/$(INTIFACE_ENGINE_VERSION)/$(INTIFACE_ENGINE_FILENAME)

.PHONY: all clean

all: intiface-engine

intiface-engine:
	mkdir -p ./out
	curl -fL -o ./out/intiface-engine "$(INTIFACE_ENGINE_URL)"
	chmod +x ./out/intiface-engine

.PHONY: clean
clean:
	rm -rf ./out
```

- [ ] **Step 3: Test the download**

```bash
cd backend && make
ls -lh out/intiface-engine
```

Expected: binary downloaded, ~20–60 MB, executable.

- [ ] **Step 4: Verify the binary starts**

```bash
./backend/out/intiface-engine --help 2>&1 | head -5
```

Expected: usage/help text printed. If the binary is for the wrong architecture, check the releases page for the correct musl variant (look for `x86_64-unknown-linux-musl`).

- [ ] **Step 5: Commit**

```bash
git add backend/Makefile
git commit -m "feat: download intiface-engine binary in Makefile"
```

---

### Task 10: Frontend test harness and @decky/api mock

**Files:**
- Create: `tests/frontend/harness/index.html`
- Create: `tests/frontend/harness/main.tsx`
- Create: `tests/frontend/harness/vite.config.ts`
- Create: `tests/frontend/mocks/decky-api.ts`
- Modify: `package.json`

- [ ] **Step 1: Add Vite, Playwright and React to package.json devDependencies**

```bash
pnpm add -D vite @vitejs/plugin-react @playwright/test react react-dom
pnpm exec playwright install chromium
```

- [ ] **Step 2: Add test scripts to package.json**

Edit `package.json` scripts section to add:

```json
"test:ui:serve": "vite --config tests/frontend/harness/vite.config.ts tests/frontend/harness",
"test:ui": "playwright test --config tests/frontend/playwright.config.ts"
```

- [ ] **Step 3: Create Vite config**

Create `tests/frontend/harness/vite.config.ts`:

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@decky/api': path.resolve(__dirname, '../mocks/decky-api.ts'),
    },
  },
});
```

- [ ] **Step 4: Create harness HTML entry**

Create `tests/frontend/harness/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Intiface Plugin Test Harness</title>
    <style>
      body { background: #1a1a1a; color: #fff; font-family: sans-serif; }
      #root { width: 320px; margin: 40px auto; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create harness main.tsx**

Create `tests/frontend/harness/main.tsx`:

```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';

// Set up default callable mocks before the plugin module loads
// (the mock module sets window.__deckyTestAPI__ when it initialises)
import '../mocks/decky-api';

import pluginDescriptor from '../../../src/index';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div>{pluginDescriptor.content}</div>
  </React.StrictMode>
);
```

- [ ] **Step 6: Create @decky/api mock**

Create `tests/frontend/mocks/decky-api.ts`:

```typescript
type AnyFn = (...args: unknown[]) => unknown;

const _callables = new Map<string, AnyFn>();
const _callLog = new Map<string, unknown[][]>();
const _handlers = new Map<string, AnyFn[]>();

export function callable<TArgs extends unknown[], TRet>(
  name: string
): (...args: TArgs) => Promise<TRet> {
  return async (...args: TArgs): Promise<TRet> => {
    const log = _callLog.get(name) ?? [];
    log.push(args);
    _callLog.set(name, log);
    const impl = _callables.get(name);
    if (impl) return impl(...args) as TRet;
    console.warn(`[decky-api mock] no impl for callable "${name}", returning null`);
    return null as unknown as TRet;
  };
}

export function addEventListener<TArgs extends unknown[]>(
  event: string,
  handler: (...args: TArgs) => void
): (...args: TArgs) => void {
  const list = _handlers.get(event) ?? [];
  list.push(handler as AnyFn);
  _handlers.set(event, list);
  return handler;
}

export function removeEventListener<TArgs extends unknown[]>(
  event: string,
  handler: (...args: TArgs) => void
): void {
  const list = _handlers.get(event) ?? [];
  _handlers.set(event, list.filter(h => h !== handler));
}

export function definePlugin<T>(factory: () => T): T {
  return factory();
}

export const toaster = {
  toast: (_opts: unknown) => {},
};

// ── Test control surface ──────────────────────────────────────────────────────

const testAPI = {
  mockCallable(name: string, impl: AnyFn): void {
    _callables.set(name, impl);
  },
  fireEvent(name: string, ...args: unknown[]): void {
    (_handlers.get(name) ?? []).forEach(h => h(...args));
  },
  callLog(name: string): unknown[][] {
    return _callLog.get(name) ?? [];
  },
  resetAll(): void {
    _callables.clear();
    _callLog.clear();
    _handlers.clear();
  },
};

// Default callable implementations so the component renders without errors
testAPI.mockCallable('get_status', async () => ({ running: false, connected: false, port: 12345 }));
testAPI.mockCallable('get_devices', async () => []);
testAPI.mockCallable('start_engine', async () => ({ success: true }));
testAPI.mockCallable('stop_engine', async () => ({ success: true }));

(window as unknown as Record<string, unknown>)['__deckyTestAPI__'] = testAPI;
```

- [ ] **Step 7: Verify the harness starts**

```bash
pnpm run test:ui:serve
```

Open http://localhost:5173 in a browser. Expected: dark page, plugin content renders (may be empty until `src/index.tsx` is updated in the next task). Stop the server with Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git add tests/frontend/ package.json pnpm-lock.yaml
git commit -m "test: add frontend Vite harness and @decky/api mock"
```

---

### Task 11: Rewrite src/index.tsx with status panel and device list

**Files:**
- Modify: `src/index.tsx`

- [ ] **Step 1: Rewrite src/index.tsx**

```typescript
import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from '@decky/ui';
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
} from '@decky/api';
import { useState, useEffect } from 'react';
import { FaHeart } from 'react-icons/fa';

const startEngine = callable<[], { success: boolean; error?: string }>('start_engine');
const stopEngine = callable<[], { success: boolean }>('stop_engine');
const getStatus = callable<[], { running: boolean; connected: boolean; port: number }>('get_status');
const getDevices = callable<[], { id: number; name: string; actuators: number }[]>('get_devices');

type DeviceInfo = { id: number; name: string; actuators: number };
type EngineStatus = { running: boolean; connected: boolean; port: number };

function Content() {
  const [status, setStatus] = useState<EngineStatus>({
    running: false,
    connected: false,
    port: 12345,
  });
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = async () => {
    const s = await getStatus();
    if (s) setStatus(s);
  };

  const refreshDevices = async () => {
    const d = await getDevices();
    if (d) setDevices(d);
  };

  useEffect(() => {
    refreshStatus();
    refreshDevices();

    const onStatusChanged = () => void refreshStatus();
    const onDevicesChanged = () => void refreshDevices();

    window.addEventListener('intiface:status_changed', onStatusChanged);
    window.addEventListener('intiface:devices_changed', onDevicesChanged);

    return () => {
      window.removeEventListener('intiface:status_changed', onStatusChanged);
      window.removeEventListener('intiface:devices_changed', onDevicesChanged);
    };
  }, []);

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    try {
      if (status.running) {
        await stopEngine();
      } else {
        const result = await startEngine();
        if (!result.success && result.error) {
          setError(result.error);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <PanelSection title="Intiface Engine">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={handleToggle} disabled={loading}>
            {loading ? 'Working…' : status.running ? 'Stop Engine' : 'Start Engine'}
          </ButtonItem>
        </PanelSectionRow>
        {error && (
          <PanelSectionRow>
            <div style={{ color: '#f88', fontSize: '12px' }}>{error}</div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <div style={{ fontSize: '12px', color: status.connected ? '#8f8' : '#888' }}>
            {status.connected
              ? `Connected · port ${status.port}`
              : 'Disconnected'}
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Devices">
        {devices.length === 0 ? (
          <PanelSectionRow>
            <div style={{ fontSize: '12px', color: '#888' }}>No devices connected</div>
          </PanelSectionRow>
        ) : (
          devices.map(dev => (
            <PanelSectionRow key={dev.id}>
              <div style={{ fontSize: '13px' }}>{dev.name}</div>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  const engineStatusListener = addEventListener<
    [running: boolean, connected: boolean, port: number]
  >('engine_status_changed', (_running, _connected, _port) => {
    window.dispatchEvent(new CustomEvent('intiface:status_changed'));
  });

  const deviceAddedListener = addEventListener<[id: number, name: string, actuators: number]>(
    'device_added',
    (_id, _name, _actuators) => {
      window.dispatchEvent(new CustomEvent('intiface:devices_changed'));
    }
  );

  const deviceRemovedListener = addEventListener<[id: number]>(
    'device_removed',
    (_id) => {
      window.dispatchEvent(new CustomEvent('intiface:devices_changed'));
    }
  );

  return {
    name: 'Intiface',
    titleView: <div className={staticClasses.Title}>Intiface</div>,
    content: <Content />,
    icon: <FaHeart />,
    onDismount() {
      removeEventListener('engine_status_changed', engineStatusListener);
      removeEventListener('device_added', deviceAddedListener);
      removeEventListener('device_removed', deviceRemovedListener);
    },
  };
});
```

- [ ] **Step 2: Build the frontend**

```bash
pnpm run build
```

Expected: builds without TypeScript errors.

- [ ] **Step 3: Verify harness renders the UI**

```bash
pnpm run test:ui:serve
```

Open http://localhost:5173. Expected: dark page with "Intiface Engine" section, "Start Engine" button, "Disconnected" status, "Devices" section with "No devices connected". Stop server.

- [ ] **Step 4: Commit**

```bash
git add src/index.tsx
git commit -m "feat: add status panel and device list UI"
```

---

### Task 12: Playwright config and frontend tests

**Files:**
- Create: `tests/frontend/playwright.config.ts`
- Create: `tests/frontend/connect.spec.ts`
- Create: `tests/frontend/devices.spec.ts`

- [ ] **Step 1: Create Playwright config**

Create `tests/frontend/playwright.config.ts`:

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  use: {
    baseURL: 'http://localhost:5173',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'pnpm run test:ui:serve',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env['CI'],
  },
});
```

- [ ] **Step 2: Write connect flow tests**

Create `tests/frontend/connect.spec.ts`:

```typescript
import { test, expect, Page } from '@playwright/test';

type TestAPI = {
  mockCallable: (name: string, impl: (...args: unknown[]) => unknown) => void;
  fireEvent: (name: string, ...args: unknown[]) => void;
  callLog: (name: string) => unknown[][];
};

async function api(page: Page): Promise<TestAPI> {
  return page.evaluateHandle(() => (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'])
    .then(h => h.asElement() ? h as unknown as TestAPI : h as unknown as TestAPI);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('button', { timeout: 5000 });
});

test('Start Engine button is visible in disconnected state', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Start Engine' })).toBeVisible();
});

test('clicking Start Engine calls start_engine callable', async ({ page }) => {
  await page.getByRole('button', { name: 'Start Engine' }).click();
  await page.waitForTimeout(200);

  const calls = await page.evaluate(
    () => (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('start_engine')
  );
  expect(calls).toHaveLength(1);
});

test('UI shows Connected after engine_status_changed event', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await expect(page.getByText(/Connected/)).toBeVisible({ timeout: 3000 });
});

test('Stop Engine button shown after engine starts', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await expect(page.getByRole('button', { name: 'Stop Engine' })).toBeVisible({ timeout: 3000 });
});

test('error message shown when start_engine fails', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('start_engine', async () => ({ success: false, error: 'Connection refused' }));
  });

  await page.getByRole('button', { name: 'Start Engine' }).click();

  await expect(page.getByText('Connection refused')).toBeVisible({ timeout: 3000 });
});

test('clicking Stop Engine calls stop_engine callable', async ({ page }) => {
  // Put UI into running state first
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await page.getByRole('button', { name: 'Stop Engine' }).click({ timeout: 3000 });
  await page.waitForTimeout(200);

  const calls = await page.evaluate(
    () => (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('stop_engine')
  );
  expect(calls).toHaveLength(1);
});
```

- [ ] **Step 3: Write device list tests**

Create `tests/frontend/devices.spec.ts`:

```typescript
import { test, expect, Page } from '@playwright/test';

type TestAPI = {
  mockCallable: (name: string, impl: (...args: unknown[]) => unknown) => void;
  fireEvent: (name: string, ...args: unknown[]) => void;
  callLog: (name: string) => unknown[][];
};

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('button', { timeout: 5000 });
});

test('shows "No devices connected" by default', async ({ page }) => {
  await expect(page.getByText('No devices connected')).toBeVisible();
});

test('device appears in list after device_added event', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Test Vibrator', actuators: 1 },
    ]);
    a.fireEvent('device_added', 0, 'Test Vibrator', 1);
  });

  await expect(page.getByText('Test Vibrator')).toBeVisible({ timeout: 3000 });
});

test('device removed from list after device_removed event', async ({ page }) => {
  // First add a device
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Test Vibrator', actuators: 1 },
    ]);
    a.fireEvent('device_added', 0, 'Test Vibrator', 1);
  });
  await expect(page.getByText('Test Vibrator')).toBeVisible({ timeout: 3000 });

  // Then remove it
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => []);
    a.fireEvent('device_removed', 0);
  });

  await expect(page.getByText('Test Vibrator')).not.toBeVisible({ timeout: 3000 });
  await expect(page.getByText('No devices connected')).toBeVisible();
});

test('multiple devices all appear in list', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Vibrator A', actuators: 1 },
      { id: 1, name: 'Vibrator B', actuators: 2 },
    ]);
    a.fireEvent('device_added', 0, 'Vibrator A', 1);
  });

  await expect(page.getByText('Vibrator A')).toBeVisible({ timeout: 3000 });
  await expect(page.getByText('Vibrator B')).toBeVisible({ timeout: 3000 });
});
```

- [ ] **Step 4: Run the frontend tests**

```bash
pnpm run test:ui
```

Expected: all tests pass. If a test fails because a selector doesn't match, inspect the rendered HTML at http://localhost:5173 and adjust the selector in the spec.

- [ ] **Step 5: Commit**

```bash
git add tests/frontend/playwright.config.ts tests/frontend/connect.spec.ts tests/frontend/devices.spec.ts
git commit -m "test: add Playwright frontend tests for connect and device list flows"
```

---

### Task 13: Update plugin.json metadata

**Files:**
- Modify: `plugin.json`

- [ ] **Step 1: Update plugin.json**

Replace `plugin.json` with:

```json
{
  "name": "Intiface",
  "author": "madrigal-eschat",
  "flags": ["_root"],
  "api_version": 1,
  "publish": {
    "tags": ["haptics", "intiface", "buttplug"],
    "description": "Self-contained Intiface Engine management for Steam Deck. Connect haptic devices without needing Intiface Central.",
    "image": ""
  }
}
```

Note: `_root` is kept because accessing Bluetooth and HID devices requires root. `debug` is removed (was a template placeholder).

- [ ] **Step 2: Commit**

```bash
git add plugin.json
git commit -m "chore: update plugin.json with correct name and metadata"
```

---

### Task 14: Full integration check

- [ ] **Step 1: Run backend test suite**

```bash
pytest tests/backend/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Build frontend**

```bash
pnpm run build
```

Expected: no TypeScript errors.

- [ ] **Step 3: Run frontend test suite**

```bash
pnpm run test:ui
```

Expected: all tests pass.

- [ ] **Step 4: Verify intiface-engine binary is present**

```bash
ls -lh backend/out/intiface-engine
```

Expected: file exists and is executable.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final integration check — all tests passing"
```

---

## Notes

### buttplug-py API uncertainty

The `_connect_client` method in `main.py` was written against the known `buttplug-py` API surface. Two things to verify when first running the lifecycle tests:

1. **`ProtocolSpec` enum value:** `ProtocolSpec.v3` may be `ProtocolSpec.V3`. Check with:
   ```bash
   python -c "from buttplug import ProtocolSpec; print([x for x in dir(ProtocolSpec) if not x.startswith('_')])"
   ```

2. **Device handler signature:** `on_device_added(emitter, dev)` may need to be `on_device_added(dev)`. If tests fail with "takes 1 positional argument but 2 were given", remove the `emitter` parameter.

### intiface-engine binary name

The exact release artifact filename must be confirmed at https://github.com/intiface/intiface-engine/releases. Update `INTIFACE_ENGINE_FILENAME` in `backend/Makefile` accordingly.

### py_modules strategy

If `py_modules/` grows large or causes CI issues, an alternative is to have the Docker build step run `pip install --target /out/py_modules buttplug-py websockets` and copy into the plugin zip. For MVP, committing py_modules is acceptable.
