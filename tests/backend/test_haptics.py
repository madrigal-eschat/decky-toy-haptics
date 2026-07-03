import asyncio
import json
import os
import pytest
import bson
from tests.backend.conftest import MockProbeController
from tests.backend.decky_mock import emit_recorder


# ── Helpers ────────────────────────────────────────────────────────────────────

def rumble_points(intensity: float, length_ms: int) -> list[dict]:
    """Return a 2-point rumble: immediate intensity at 0ms, zero at length_ms."""
    return [{"dt_ms": 0, "intensity": intensity}, {"dt_ms": length_ms, "intensity": 0.0}]


# ── Rumble → ScalarCmd ──────────────────────────────────────────────────

async def test_haptic_play_sends_scalar_cmd(plugin, mock_subprocess, mock_server, mock_probe):
    mock_server.add_fake_device(0, "Test Toy")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    controller, _ = mock_probe
    await controller.emit_haptic("steam-input/0", rumble_points(0.8, 200))
    await asyncio.sleep(0.1)

    cmds = [c for c in mock_server.received_commands if "ScalarCmd" in c]
    assert len(cmds) >= 1
    scalar = cmds[0]["ScalarCmd"]["Scalars"][0]["Scalar"]
    assert abs(scalar - 0.8) < 0.05


async def test_scale_halves_intensity(plugin, mock_subprocess, mock_server, mock_probe):
    mock_server.add_fake_device(0, "Test Toy")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 0.5}
    await plugin.start_engine()

    controller, _ = mock_probe
    await controller.emit_haptic("steam-input/0", rumble_points(1.0, 200))
    await asyncio.sleep(0.1)

    cmds = [c for c in mock_server.received_commands if "ScalarCmd" in c]
    assert len(cmds) >= 1
    scalar = cmds[0]["ScalarCmd"]["Scalars"][0]["Scalar"]
    assert abs(scalar - 0.5) < 0.05


# ── Stop interrupts ───────────────────────────────────────────────────

async def test_stop_sends_zero_scalar(plugin, mock_subprocess, mock_server, mock_probe):
    mock_server.add_fake_device(0, "Test Toy")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    controller, _ = mock_probe
    await controller.emit_stop("steam-input/0")
    await asyncio.sleep(0.1)

    cmds = [c for c in mock_server.received_commands if "ScalarCmd" in c]
    assert len(cmds) >= 1
    scalar = cmds[-1]["ScalarCmd"]["Scalars"][0]["Scalar"]
    assert scalar == 0.0


async def test_stop_cancels_in_flight_sequence(plugin, mock_subprocess, mock_server, mock_probe):
    mock_server.add_fake_device(0, "Test Toy")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    controller, _ = mock_probe
    long_pts = [{"dt_ms": 0, "intensity": 0.9}, {"dt_ms": 2000, "intensity": 0.0}]
    await controller.emit_haptic("steam-input/0", long_pts)
    await asyncio.sleep(0.05)
    await controller.emit_stop("steam-input/0")
    await asyncio.sleep(0.1)

    cmds = [c for c in mock_server.received_commands if "ScalarCmd" in c]
    assert cmds[-1]["ScalarCmd"]["Scalars"][0]["Scalar"] == 0.0


# ── Device routing ───────────────────────────────────────────────────

async def test_unmapped_device_targets_all_toys(plugin, mock_subprocess, mock_server, mock_probe):
    mock_server.add_fake_device(0, "Toy A")
    mock_server.add_fake_device(1, "Toy B")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    controller, _ = mock_probe
    await controller.emit_haptic("steam-input/0", rumble_points(0.5, 100))
    await asyncio.sleep(0.15)

    indices = {c["ScalarCmd"]["DeviceIndex"] for c in mock_server.received_commands
               if "ScalarCmd" in c}
    assert 0 in indices
    assert 1 in indices


# ── bridge_status_changed event ─────────────────────────────────────

async def test_set_bridge_enabled_emits_status_event(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": False, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()
    emit_recorder.reset()

    await plugin.set_bridge_enabled(enabled=True)

    events = emit_recorder.events_named("bridge_status_changed")
    assert len(events) == 1
    enabled, device = events[0]
    assert enabled is True


# ── bridge callables / settings ──────────────────────────────────────

async def test_set_bridge_scale_updates_bridge(plugin, mock_subprocess, mock_server, mock_probe):
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    result = await plugin.set_bridge_scale(0.3)
    assert result == {"success": True}
    assert plugin._bridge._scale == pytest.approx(0.3)


async def test_update_settings_persists_bridge_fields(plugin, inject_decky):
    await plugin.update_settings(bridge_intensity_scale=0.7, bridge_enabled=False)

    path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(path) as f:
        saved = json.load(f)
    assert saved["bridge_intensity_scale"] == pytest.approx(0.7)
    assert saved["bridge_enabled"] is False


# ── lifecycle integration ─────────────────────────────────────────────

async def test_bridge_starts_with_engine_when_enabled(plugin, mock_subprocess, mock_server, mock_probe):
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    assert plugin._bridge is not None


async def test_bridge_does_not_start_when_disabled(plugin, mock_subprocess, mock_server):
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": False, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    assert plugin._bridge is None


async def test_bridge_stops_with_engine(plugin, mock_subprocess, mock_server, mock_probe):
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()
    await plugin.stop_engine()

    assert plugin._bridge is None
