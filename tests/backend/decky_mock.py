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
