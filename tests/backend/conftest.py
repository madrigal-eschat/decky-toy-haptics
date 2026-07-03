import sys
import asyncio
import os
import bson
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


class MockProbeController:
    """Controls what a mock haptics-probe subprocess emits over its stdout pipe."""

    def __init__(self) -> None:
        self._writer: asyncio.StreamWriter | None = None

    def set_writer(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer

    async def emit(self, doc: dict) -> None:
        assert self._writer is not None
        self._writer.write(bson.dumps(doc))
        await self._writer.drain()

    async def emit_haptic(self, device: str, points: list[dict]) -> None:
        await self.emit({"type": "haptic", "device": device, "points": points})

    async def emit_stop(self, device: str) -> None:
        await self.emit({"type": "stop", "device": device})

    async def emit_device_added(self, device: str, name: str, path: str) -> None:
        await self.emit({"type": "device_added", "device": device, "name": name, "path": path})


@pytest_asyncio.fixture
async def mock_probe(monkeypatch, mock_subprocess):
    """Replaces the haptics-probe subprocess with a pipe-backed BSON stream.

    Other `asyncio.create_subprocess_exec` calls (e.g. intiface-engine) still
    resolve to the generic `mock_subprocess` fake process.
    """
    controller = MockProbeController()
    loop = asyncio.get_event_loop()

    r_fd, w_fd = os.pipe()
    r_stream = asyncio.StreamReader()
    r_protocol = asyncio.StreamReaderProtocol(r_stream)
    r_transport, _ = await loop.connect_read_pipe(lambda: r_protocol, os.fdopen(r_fd, "rb", 0))

    w_transport, w_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, os.fdopen(w_fd, "wb", 0)
    )
    writer = asyncio.StreamWriter(w_transport, w_protocol, None, loop)
    controller.set_writer(writer)

    fake_probe_proc = MagicMock()
    fake_probe_proc.returncode = None
    fake_probe_proc.stdout = r_stream
    fake_probe_proc.terminate = MagicMock()
    fake_probe_proc.wait = AsyncMock(return_value=0)

    async def fake_exec(program, *args, **kwargs):
        if "haptics-probe" in str(program):
            return fake_probe_proc
        return mock_subprocess

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    yield controller, fake_probe_proc

    writer.close()
    r_transport.close()


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
