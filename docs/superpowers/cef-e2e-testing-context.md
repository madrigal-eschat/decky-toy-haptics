# Context: Full VM E2E Testing via CEF (Option B)

**Purpose:** This document is a seed for a future brainstorming session on implementing full end-to-end UI testing for the `decky-intiface` plugin by driving the actual Steam overlay inside a SteamOS VM. It covers what is known, what is uncertain, and what would need to be researched or prototyped before a design can be committed to.

---

## What "Option B" means

Option A (the approach currently being implemented) tests the frontend against a mock of `@decky/api` in a standalone browser, and tests the Python backend against a mock Intiface server. It doesn't exercise the actual Steam overlay, the Decky injection layer, or the real `callable()` / `emit()` bridge.

Option B means: booting the SteamOS VM into gaming mode, running Steam + Decky Loader with the plugin installed, and using Playwright (or a similar automation tool) to drive the plugin UI inside the real Steam overlay — then asserting on both UI state and downstream effects (e.g., the Python backend sent the right commands to Intiface).

---

## Technical landscape

### Steam's Chromium (CEF) instance

Steam's UI — including gaming mode's "Big Picture" shell and the Quick Access Menu (QAM) where Decky plugins appear — runs on a modified Chromium via CEF (Chromium Embedded Framework). This is not a full browser; it's an embedded shell. Steam can be launched with Chromium-style command-line flags that enable CDP (Chrome DevTools Protocol) remote debugging.

The flag of interest is `--remote-debugging-port=<port>`. On a standard desktop Linux install this can be passed when launching Steam. On SteamOS, Steam is launched as a systemd unit; modifying its launch flags is possible but may be reset by system updates.

The known/commonly used port for Steam's CEF debugger is **8080**, but this is not guaranteed and should be verified empirically on the target SteamOS version.

### Decky Loader's architecture

- Decky runs a local HTTP/WebSocket server, default port **1337**.
- Plugin frontends are JavaScript bundles served from `http://localhost:1337/plugins/<plugin-name>/dist/index.js`.
- At runtime, Decky injects this JavaScript into the Steam CEF context; the plugin UI renders inside an iframe (or React portal) within the QAM overlay.
- Decky has a **developer mode** accessible via its settings. Enabling it may expose additional debugging surfaces (to be verified).
- Decky's GitHub: https://github.com/SteamDeckHomebrew/decky-loader

### Playwright `connectOverCDP`

Playwright can attach to any running Chromium instance that exposes a CDP endpoint:

```typescript
const browser = await chromium.connectOverCDP('http://localhost:8080');
const contexts = browser.contexts();
// find the right page/iframe
```

CDP exposes a list of "targets" (tabs, iframes, workers). Steam's Chromium instance will have many targets — the main Shell, the store, library, overlay, and any injected iframes including Decky's. The automation challenge is reliably identifying and attaching to the correct target.

---

## Known challenges

### 1. Finding the right CDP target

Steam's Chromium hosts many concurrent targets. The Decky plugin does not run as a top-level page — it runs as injected JS / an iframe within the QAM. Playwright's `connectOverCDP` gives you a flat list of pages; you would need to filter by URL pattern (e.g., `localhost:1337/...`) or by page title to land on the right target. This filtering logic may be fragile across Steam UI updates.

### 2. Opening the QAM programmatically

To reach the plugin's UI, the user must open Steam's Quick Access Menu and navigate to the plugin's panel. There is no known programmatic API to do this from outside the Chromium instance. Options:

- **Keyboard shortcut simulation**: The QAM is typically opened with the Steam button + A on a Deck, or a keyboard shortcut in desktop mode. This could be simulated via `xdotool` or `ydotool` (for Wayland) inside the VM.
- **CDP `Input.dispatchKeyEvent`**: Once attached to the right Chromium target, CDP can inject key events directly. But which target to send them to first (before the QAM is open) is unclear.
- **Decky's own WebSocket API**: Decky exposes a WebSocket API on port 1337. It may be possible to trigger plugin events or navigation through this rather than simulating physical input. This needs investigation.

### 3. SteamOS Wayland vs X11

Gaming mode SteamOS runs on Wayland (via gamescope). Tools like `xdotool` won't work without an XWayland bridge. `ydotool` or `wtype` are alternatives that work with Wayland but require the `uinput` kernel module and appropriate permissions. The VM may or may not expose `/dev/uinput`.

### 4. VM-specific constraints

The SteamOS VM is likely running without GPU passthrough, which means Steam gaming mode may behave differently (framerate, overlay rendering) compared to real hardware. Whether gamescope + the Steam overlay + CEF function correctly in a software-rendered VM is uncertain and may require specific VM configuration.

### 5. Steam update fragility

Steam updates frequently. The CEF version, the DOM structure of the QAM, and Decky's injection point can all change. Tests that rely on CSS selectors or DOM structure within the Steam shell (not the plugin's own DOM) are at high risk of breaking silently on Steam updates.

---

## What a working setup might look like

```
SteamOS VM (gaming mode, Steam + Decky running)
  └─ Steam launched with --remote-debugging-port=8080
       └─ Chromium CEF exposes CDP at localhost:8080

Test runner (host or VM)
  └─ Playwright test
       ├─ connectOverCDP('http://<vm-ip>:8080')
       ├─ find target matching 'localhost:1337' (Decky plugin iframe)
       ├─ simulate QAM open (keyboard shortcut via ydotool or Decky WS API)
       ├─ interact with plugin UI (click connect button, etc.)
       └─ assert: backend called Intiface, UI reflects connected state
```

---

## Open questions for the brainstorming session

1. **Can Steam's CEF be reliably exposed on a known port in SteamOS?** What's the exact mechanism — modifying the systemd unit? A wrapper script? Does Decky provide a hook for this?

2. **Does Decky's developer mode or its WebSocket API expose enough to open the QAM / navigate to a plugin without simulating hardware input?**

3. **Is gamescope + Steam overlay functional in a software-rendered SteamOS VM?** If not, is desktop mode (non-gaming mode) a viable fallback for UI testing?

4. **Is the Decky plugin iframe addressable as a distinct CDP target**, or is it injected into the main Shell page's DOM in a way that requires using the Shell target and querying into an iframe?

5. **What test isolation strategy is appropriate?** Each test run likely needs a fresh plugin state. Can the plugin's settings/state be reset between tests from outside Steam, or does that require tearing down and restarting the plugin?

6. **What assertion strategy covers the backend?** The UI test asserts on visual state; verifying that Intiface actually received the right commands requires either a mock Intiface server with an assertion API, or log-scraping. Which is more tractable?

---

## Suggested starting point for the session

Before designing the test infrastructure, spend time on a **proof-of-concept spike**:

1. Enable CDP on Steam in the SteamOS VM and confirm you can connect with Playwright.
2. List all CDP targets and identify which one corresponds to the Decky QAM iframe.
3. Programmatically open the QAM (by any means) and assert you can read DOM elements from the plugin.

Only once this spike succeeds should a full design be committed to — many of the unknowns above could be blockers, and it's better to find out early.

---

## Relevant links

- Decky Loader source: https://github.com/SteamDeckHomebrew/decky-loader
- Decky plugin template: https://github.com/SteamDeckHomebrew/decky-plugin-template
- Playwright `connectOverCDP` docs: https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp
- Chrome DevTools Protocol: https://chromedevtools.github.io/devtools-protocol/
- `ydotool` (Wayland input simulation): https://github.com/ReimuNotMoe/ydotool
