# Decky Plugin — Copilot Instructions

This is a [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Deck, based on the decky-plugin-template. It has a TypeScript/React frontend and a Python backend, with an optional compiled C binary backend.

## Build Commands

```bash
# Install dependencies
pnpm i

# Build frontend (outputs to dist/)
pnpm run build

# Watch mode for frontend development
pnpm run watch

# Update @decky/ui to latest
pnpm update @decky/ui --latest

# Build C backend (requires Docker)
cd backend && docker build -t decky-plugin-backend . && docker run --rm -v $(pwd):/backend decky-plugin-backend
```

There are no tests configured.

## Architecture

### Frontend (`src/index.tsx`)

- Entry point is `definePlugin()`, which returns `{ name, titleView, content, icon, onDismount }`.
- All UI components use `@decky/ui` (PanelSection, PanelSectionRow, ButtonItem, etc.) and React.
- Communication with the Python backend uses two patterns from `@decky/api`:
  - **Calls**: `callable<[arg1: Type, arg2: Type], ReturnType>("python_method_name")` — creates a typed function that invokes a Python method.
  - **Events**: `addEventListener("event_name", handler)` / `removeEventListener("event_name", handler)` — listens for events emitted by Python. Clean up listeners in `onDismount`.

### Backend (`main.py`)

- All backend logic lives in the `Plugin` class.
- Any `async def method(self, ...)` on `Plugin` is automatically callable from TypeScript via `callable()`.
- Lifecycle hooks:
  - `_main()` — called once on plugin load; start long-running tasks here.
  - `_unload()` — plugin is being stopped (but not removed).
  - `_uninstall()` — plugin is being uninstalled; clean up files/processes.
  - `_migration()` — runs before `_main()` on first load after update; use `decky.migrate_logs()`, `decky.migrate_settings()`, `decky.migrate_runtime()` here.
- Emit events to the frontend: `await decky.emit("event_name", arg1, arg2, ...)`.
- Log via `decky.logger.info()` / `decky.logger.error()` etc.
- Decky runtime paths: `decky.DECKY_HOME`, `decky.DECKY_USER_HOME`, `decky.DECKY_SETTINGS_DIR`, `decky.DECKY_RUNTIME_DIR`, `decky.DECKY_LOG_DIR`.

### C Binary Backend (`backend/`)

- Source in `backend/src/`, built by Docker using `ghcr.io/steamdeckhomebrew/holo-base:latest` (SteamOS base; swap for `holo-toolchain-rust` or `holo-toolchain-go` as needed).
- The Makefile **must** output binaries to `backend/out/` — CI picks them up from there and packages them into `bin/` in the final plugin zip.

### `defaults/`

Static files (configs, templates, themes) to be bundled alongside the plugin in the distribution zip.

## Key Conventions

- **TypeScript strict mode** is enabled (`noImplicitAny`, `strict`, `noUnusedLocals`, etc.). All types must be explicit.
- **Module resolution**: `"module": "ESNext"`, `"target": "ES2020"`, JSX via `react-jsx`.
- **Image/asset imports**: SVG, PNG, JPG modules are declared in `src/types.d.ts` as returning `string`.
- **`plugin.json`**: Metadata for the store (`name`, `author`, `flags`, `api_version`, `publish`). The `_root` flag means the plugin runs as root — only include if required.
- **`py_modules/`**: Place pure-Python dependencies here so they are available to `main.py` at runtime. Add `./py_modules` to `python.analysis.extraPaths` in `.vscode/settings.json` for intellisense.
- **Deploy to deck**: Configured via `.vscode/settings.json` (copied from `.vscode/defsettings.json`). Uses rsync over SSH. Target defaults: `steamdeck.local:22`, user `deck`.
