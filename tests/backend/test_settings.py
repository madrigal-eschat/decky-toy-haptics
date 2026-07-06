import json
import os


async def test_load_settings_uses_defaults_when_no_file(plugin):
    await plugin._load_settings()

    assert plugin._settings["port"] == 12345
    assert plugin._settings["autostart"] is True


async def test_load_settings_reads_from_file(plugin, inject_decky):
    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
    with open(settings_path, "w") as f:
        json.dump({"port": 7777, "autostart": False}, f)

    await plugin._load_settings()

    assert plugin._settings["port"] == 7777
    assert plugin._settings["autostart"] is False


async def test_load_settings_merges_missing_keys_with_defaults(plugin, inject_decky):
    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
    with open(settings_path, "w") as f:
        json.dump({"port": 6666}, f)  # no autostart key

    await plugin._load_settings()

    assert plugin._settings["port"] == 6666
    assert plugin._settings["autostart"] is True  # filled from defaults


async def test_update_settings_persists_port(plugin, inject_decky):
    result = await plugin.update_settings(port=9999)

    assert result == {"success": True}
    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
    with open(settings_path) as f:
        saved = json.load(f)
    assert saved["port"] == 9999


async def test_update_settings_persists_autostart(plugin, inject_decky):
    await plugin.update_settings(autostart=False)

    settings_path = os.path.join(
        inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"
    )
    with open(settings_path) as f:
        saved = json.load(f)
    assert saved["autostart"] is False


async def test_get_status_returns_configured_port(plugin):
    plugin._settings = {"port": 8888, "autostart": True}

    status = await plugin.get_status()

    assert status["port"] == 8888
