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
