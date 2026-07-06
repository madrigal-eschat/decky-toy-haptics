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


async def test_stop_engine_emits_disconnected_event(
    plugin, mock_subprocess, mock_server
):
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
    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
    with open(settings_path, "w") as f:
        json.dump({"port": mock_server.port, "autostart": True}, f)

    await plugin._main()

    assert plugin._process is not None
    status = await plugin.get_status()
    assert status["running"] is True


async def test_main_does_not_start_engine_when_autostart_false(
    plugin, mock_subprocess, mock_server, inject_decky
):
    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
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
