# Toy Haptics

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Deck that bundles and manages [`intiface-engine`](https://github.com/buttplugio/buttplug) — a headless [Buttplug](https://buttplug.io/) haptics server. Connect and control haptic devices directly from the Quick Access Menu, no separate Intiface Central install needed.

## Features

- Start and stop `intiface-engine` from the Steam Deck QAM
- See connected device names at a glance
- Auto-starts on boot (configurable)
- Games that speak the [Buttplug protocol](https://buttplug-spec.docs.buttplug.io/) connect directly to the bundled engine on `ws://localhost:12345`

## Development

### Requirements

- Node.js v18+ and [pnpm](https://pnpm.io/) (`brew install pnpm` on macOS)
- Python 3.10+ with pip
- Docker (to download the `intiface-engine` binary for the Steam Deck)

### Install dependencies

```bash
# Frontend
pnpm i

# Backend test dependencies
pip install -r tests/backend/requirements.txt
```

### Run the tests

**Backend (Python, pytest):**

```bash
pytest tests/backend/ -v
```

**Frontend (Playwright, headless Chromium):**

```bash
pnpm run test:ui
```

### Local UI dev server

Spin up the test harness in a browser to iterate on the React UI without a real Deck:

```bash
pnpm run test:ui:serve
```

Open [http://localhost:5173](http://localhost:5173). The harness uses a mock `@decky/api` — you can call `window.__deckyTestAPI__.fireEvent(...)` or `mockCallable(...)` from the browser console to simulate backend events.

### Build the frontend

```bash
pnpm run build
```

Output goes to `dist/index.js`.

### Watch mode (rebuild on save)

```bash
pnpm run watch
```

## Packaging for the Deck

Install the [Decky CLI](https://github.com/SteamDeckHomebrew/cli) (requires Docker):

```bash
decky plugin build
```

This single command builds the backend binary inside a SteamOS Docker container, compiles the frontend, and produces a ready-to-install zip at `out/Intiface.zip`.

Install it on your Deck via Decky Loader → "Install from ZIP".

### Deploy directly to a Deck (VSCode / rsync)

Copy `.vscode/defsettings.json` to `.vscode/settings.json` and set your Deck's IP/hostname, then use the **deploy** task in VSCode. Or run rsync manually:

```bash
rsync -avz --delete \
  dist/ main.py plugin.json package.json py_modules/ \
  deck@steamdeck.local:/home/deck/homebrew/plugins/Toy\ Haptics/
```

Restart the Decky plugin to pick up changes.

## Project structure

```
src/index.tsx          # React frontend (QAM panel)
main.py                # Python backend (Plugin class)
backend/Makefile       # Downloads intiface-engine binary
py_modules/            # Bundled Python deps (buttplug-py, websockets)
tests/
  backend/             # pytest tests (decky shim, mock Buttplug WS server)
  frontend/            # Playwright tests + Vite harness
docs/superpowers/      # Design specs and implementation plans
```

## Architecture

The Python `Plugin` class:
1. Spawns `intiface-engine` as a subprocess (`bin/intiface-engine --websocket-port 12345 ...`)
2. Connects a `buttplug-py` client to it
3. Emits `engine_status_changed`, `device_added`, `device_removed` events to the React frontend
4. Exposes `start_engine`, `stop_engine`, `get_status`, `get_devices`, `update_settings` as callables

The React frontend polls the backend on mount and listens to Decky events to keep the UI in sync.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
