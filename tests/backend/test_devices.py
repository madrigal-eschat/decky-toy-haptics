import asyncio
from tests.backend.conftest import wait_for_emit
from tests.backend.decky_mock import emit_recorder


async def test_get_devices_empty_before_connect(plugin):
    devices = await plugin.get_devices()

    assert devices == []


async def test_device_appears_after_connect(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Test Vibrator")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    devices = await plugin.get_devices()
    assert len(devices) == 1
    assert devices[0]["name"] == "Test Vibrator"
    assert devices[0]["id"] == 0


async def test_device_added_event_emitted(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Test Vibrator")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

    events = await wait_for_emit("device_added")

    device_id, device_name, actuators = events[0]
    assert device_name == "Test Vibrator"
    assert device_id == 0


async def test_multiple_devices_discovered(plugin, mock_subprocess, mock_server):
    mock_server.add_fake_device(0, "Vibrator A")
    mock_server.add_fake_device(1, "Vibrator B")
    plugin._settings = {"port": mock_server.port, "autostart": False}
    await plugin.start_engine()

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
