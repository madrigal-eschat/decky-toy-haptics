# decky-toy-haptics — Claude Instructions

Decky Loader plugin for Steam Deck. TypeScript/React frontend, Python backend, optional C binary backend.

## Build Commands

```bash
pnpm i                  # install deps
pnpm run build          # build frontend → dist/
pnpm run watch          # frontend watch mode
pnpm update @decky/ui --latest

# C backend (requires Docker)
cd backend && docker build -t decky-plugin-backend . && docker run --rm -v $(pwd):/backend decky-plugin-backend
```

No tests configured.

## Architecture

### Frontend (`src/index.tsx`)

Entry: `definePlugin()` → `{ name, titleView, content, icon, onDismount }`.

UI: `@decky/ui` (PanelSection, PanelSectionRow, ButtonItem, etc.) + React.

Backend comms via `@decky/api`:
- **Calls**: `callable<[arg1: Type], ReturnType>("python_method_name")`
- **Events**: `addEventListener("event_name", handler)` / `removeEventListener(...)` — clean up in `onDismount`

### Backend (`main.py`)

All logic in `Plugin` class. Any `async def method(self, ...)` auto-callable from TS via `callable()`.

Lifecycle:
- `_main()` — plugin load; start long-running tasks
- `_unload()` — plugin stopped (not removed)
- `_uninstall()` — plugin uninstalled; clean up files/processes
- `_migration()` — before `_main()` on first load after update; use `decky.migrate_logs/settings/runtime()`

Emit events: `await decky.emit("event_name", arg1, ...)`

Logging: `decky.logger.info/error/...`

Paths: `decky.DECKY_HOME`, `decky.DECKY_USER_HOME`, `decky.DECKY_SETTINGS_DIR`, `decky.DECKY_RUNTIME_DIR`, `decky.DECKY_LOG_DIR`

### C Binary Backend (`backend/`)

Source: `backend/src/`. Built via Docker using `ghcr.io/steamdeckhomebrew/holo-base:latest` (SteamOS base; swap for `holo-toolchain-rust` or `holo-toolchain-go` as needed).

Makefile **must** output to `backend/out/` — CI packages into `bin/` in final plugin zip.

### `defaults/`

Static files (configs, templates, themes) bundled in distribution zip.

## Key Conventions

- TypeScript strict mode: `noImplicitAny`, `strict`, `noUnusedLocals`. All types explicit.
- Module: `"module": "ESNext"`, `"target": "ES2020"`, JSX via `react-jsx`.
- Image/asset imports: SVG, PNG, JPG declared in `src/types.d.ts` as `string`.
- `plugin.json`: store metadata. `_root` flag = runs as root — only if required.
- `py_modules/`: pure-Python deps for `main.py`. Add to `python.analysis.extraPaths` in `.vscode/settings.json`.
- Deploy to deck: `.vscode/settings.json` (copy from `.vscode/defsettings.json`). rsync over SSH → `steamdeck.local:22`, user `deck`.
