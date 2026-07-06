# Design: decky-intiface Plugin

**Date:** 2026-06-26
**Status:** Approved
**Scope:** Full plugin design with phased delivery. MVP is delivered first; later phases are designed now so architecture decisions don't need revisiting.

---

## What we're building

A self-contained Decky Loader plugin for Steam Deck that:

1. Bundles and manages `intiface-engine` (the headless Buttplug server) as a subprocess
2. Exposes a device management UI in the Steam Quick Access Menu — replacing Intiface Central for Deck users
3. Eventually intercepts Steam controller rumble events via Linux evdev and forwards them as buttplug haptic commands to connected devices

No external Intiface Central installation is required.

---

## Phased delivery

### MVP (Phase 1) — deliver now

- Bundle `intiface-engine` binary (Linux x86_64, SteamOS target)
- Python backend starts/stops it, connects via `buttplug-py`, surfaces status and device list
- Minimal UI: engine start/stop + status indicator, device list (read-only)
- Games that natively speak the Buttplug protocol can connect directly to the bundled engine

### Phase 2 — evdev haptics bridge

- Python evdev listener watches the controller's force-feedback device
- Translates FF rumble magnitude → buttplug `ScalarCmd` intensity, forwarded to all (or selected) connected devices
- Configurable: source evdev device, intensity scaling
- UI additions: bridge enable/disable toggle, source device selector, intensity scale slider
- Reference: https://github.com/intiface/intiface-game-haptics-router (Windows-only; this is the Linux-native equivalent built in Python using `python-evdev`)

### Phase 3 — full UI

- Per-device controls: intensity slider, pattern selection, test button
- Settings panel: engine port, device type filters, log level
- Log viewer (streams `log_entry` events from backend)
- Per-device configuration persistence

---

## Architecture

```
Plugin zip
├── backend/out/intiface-engine   (Linux x86_64 binary, built via Docker)
├── main.py                       (Python Plugin class)
├── dist/index.js                 (React/TypeScript frontend bundle)
├── plugin.json
└── package.json
```

### Python backend (`main.py`)

The `Plugin` class:

- **`_main()`** — reads settings, starts `intiface-engine` subprocess on configured port, connects `buttplug-py` client, begins emitting device events
- **`_unload()`** — disconnects client, terminates `intiface-engine`
- **`_migration()`** — migrates legacy settings paths

Callables exposed to frontend:

| Callable | Args | Returns | Notes |
|---|---|---|---|
| `start_engine` | — | `{ success, error? }` | Starts subprocess + client |
| `stop_engine` | — | `{ success }` | Stops cleanly |
| `get_status` | — | `{ running, connected, port }` | |
| `get_devices` | — | `[{ id, name, actuators }]` | |
| `update_settings` | `{ port?, ... }` | `{ success }` | Persists to settings dir |

Events emitted to frontend:

| Event | Payload |
|---|---|
| `engine_status_changed` | `{ running, connected }` |
| `device_added` | `{ id, name, actuators }` |
| `device_removed` | `{ id }` |
| `error` | `{ message }` |

*(Phase 2 adds: `bridge_status_changed`. Phase 3 adds: `log_entry`)*

Settings persisted to `decky.DECKY_SETTINGS_DIR/settings.json`:

```json
{
  "port": 12345,
  "autostart": true
}
```

`port` defaults to `12345`. `autostart` defaults to `true` — if true, `_main()` starts the engine immediately without waiting for the user to press start.

### Frontend (`src/index.tsx`)

MVP panels:

- **Status panel**: engine running indicator, start/stop button, port display
- **Device list**: list of connected devices (name only for MVP)

Phase 2 additions:
- **Bridge panel**: evdev bridge enable/disable, source device selector, intensity scale

Phase 3 additions:
- **Per-device controls**, **Settings panel**, **Log viewer**

### Backend binary (`backend/`)

`backend/Makefile` downloads the appropriate `intiface-engine` release from GitHub (`intiface/intiface-engine`) for `x86_64-unknown-linux-musl` (musl for SteamOS compatibility) and copies it to `backend/out/intiface-engine`.

`backend/Dockerfile` uses `ghcr.io/steamdeckhomebrew/holo-base:latest` as required by the Decky build system.

---

## Testing infrastructure (Option A)

Two independent test suites. Neither requires Steam, Decky, or a running `intiface-engine`.

### Backend (`tests/backend/`)

**Framework:** `pytest` + `pytest-asyncio`

**Decky shim** (`tests/backend/decky_mock.py`): injected into `sys.modules['decky']` before `main.py` import. Stubs `decky.logger`, `decky.emit` (records calls), all `DECKY_*` path constants (→ `tmp_path`), and `migrate_*` (no-ops).

**Mock Intiface server** (`tests/backend/mock_intiface.py`): minimal asyncio WebSocket server implementing Buttplug v3 JSON protocol — enough to handle `RequestServerInfo`, `RequestDeviceList`, `StartScanning`/`ScanningFinished`/`DeviceAdded`, `ScalarCmd`/`VibrateCmd` → `Ok`. Exposes `server.received_commands` for assertions. Starts on a random port per test; the `conftest.py` fixture passes that port to the `Plugin` instance via `update_settings` before calling `_main()`.

**Test files:**

| File | Covers |
|---|---|
| `test_lifecycle.py` | `_main` starts engine; `_unload` stops it cleanly; crash emits error event |
| `test_connection.py` | Connect flow; `ServerInfo` validation; connection failure surfaces error |
| `test_devices.py` | Scanning → device list populated; `device_added`/`device_removed` events emitted |
| `test_haptics.py` | *(Phase 2)* evdev FF event → correct `ScalarCmd` sent to mock server |
| `test_settings.py` | `update_settings` persists; settings applied to subprocess args on next start |

### Frontend (`tests/frontend/`)

**Harness:** Vite dev server serving `tests/frontend/harness/index.html`. Module aliases:

- `@decky/api` → `tests/frontend/mocks/decky-api.ts`
- `@decky/ui` → real package (React components work in plain Chromium)

**`@decky/api` mock** exposes `window.__deckyTestAPI__`:

```ts
mockCallable(name, impl)   // configure callable response before interacting
fireEvent(name, ...args)   // inject backend event into the plugin
callLog(name)              // inspect what the plugin called
```

**Playwright config** (`tests/frontend/playwright.config.ts`): Chromium only, `webServer` runs `pnpm run test:ui:serve`.

**Test files:**

| File | Covers |
|---|---|
| `connect.spec.ts` | Start button → `start_engine` called → status indicator updates; stop flow; error state |
| `devices.spec.ts` | `device_added` event → device appears in list; `device_removed` → removed |
| `bridge.spec.ts` | *(Phase 2)* Bridge toggle, device selector, scale input |

**New `package.json` scripts:**

```json
"test:ui:serve": "vite tests/frontend/harness",
"test:ui":       "playwright test --config tests/frontend/playwright.config.ts"
```

### Running the suites

```bash
# Backend
pip install pytest pytest-asyncio websockets buttplug-py
pytest tests/backend/

# Frontend (after pnpm i)
pnpm run test:ui
```

---

## What this does not cover

- Steam overlay / Decky injection layer (see `docs/superpowers/cef-e2e-testing-context.md` for the future Option B approach)
- Physical haptic device communication (mock server only)
- Windows or non-SteamOS Linux targets
