# Design: Phase 2 — evdev Haptics Bridge

**Date:** 2026-06-27
**Status:** Approved
**Scope:** Phase 2 of the decky-toy-haptics plugin. Intercepts Steam Input force-feedback effects via eBPF and forwards them as Buttplug `ScalarCmd` sequences to connected toys.

---

## What we're building

A Linux-native equivalent of the Windows [intiface-game-haptics-router](https://github.com/intiface/intiface-game-haptics-router), built in Rust (eBPF + evdev) with a thin Python integration layer.

When a game sends rumble/haptic effects through Steam Input (XInput/SDL → Steam → kernel force-feedback), the bridge captures those effects with full waveform data, translates them into timed Buttplug `ScalarCmd` sequences, and drives connected toys in real time.

---

## Architecture

```
Game → XInput/SDL rumble
         ↓ Steam Input
    Steam process writes EVIOCSFF ioctl + EV_FF play events
         ↓
    [kernel] eBPF tracepoint fires on EVIOCSFF → captures ff_effect struct
    haptics-probe (Rust, Aya) also reads EV_FF play/stop via evdev
         ↓ unified ordered stream
    BSON frames on stdout
         ↓
    Python HapticsBridge reads, schedules ScalarCmd sequences
         ↓ buttplug-py
    intiface-engine → toy devices
```

### Components

```
backend/haptics-probe/          Rust Aya workspace (new)
├── haptics-probe-ebpf/         BPF program: tracepoint on sys_enter_ioctl
└── haptics-probe/              Userspace loader + evdev reader + translator

bin/haptics-probe               compiled output, shipped in plugin zip
bin/intiface-engine             existing

main.py                         Plugin class (extended)
  HapticsBridge                 new: manages probe subprocess + schedules ScalarCmds

src/index.tsx                   Frontend (extended)
  BridgePanel                   new component: toggle, device list, scale slider
```

---

## Rust haptics-probe

### Responsibilities

1. **eBPF tracepoint** (`sys_enter_ioctl` filtered to `EVIOCSFF`) — captures `ff_effect` struct from the uploading process's userspace memory via `bpf_probe_read_user`. Stores effect data keyed by `(pid, fd, effect_id)`.
2. **evdev reader** — opens all FF-capable `/dev/input/event*` devices, watches for `EV_FF` play/stop events. On play: looks up stored effect, computes pre-sampled point sequence, emits BSON. On stop: emits stop event.
3. **Device enumeration** — on startup, emits `device_added` for each FF-capable device found. Monitors for hotplug.
4. **FF → ScalarCmd translation** — all waveform math in Rust, Python receives ready-to-schedule points.

### Device ID

Each device is identified by its `phys` string from `EVIOCGPHYS` (e.g. `steam-input/0`, `usb-0000:00:14.0-2/input0`). Falls back to `basename(path)` (e.g. `event5`) if `phys` is empty. This ID is stable across reboots and tied to physical port/slot.

### Output throttling

The probe enforces a minimum 10ms interval between emitted BSON frames. If a haptic sequence would produce points closer than 10ms apart, points are merged (take the higher intensity) or dropped to respect the interval. This matches the minimum sensible Buttplug command rate and prevents overwhelming the IPC pipe.

`stop` events are **exempt from throttling** — they are emitted immediately and bypass the 10ms gate. On the Python side, a received `stop` cancels any in-flight sequence task for that device and sends `ScalarCmd(0)` without waiting for the next scheduled point.

### CLI interface

```
haptics-probe                   # monitor all FF devices, stream BSON to stdout
haptics-probe --list-devices    # print JSON array of FF devices, exit
```

### BSON output protocol

Each document is self-delimiting (4-byte BSON length prefix). Python reads length, then document.

**Device events:**
```bson
{ type: "device_added",   device: "steam-input/0", name: "Steam Virtual Gamepad",
                          path: "/dev/input/event5" }
{ type: "device_removed", device: "steam-input/0" }
```

**Haptic event (pre-translated, ready for ScalarCmd scheduling):**
```bson
{ type: "haptic", device: "steam-input/0",
  points: [
    { dt_ms: 0,    intensity: 0.0  },
    { dt_ms: 50,   intensity: 0.79 },
    { dt_ms: 100,  intensity: 0.63 },
    ...
    { dt_ms: 1000, intensity: 0.0  }
  ]
}
```

**Stop event:**
```bson
{ type: "stop", device: "steam-input/0" }
```

**Error event:**
```bson
{ type: "error", device: "steam-input/0", message: "device disconnected" }
```

### FF effect translation (in Rust)

| FF type | Translation |
|---|---|
| `FF_RUMBLE` | `intensity = (strong + weak) / 2 / 65535.0`. Two points: `(0, intensity)` and `(replay.length_ms, 0.0)` |
| `FF_PERIODIC` | Sample waveform (sine/square/triangle/sawtooth) at ~20ms intervals over `replay.length_ms`. Apply envelope: linear ramp from `attack_level` over `attack_ms`, sustain at peak, linear ramp to `fade_level` over `fade_ms`. Normalise magnitude to 0–1. |
| `FF_CONSTANT` | Constant `level / 32767.0` for `replay.length_ms` |
| `FF_RAMP` | Linear interpolation from `start_level` to `end_level` over `replay.length_ms` |

All intensity values are normalised to `[0.0, 1.0]` before output. Scale factor is NOT applied in the probe — Python applies it at send time.

### Build

Docker (`backend/Dockerfile`) is extended to install `rustup` with stable toolchain and `bpf-linker` (for `bpfel-unknown-none` target). Makefile builds `intiface-engine` and `haptics-probe`, both output to `backend/out/`. eBPF bytecode is embedded in the `haptics-probe` binary via `include_bytes!` — no separate `.bpf.o` to ship.

Requires: kernel with `CONFIG_BPF_TRACING` (present on SteamOS 3.x). Runtime: no libbpf dependency (Aya uses raw BPF syscalls). Loading requires `CAP_SYS_ADMIN` / `CAP_BPF` — the plugin runs as root via `_root` flag in `plugin.json`.

---

## Python backend changes

### New settings keys (`settings.json`)

```json
{
  "bridge_enabled": true,
  "bridge_device_map": {
    "steam-input/0": null
  },
  "bridge_intensity_scale": 1.0
}
```

`bridge_device_map` maps source device phys-ID → list of buttplug device IDs to target, or `null` to target all connected devices. Devices absent from the map also default to targeting all connected devices.

### `HapticsBridge` class

Single responsibility: manage the probe subprocess and translate its output into `ScalarCmd` calls on the existing buttplug client.

```python
class HapticsBridge:
    async def start(self, client, settings) -> None
        # spawn bin/haptics-probe
        # start _reader_loop task
    async def stop(self) -> None
        # terminate probe, cancel reader task
    async def update_scale(self, scale: float) -> None

    async def _reader_loop(self) -> None
        # read BSON frames from probe stdout
        # dispatch by type

    async def _on_haptic(self, device: str, points: list) -> None
        # look up device_map[device] → target device ids (or all)
        # schedule ScalarCmd sequence:
        #   for each point: asyncio.sleep(delta_ms/1000), send intensity * scale

    async def _on_stop(self, device: str) -> None
        # cancel pending sequence task for this device
        # send ScalarCmd(0) immediately
```

### New callables on `Plugin`

| Callable | Args | Returns |
|---|---|---|
| `set_bridge_enabled` | `enabled: bool` | `{success: bool}` |
| `list_evdev_devices` | — | `[{device: str, name: str, path: str}]` |
| `set_bridge_scale` | `scale: float` | `{success: bool}` |
| `update_settings` | extended with `bridge_*` fields | `{success: bool}` |

`list_evdev_devices` spawns `haptics-probe --list-devices`, reads JSON output, returns list.

### New event

| Event | Payload |
|---|---|
| `bridge_status_changed` | `enabled: bool, device: str \| None` |

### Lifecycle integration

`_main()` → after engine starts and buttplug client connects → if `bridge_enabled`, call `HapticsBridge.start()`.
`_unload()` → `HapticsBridge.stop()` before engine stop.

`bson` package added to `py_modules/` for BSON decoding.

---

## Frontend changes

### `BridgePanel` component

```
┌─ Haptics Bridge ──────────────────────────────┐
│  [Enable Bridge]  ● Active / ○ Inactive       │
│                                               │
│  Source Devices                               │
│  ┌─────────────────────────────────────────┐  │
│  │ steam-input/0  Steam Virtual Gamepad    │  │
│  │   → All toys                            │  │
│  │ usb-0000:00:14.0-2  DualSense           │  │
│  │   → No mapping                          │  │
│  └─────────────────────────────────────────┘  │
│                                               │
│  Intensity Scale  [────●────────]  0.8        │
└───────────────────────────────────────────────┘
```

Device-to-toy mapping display is read-only in Phase 2 ("→ All toys" / "→ No mapping"). Editing the mapping is deferred to Phase 3.

### New TypeScript callables

```ts
const setBridgeEnabled = callable<[boolean], {success: boolean}>('set_bridge_enabled')
const listEvdevDevices = callable<[], {device: string, name: string, path: string}[]>('list_evdev_devices')
const setBridgeScale   = callable<[number], {success: boolean}>('set_bridge_scale')
```

### New event listener

```ts
addEventListener<[enabled: boolean, device: string | null]>('bridge_status_changed', ...)
```

### State additions

```ts
bridgeEnabled: boolean
bridgeDevices: {device: string, name: string, path: string}[]
bridgeScale: number    // 0.0–1.0
```

---

## Testing

### Backend (`tests/backend/test_haptics.py`)

Uses a mock probe subprocess that writes pre-crafted BSON frames to a pipe (parallel to existing `mock_subprocess` fixture).

| Test | Covers |
|---|---|
| `test_rumble_scalar` | `FF_RUMBLE` event → correct `ScalarCmd` sent to mock intiface server |
| `test_periodic_sequence` | `FF_PERIODIC` with envelope → correct timed `ScalarCmd` sequence |
| `test_device_routing` | Two source devices, one mapped → only mapped toys receive commands |
| `test_scale` | `set_bridge_scale(0.5)` → intensities halved |
| `test_probe_error` | Probe emits error → `bridge_status_changed(false, ...)` emitted |
| `test_stop_cancels` | Stop event cancels in-flight sequence, sends ScalarCmd(0) |

### Rust unit tests (`backend/haptics-probe/haptics-probe/tests/`)

No kernel/eBPF required — pure translation logic:

| Test | Covers |
|---|---|
| `test_rumble_translation` | `ff_rumble_effect` → correct two-point sequence |
| `test_periodic_sine` | Sine wave samples match expected values |
| `test_periodic_square` | Square wave samples |
| `test_envelope_attack_fade` | Envelope shaping applied correctly |
| `test_throttle` | Points closer than 10ms are merged/dropped; stop events bypass throttle |
| `test_bson_framing` | Output is valid BSON, self-delimiting |

### Frontend (`tests/frontend/bridge.spec.ts`)

| Test | Covers |
|---|---|
| Bridge toggle | `set_bridge_enabled` called, UI reflects state |
| Status event | `bridge_status_changed` → indicator updates |
| Scale slider | `set_bridge_scale` called with correct value |

All existing test fixtures (`mock_subprocess`, `MockIntifaceServer`, `emit_recorder`) reused without modification.

---

## What this does not cover

- Per-device toy mapping UI (Phase 3)
- Time-varying `ScalarCmd` waveform playback on the frontend (Phase 3)
- `FF_SPRING`, `FF_FRICTION`, `FF_DAMPER`, `FF_INERTIA` condition effects (mapped to zero / ignored)
- Non-SteamOS Linux targets
- Windows / macOS
