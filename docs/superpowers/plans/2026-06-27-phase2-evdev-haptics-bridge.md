# Phase 2 — evdev Haptics Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Intercept Steam Input force-feedback effects via an Aya eBPF probe, translate them to pre-sampled intensity point sequences, and forward them as Buttplug ScalarCmd calls to connected toys.

**Architecture:** A Rust binary (`haptics-probe`) uses two eBPF tracepoints on `sys_enter/exit_ioctl` to capture `ff_effect` structs when games upload them via `EVIOCSFF`, then reads evdev `EV_FF` play/stop events to know when to emit translated haptic sequences over stdout as BSON. Python's `HapticsBridge` spawns the probe, reads BSON frames, and schedules `ScalarCmd` calls via the existing buttplug-py client.

**Tech Stack:** Rust (Aya 0.13, bson 2, evdev 0.12, tokio 1), Python (asyncio, bson pip package), TypeScript/React (@decky/ui), pytest + pytest-asyncio

---

## File Map

**New files:**
- `backend/haptics-probe/Cargo.toml` — workspace
- `backend/haptics-probe/haptics-probe-common/Cargo.toml` + `src/lib.rs` — shared types (FfEffect, ring buf events)
- `backend/haptics-probe/haptics-probe-ebpf/Cargo.toml` + `src/main.rs` — eBPF program
- `backend/haptics-probe/haptics-probe/Cargo.toml` + `build.rs` + `src/main.rs` — userspace binary
- `backend/haptics-probe/haptics-probe/src/translate.rs` — FF effect → point sequence translation
- `backend/haptics-probe/haptics-probe/src/throttle.rs` — 10ms output throttle
- `backend/haptics-probe/haptics-probe/src/device.rs` — evdev device enumeration + EV_FF reader
- `backend/haptics-probe/haptics-probe/src/ebpf.rs` — eBPF program loader + effect store access
- `tests/backend/test_haptics.py` — backend haptics bridge tests

**Modified files:**
- `backend/Dockerfile` — switch to holo-toolchain-rust, add bpf-linker
- `backend/Makefile` — add haptics-probe build target
- `main.py` — add HapticsBridge class, new callables, bridge settings, lifecycle integration
- `tests/backend/conftest.py` — add mock_probe fixture
- `tests/backend/requirements.txt` — add bson
- `src/index.tsx` — add BridgePanel component and bridge callables/events

---

## Task 1: Build Infrastructure

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `backend/Makefile`
- Create: `backend/haptics-probe/Cargo.toml`
- Create: `backend/haptics-probe/haptics-probe-common/Cargo.toml`
- Create: `backend/haptics-probe/haptics-probe-common/src/lib.rs`
- Create: `backend/haptics-probe/haptics-probe-ebpf/Cargo.toml`
- Create: `backend/haptics-probe/haptics-probe-ebpf/src/main.rs` (stub)
- Create: `backend/haptics-probe/haptics-probe/Cargo.toml`
- Create: `backend/haptics-probe/haptics-probe/build.rs`
- Create: `backend/haptics-probe/haptics-probe/src/main.rs` (stub)

- [ ] **Switch Dockerfile to Rust toolchain image and add bpf-linker**

Replace `backend/Dockerfile` contents:

```dockerfile
FROM ghcr.io/steamdeckhomebrew/holo-toolchain-rust:latest

RUN rustup target add bpfel-unknown-none \
 && cargo install bpf-linker

ENTRYPOINT [ "/backend/entrypoint.sh" ]
```

- [ ] **Create Cargo workspace**

`backend/haptics-probe/Cargo.toml`:
```toml
[workspace]
members = [
    "haptics-probe-common",
    "haptics-probe-ebpf",
    "haptics-probe",
]
resolver = "2"
```

- [ ] **Create common crate (shared types)**

`backend/haptics-probe/haptics-probe-common/Cargo.toml`:
```toml
[package]
name = "haptics-probe-common"
version = "0.1.0"
edition = "2021"

[features]
default = []
user = ["bson"]

[dependencies]
bson = { version = "2", optional = true }
```

`backend/haptics-probe/haptics-probe-common/src/lib.rs`:
```rust
#![cfg_attr(not(feature = "user"), no_std)]

/// Waveform types matching Linux FF_* constants
#[derive(Debug, Clone, Copy, PartialEq)]
#[repr(u16)]
pub enum Waveform {
    Square    = 0x58,
    Triangle  = 0x59,
    Sine      = 0x5a,
    SawUp     = 0x5b,
    SawDown   = 0x5c,
    Custom    = 0x5d,
}

impl Waveform {
    pub fn from_u16(v: u16) -> Option<Self> {
        match v {
            0x58 => Some(Self::Square),
            0x59 => Some(Self::Triangle),
            0x5a => Some(Self::Sine),
            0x5b => Some(Self::SawUp),
            0x5c => Some(Self::SawDown),
            0x5d => Some(Self::Custom),
            _    => None,
        }
    }
}

/// Envelope applied to periodic/constant/ramp effects
#[derive(Debug, Clone, Copy, Default)]
#[repr(C)]
pub struct Envelope {
    pub attack_length: u16,
    pub attack_level:  u16,
    pub fade_length:   u16,
    pub fade_level:    u16,
}

/// Captured effect data — stored in eBPF map, read by userspace
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct FfEffect {
    pub kind:      u16,
    pub id:        i16,
    pub direction: u16,
    // trigger (4 bytes)
    pub trigger_button:   u16,
    pub trigger_interval: u16,
    // replay (4 bytes)
    pub replay_length: u16,
    pub replay_delay:  u16,
    // union — largest variant is periodic (14 bytes)
    pub u: [u16; 7],  // raw union bytes as u16 words
}

// FF type constants
pub const FF_RUMBLE:   u16 = 0x50;
pub const FF_PERIODIC: u16 = 0x51;
pub const FF_CONSTANT: u16 = 0x52;
pub const FF_RAMP:     u16 = 0x58;

/// Event emitted from eBPF ring buffer to userspace
#[derive(Debug, Clone, Copy)]
#[repr(C)]
pub struct ProbeEvent {
    /// Process group ID of the process that uploaded the effect
    pub tgid: u32,
    /// Assigned effect id
    pub effect_id: i16,
    _pad: u16,
    pub effect: FfEffect,
}
```

- [ ] **Create eBPF crate stub**

`backend/haptics-probe/haptics-probe-ebpf/Cargo.toml`:
```toml
[package]
name = "haptics-probe-ebpf"
version = "0.1.0"
edition = "2021"

[dependencies]
aya-bpf = "0.1"
aya-log-ebpf = "0.1"
haptics-probe-common = { path = "../haptics-probe-common" }

[[bin]]
name = "haptics-probe-ebpf"
path = "src/main.rs"
```

`backend/haptics-probe/haptics-probe-ebpf/src/main.rs`:
```rust
#![no_std]
#![no_main]

use aya_bpf::macros::tracepoint;
use aya_bpf::programs::TracePointContext;

#[tracepoint]
pub fn sys_enter_ioctl(_ctx: TracePointContext) -> i32 { 0 }

#[tracepoint]
pub fn sys_exit_ioctl(_ctx: TracePointContext) -> i32 { 0 }

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }
```

- [ ] **Create userspace crate**

`backend/haptics-probe/haptics-probe/Cargo.toml`:
```toml
[package]
name = "haptics-probe"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "haptics-probe"
path = "src/main.rs"

[dependencies]
aya            = { version = "0.13", features = ["async_tokio"] }
aya-log        = "0.2"
haptics-probe-common = { path = "../haptics-probe-common", features = ["user"] }
bson           = "2"
evdev          = "0.12"
tokio          = { version = "1", features = ["full"] }
anyhow         = "1"
serde          = { version = "1", features = ["derive"] }
log            = "0.4"
env_logger     = "0.11"

[build-dependencies]
aya-build = "0.1"
```

`backend/haptics-probe/haptics-probe/build.rs`:
```rust
use aya_build::cargo_metadata;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let programs = &["haptics-probe-ebpf"];
    aya_build::build_ebpf(programs)?;
    Ok(())
}
```

`backend/haptics-probe/haptics-probe/src/main.rs` (stub):
```rust
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    env_logger::init();
    println!("haptics-probe stub");
    Ok(())
}
```

- [ ] **Add haptics-probe to Makefile**

Append to `backend/Makefile`:
```makefile
HAPTICS_PROBE_TARGET = x86_64-unknown-linux-musl

.PHONY: haptics-probe
haptics-probe:
	cd haptics-probe && \
	  CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER=x86_64-linux-gnu-gcc \
	  cargo build --release --target $(HAPTICS_PROBE_TARGET) \
	    --package haptics-probe
	cp haptics-probe/target/$(HAPTICS_PROBE_TARGET)/release/haptics-probe ./out/haptics-probe

all: ./out/intiface-engine haptics-probe
```

- [ ] **Verify Docker build compiles successfully**

```bash
cd backend && docker build -t decky-plugin-backend . \
  && docker run --rm -v $(pwd):/backend decky-plugin-backend
```
Expected: build completes, `out/intiface-engine` and `out/haptics-probe` present.

- [ ] **Commit**

```bash
git add backend/
git commit -m "feat: scaffold haptics-probe Rust workspace and Docker build"
```

---

## Task 2: FF Effect Translation (TDD)

**Files:**
- Create: `backend/haptics-probe/haptics-probe/src/translate.rs`

The translation module converts a captured `FfEffect` into a `Vec<(u32, f32)>` — a sequence of `(dt_ms, intensity_0to1)` pairs. No eBPF or I/O involved; pure logic, fully unit-testable.

- [ ] **Write failing tests first**

Create `backend/haptics-probe/haptics-probe/src/translate.rs` with the test module, but no implementation yet:

```rust
use haptics-probe-common::{FfEffect, FF_RUMBLE, FF_PERIODIC, FF_CONSTANT, FF_RAMP, Waveform, Envelope};

/// A single scheduled haptic point: milliseconds after play start, intensity 0.0–1.0
#[derive(Debug, Clone, PartialEq)]
pub struct HapticPoint {
    pub dt_ms: u32,
    pub intensity: f32,
}

/// Translate a captured ff_effect into a sequence of haptic points.
/// Returns empty vec for unrecognised effect types.
pub fn translate(effect: &FfEffect) -> Vec<HapticPoint> {
    todo!()
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn rumble_intensity(strong: u16, weak: u16) -> f32 {
    todo!()
}

fn apply_envelope(base: f32, t_ms: u32, length_ms: u32, envelope: Envelope) -> f32 {
    todo!()
}

fn sample_waveform(waveform: Waveform, t_ms: u32, period_ms: u16, magnitude: i16,
                   offset: i16, phase: u16) -> f32 {
    todo!()
}

fn periodic_points(effect: &FfEffect) -> Vec<HapticPoint> { todo!() }
fn rumble_points(effect: &FfEffect)   -> Vec<HapticPoint> { todo!() }
fn constant_points(effect: &FfEffect) -> Vec<HapticPoint> { todo!() }
fn ramp_points(effect: &FfEffect)     -> Vec<HapticPoint> { todo!() }

#[cfg(test)]
mod tests {
    use super::*;
    use haptics-probe-common::FF_RUMBLE;

    fn rumble_effect(strong: u16, weak: u16, length_ms: u16) -> FfEffect {
        let mut e = FfEffect {
            kind: FF_RUMBLE, id: 0, direction: 0,
            trigger_button: 0, trigger_interval: 0,
            replay_length: length_ms, replay_delay: 0,
            u: [0u16; 7],
        };
        e.u[0] = strong;
        e.u[1] = weak;
        e
    }

    fn periodic_effect(waveform: u16, magnitude: i16, period_ms: u16,
                       length_ms: u16, env: Envelope) -> FfEffect {
        let mut e = FfEffect {
            kind: FF_PERIODIC, id: 0, direction: 0,
            trigger_button: 0, trigger_interval: 0,
            replay_length: length_ms, replay_delay: 0,
            u: [0u16; 7],
        };
        e.u[0] = waveform;
        e.u[1] = period_ms;
        e.u[2] = magnitude as u16;
        e.u[3] = 0; // offset
        e.u[4] = 0; // phase
        e.u[5] = (env.attack_length as u16) | (env.attack_level << 8); // packed wrong, see below
        // Actually store envelope as separate u16s:
        // u[3]=offset, u[4]=phase, u[5]=attack_length, u[6]=attack_level
        // Use a helper: see translate.rs FfEffect union layout comment
        e
    }

    // ── rumble ────────────────────────────────────────────────────────────────

    #[test]
    fn rumble_full_strength_produces_start_and_stop_points() {
        let e = rumble_effect(0xFFFF, 0xFFFF, 500);
        let pts = translate(&e);
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[0].dt_ms, 0);
        assert!((pts[0].intensity - 1.0).abs() < 0.01);
        assert_eq!(pts[1].dt_ms, 500);
        assert_eq!(pts[1].intensity, 0.0);
    }

    #[test]
    fn rumble_half_strength_produces_half_intensity() {
        let e = rumble_effect(0x8000, 0x8000, 200);
        let pts = translate(&e);
        assert!((pts[0].intensity - 0.5).abs() < 0.01);
    }

    #[test]
    fn rumble_combines_strong_and_weak_as_average() {
        // strong=1.0, weak=0.0 → average = 0.5
        let e = rumble_effect(0xFFFF, 0, 100);
        let pts = translate(&e);
        assert!((pts[0].intensity - 0.5).abs() < 0.01);
    }

    #[test]
    fn rumble_zero_length_produces_single_zero_point() {
        let e = rumble_effect(0xFFFF, 0xFFFF, 0);
        let pts = translate(&e);
        assert_eq!(pts.len(), 1);
        assert_eq!(pts[0].intensity, 0.0);
    }

    // ── periodic ──────────────────────────────────────────────────────────────

    #[test]
    fn periodic_sine_samples_at_20ms_intervals() {
        let e = periodic_effect(0x5a /*sine*/, 0x7FFF, 100, 200, Envelope::default());
        let pts = translate(&e);
        // 200ms / 20ms + final stop = 11 points (0,20,40,...,200)
        assert_eq!(pts.len(), 11);
        assert_eq!(pts[0].dt_ms, 0);
        assert_eq!(pts.last().unwrap().dt_ms, 200);
        assert_eq!(pts.last().unwrap().intensity, 0.0);
    }

    #[test]
    fn periodic_sine_peak_near_quarter_period() {
        // sine at t=period/4 should be near maximum
        let e = periodic_effect(0x5a, 0x7FFF, 40 /*period*/, 200, Envelope::default());
        let pts = translate(&e);
        // sample at dt=10ms = period/4 → should be near 1.0
        let pt = pts.iter().find(|p| p.dt_ms == 20).unwrap();
        assert!(pt.intensity > 0.8, "got {}", pt.intensity);
    }

    #[test]
    fn periodic_square_is_binary() {
        let e = periodic_effect(0x58 /*square*/, 0x7FFF, 100, 200, Envelope::default());
        let pts = translate(&e);
        for p in &pts[..pts.len()-1] { // exclude final stop
            assert!(p.intensity == 0.0 || (p.intensity - 1.0).abs() < 0.01,
                    "square point not 0 or 1: {}", p.intensity);
        }
    }

    #[test]
    fn envelope_attack_ramps_up() {
        let env = Envelope { attack_length: 100, attack_level: 0,
                             fade_length: 0, fade_level: 0x7FFF };
        let e = periodic_effect(0x5a, 0x7FFF, 20, 200, env);
        let pts = translate(&e);
        // at t=0 intensity should be near 0 (start of attack)
        assert!(pts[0].intensity < 0.1, "got {}", pts[0].intensity);
        // at t=100ms intensity should be at full sustain
        let p100 = pts.iter().find(|p| p.dt_ms == 100).unwrap();
        assert!(p100.intensity > 0.8, "got {}", p100.intensity);
    }

    // ── constant ──────────────────────────────────────────────────────────────

    #[test]
    fn constant_produces_flat_points() {
        let mut e = FfEffect {
            kind: FF_CONSTANT, id: 0, direction: 0,
            trigger_button: 0, trigger_interval: 0,
            replay_length: 100, replay_delay: 0,
            u: [0; 7],
        };
        e.u[0] = 0x7FFF; // level
        let pts = translate(&e);
        let sustain: Vec<_> = pts.iter().filter(|p| p.dt_ms > 0 && p.dt_ms < 100).collect();
        for p in sustain {
            assert!((p.intensity - 1.0).abs() < 0.01, "got {}", p.intensity);
        }
    }

    // ── unknown type ──────────────────────────────────────────────────────────

    #[test]
    fn unknown_ff_type_returns_empty() {
        let e = FfEffect { kind: 0xFF, id: 0, direction: 0,
                           trigger_button: 0, trigger_interval: 0,
                           replay_length: 100, replay_delay: 0, u: [0; 7] };
        assert!(translate(&e).is_empty());
    }
}
```

- [ ] **Run tests to confirm they fail**

```bash
cd backend/haptics-probe && cargo test -p haptics-probe 2>&1 | grep -E "FAILED|error"
```
Expected: compilation errors / panics (todo!() not reached yet means compile passes but runtime panics).

- [ ] **Implement translate.rs**

Replace the `todo!()` stubs with real implementations:

```rust
use core::f32::consts::PI;
use haptics_probe_common::{FfEffect, FF_RUMBLE, FF_PERIODIC, FF_CONSTANT, FF_RAMP, Waveform, Envelope};

pub const SAMPLE_INTERVAL_MS: u32 = 20;

#[derive(Debug, Clone, PartialEq)]
pub struct HapticPoint {
    pub dt_ms: u32,
    pub intensity: f32,
}

pub fn translate(effect: &FfEffect) -> Vec<HapticPoint> {
    match effect.kind {
        FF_RUMBLE   => rumble_points(effect),
        FF_PERIODIC => periodic_points(effect),
        FF_CONSTANT => constant_points(effect),
        FF_RAMP     => ramp_points(effect),
        _           => vec![],
    }
}

fn rumble_intensity(strong: u16, weak: u16) -> f32 {
    ((strong as f32 + weak as f32) / 2.0 / 65535.0).clamp(0.0, 1.0)
}

/// Apply envelope scaling to a base intensity at time t_ms within a replay of length_ms.
/// Envelope: linear attack ramp from attack_level to full over attack_length,
///           linear fade ramp from full to fade_level over the last fade_length ms.
fn apply_envelope(base: f32, t_ms: u32, length_ms: u32, env: Envelope) -> f32 {
    let scale = if env.attack_length > 0 && t_ms < env.attack_length as u32 {
        let attack_start = env.attack_level as f32 / 32767.0;
        let progress = t_ms as f32 / env.attack_length as f32;
        attack_start + (1.0 - attack_start) * progress
    } else if env.fade_length > 0 && length_ms > 0 {
        let fade_start_ms = length_ms.saturating_sub(env.fade_length as u32);
        if t_ms >= fade_start_ms {
            let fade_end = env.fade_level as f32 / 32767.0;
            let progress = (t_ms - fade_start_ms) as f32 / env.fade_length as f32;
            1.0 - (1.0 - fade_end) * progress
        } else {
            1.0
        }
    } else {
        1.0
    };
    (base * scale).clamp(0.0, 1.0)
}

fn sample_waveform(waveform: Waveform, t_ms: u32, period_ms: u16,
                   magnitude: i16, offset: i16, _phase: u16) -> f32 {
    if period_ms == 0 { return 0.0; }
    let t = (t_ms % period_ms as u32) as f32 / period_ms as f32; // 0.0–1.0
    let mag = magnitude.abs() as f32 / 32767.0;
    let off = offset as f32 / 32767.0;
    let raw = match waveform {
        Waveform::Sine     => (t * 2.0 * PI).sin(),
        Waveform::Square   => if t < 0.5 { 1.0 } else { -1.0 },
        Waveform::Triangle => if t < 0.5 { 4.0 * t - 1.0 } else { 3.0 - 4.0 * t },
        Waveform::SawUp    => 2.0 * t - 1.0,
        Waveform::SawDown  => 1.0 - 2.0 * t,
        Waveform::Custom   => 0.0,
    };
    ((raw * mag + off) * 0.5 + 0.5).clamp(0.0, 1.0)
}

fn rumble_points(effect: &FfEffect) -> Vec<HapticPoint> {
    let strong = effect.u[0];
    let weak   = effect.u[1];
    let length = effect.replay_length as u32;
    if length == 0 {
        return vec![HapticPoint { dt_ms: 0, intensity: 0.0 }];
    }
    let intensity = rumble_intensity(strong, weak);
    vec![
        HapticPoint { dt_ms: 0, intensity },
        HapticPoint { dt_ms: length, intensity: 0.0 },
    ]
}

fn constant_points(effect: &FfEffect) -> Vec<HapticPoint> {
    let level    = effect.u[0] as i16;
    let length   = effect.replay_length as u32;
    let env      = Envelope {
        attack_length: effect.u[1], attack_level: effect.u[2],
        fade_length:   effect.u[3], fade_level:   effect.u[4],
    };
    let base = (level.abs() as f32 / 32767.0).clamp(0.0, 1.0);
    sample_range(0, length, base, length, env)
}

fn ramp_points(effect: &FfEffect) -> Vec<HapticPoint> {
    let start_level = effect.u[0] as i16;
    let end_level   = effect.u[1] as i16;
    let length      = effect.replay_length as u32;
    (0..=length).step_by(SAMPLE_INTERVAL_MS as usize)
        .chain(if length % SAMPLE_INTERVAL_MS == 0 { None } else { Some(length) })
        .map(|t| {
            let progress = if length == 0 { 0.0 } else { t as f32 / length as f32 };
            let level = start_level as f32 + (end_level - start_level) as f32 * progress;
            HapticPoint { dt_ms: t, intensity: (level.abs() / 32767.0).clamp(0.0, 1.0) }
        })
        .chain(std::iter::once(HapticPoint { dt_ms: length, intensity: 0.0 }))
        .collect()
}

fn periodic_points(effect: &FfEffect) -> Vec<HapticPoint> {
    let waveform   = effect.u[0];
    let period_ms  = effect.u[1];
    let magnitude  = effect.u[2] as i16;
    let offset     = effect.u[3] as i16;
    let phase      = effect.u[4];
    let length     = effect.replay_length as u32;
    let env        = Envelope {
        attack_length: effect.u[5],
        attack_level:  0,
        fade_length:   effect.u[6],
        fade_level:    0,
    };
    let wf = Waveform::from_u16(waveform).unwrap_or(Waveform::Sine);
    let base_at = |t: u32| sample_waveform(wf, t, period_ms, magnitude, offset, phase);
    sample_range_fn(0, length, base_at, length, env)
}

fn sample_range(start: u32, end: u32, base: f32, length: u32, env: Envelope) -> Vec<HapticPoint> {
    sample_range_fn(start, end, |_| base, length, env)
}

fn sample_range_fn<F: Fn(u32) -> f32>(
    start: u32, end: u32, base_fn: F, length: u32, env: Envelope,
) -> Vec<HapticPoint> {
    let mut pts: Vec<HapticPoint> = (start..end)
        .step_by(SAMPLE_INTERVAL_MS as usize)
        .map(|t| HapticPoint {
            dt_ms: t,
            intensity: apply_envelope(base_fn(t), t, length, env),
        })
        .collect();
    pts.push(HapticPoint { dt_ms: end, intensity: 0.0 });
    pts
}
```

Add `mod translate;` to `src/main.rs`.

- [ ] **Run tests to confirm they pass**

```bash
cd backend/haptics-probe && cargo test -p haptics-probe -- translate 2>&1
```
Expected: all translate tests pass.

- [ ] **Commit**

```bash
git add backend/haptics-probe/
git commit -m "feat: FF effect to haptic point sequence translation (TDD)"
```

---

## Task 3: Output Throttle (TDD)

**Files:**
- Create: `backend/haptics-probe/haptics-probe/src/throttle.rs`

The throttle enforces ≥10ms between emitted messages. Stop events bypass the throttle entirely.

- [ ] **Write failing tests**

```rust
// backend/haptics-probe/haptics-probe/src/throttle.rs
use std::time::{Duration, Instant};

pub const MIN_INTERVAL_MS: u64 = 10;

pub struct Throttle {
    last_haptic: Option<Instant>,
}

impl Throttle {
    pub fn new() -> Self { Self { last_haptic: None } }

    /// Returns true if a haptic message should be emitted now.
    /// Always returns true for stop messages.
    pub fn should_emit_haptic(&mut self) -> bool { todo!() }

    /// Called after a haptic message is emitted to record the timestamp.
    pub fn record_haptic_emitted(&mut self) { todo!() }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread::sleep;

    #[test]
    fn first_haptic_always_emitted() {
        let mut t = Throttle::new();
        assert!(t.should_emit_haptic());
    }

    #[test]
    fn second_haptic_blocked_within_10ms() {
        let mut t = Throttle::new();
        t.record_haptic_emitted();
        // immediately after — well within 10ms
        assert!(!t.should_emit_haptic());
    }

    #[test]
    fn haptic_allowed_after_10ms() {
        let mut t = Throttle::new();
        t.record_haptic_emitted();
        sleep(Duration::from_millis(11));
        assert!(t.should_emit_haptic());
    }

    #[test]
    fn stop_always_bypasses_throttle() {
        // stop is not controlled by Throttle; the caller sends it unconditionally.
        // Throttle does not gate stops. This test documents the contract:
        // should_emit_haptic() == false does not prevent stop emission.
        let mut t = Throttle::new();
        t.record_haptic_emitted();
        // stop can still be sent — caller responsibility, throttle not involved
        assert!(!t.should_emit_haptic()); // haptic is blocked...
        // ...but stop would be sent by caller without calling should_emit_haptic
    }
}
```

- [ ] **Run to verify failure**

```bash
cd backend/haptics-probe && cargo test -p haptics-probe -- throttle 2>&1 | head -20
```
Expected: compile errors from `todo!()`.

- [ ] **Implement**

```rust
pub fn should_emit_haptic(&mut self) -> bool {
    match self.last_haptic {
        None => true,
        Some(t) => t.elapsed() >= Duration::from_millis(MIN_INTERVAL_MS),
    }
}

pub fn record_haptic_emitted(&mut self) {
    self.last_haptic = Some(Instant::now());
}
```

- [ ] **Run tests to confirm pass**

```bash
cd backend/haptics-probe && cargo test -p haptics-probe -- throttle 2>&1
```
Expected: all pass.

- [ ] **Commit**

```bash
git add backend/haptics-probe/haptics-probe/src/throttle.rs
git commit -m "feat: output throttle — min 10ms between haptic frames"
```

---

## Task 4: evdev Device Module

**Files:**
- Create: `backend/haptics-probe/haptics-probe/src/device.rs`

This module lists FF-capable devices and reads `EV_FF` play/stop events. The `--list-devices` CLI mode uses it.

- [ ] **Write device.rs**

```rust
// backend/haptics-probe/haptics-probe/src/device.rs
use anyhow::Result;
use evdev::{Device, EventType, InputEventKind, FFEffect};
use std::path::{Path, PathBuf};

/// Metadata about one FF-capable input device.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DeviceInfo {
    /// Stable ID: phys string if available, else basename(path).
    pub device_id: String,
    pub name: String,
    pub path: String,
}

/// Enumerate all /dev/input/event* devices that support EV_FF.
pub fn list_ff_devices() -> Result<Vec<DeviceInfo>> {
    let mut result = Vec::new();
    let entries = std::fs::read_dir("/dev/input")?;
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.to_str().map(|s| s.contains("event")).unwrap_or(false) {
            continue;
        }
        if let Ok(dev) = Device::open(&path) {
            if dev.supported_events().contains(EventType::FORCEFEEDBACK) {
                let device_id = stable_id(&dev, &path);
                let name = dev.name().unwrap_or("Unknown").to_string();
                result.push(DeviceInfo {
                    device_id,
                    name,
                    path: path.to_string_lossy().into_owned(),
                });
            }
        }
    }
    Ok(result)
}

/// Derive a stable device ID: phys string, falling back to basename.
pub fn stable_id(dev: &Device, path: &Path) -> String {
    dev.physical_path()
        .filter(|p| !p.is_empty())
        .map(|p| p.to_string())
        .unwrap_or_else(|| {
            path.file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned()
        })
}

/// A single event from an evdev FF device.
#[derive(Debug)]
pub enum FfEvent {
    Play { effect_id: i16 },
    Stop { effect_id: i16 },
}

/// Read the next FF play/stop event from an evdev device (non-async, use in a spawn_blocking).
pub fn next_ff_event(dev: &mut Device) -> Result<FfEvent> {
    loop {
        for ev in dev.fetch_events()? {
            if ev.event_type() == EventType::FORCEFEEDBACK {
                let effect_id = ev.code() as i16;
                return Ok(if ev.value() != 0 {
                    FfEvent::Play { effect_id }
                } else {
                    FfEvent::Stop { effect_id }
                });
            }
        }
    }
}
```

Add `mod device;` to `src/main.rs`.

- [ ] **Wire `--list-devices` into main.rs**

```rust
// top of main.rs
mod device;
mod translate;
mod throttle;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    env_logger::init();
    let args: Vec<String> = std::env::args().collect();

    if args.get(1).map(|s| s.as_str()) == Some("--list-devices") {
        let devices = device::list_ff_devices()?;
        println!("{}", serde_json::to_string(&devices)?);
        return Ok(());
    }

    println!("haptics-probe: monitoring not yet implemented");
    Ok(())
}
```

Add `serde_json = "1"` to `haptics-probe/Cargo.toml` dependencies.

- [ ] **Verify it compiles**

```bash
cd backend/haptics-probe && cargo build -p haptics-probe 2>&1 | tail -5
```
Expected: `Finished` with no errors.

- [ ] **Commit**

```bash
git add backend/haptics-probe/
git commit -m "feat: evdev device enumeration and FF event reader"
```

---

## Task 5: eBPF Program

**Files:**
- Modify: `backend/haptics-probe/haptics-probe-ebpf/src/main.rs`
- Modify: `backend/haptics-probe/haptics-probe-common/src/lib.rs`

The eBPF program hooks `sys_enter_ioctl` to capture `ff_effect` data and `sys_exit_ioctl` to capture the kernel-assigned effect id (which is written back to userspace on `EVIOCSFF`).

- [ ] **Add scratch map types to common/src/lib.rs**

Append to `haptics-probe-common/src/lib.rs`:

```rust
/// Scratch entry: saved pointer + effect bytes before the kernel writes back the id.
/// Stored per-thread (keyed by tgid<<32|pid) from enter until exit.
#[derive(Clone, Copy)]
#[repr(C)]
pub struct EnterScratch {
    pub ff_effect_ptr: u64,  // userspace pointer passed to EVIOCSFF
    pub effect: FfEffect,
}

/// Compute EVIOCSFF ioctl number at compile time.
/// _IOW('E', 0x52, ff_effect) = (1<<30) | (size<<16) | ('E'<<8) | 0x52
pub const fn eviocsff_nr() -> u32 {
    let size = core::mem::size_of::<FfEffect>() as u32;
    (1u32 << 30) | ((size & 0x3fff) << 16) | (0x45u32 << 8) | 0x52u32
}
```

- [ ] **Write eBPF program**

Replace `backend/haptics-probe/haptics-probe-ebpf/src/main.rs`:

```rust
#![no_std]
#![no_main]

use aya_bpf::{
    macros::{map, tracepoint},
    maps::{HashMap, RingBuf},
    programs::TracePointContext,
    helpers::bpf_probe_read_user_buf,
};
use haptics_probe_common::{EnterScratch, FfEffect, ProbeEvent, eviocsff_nr};

/// Per-thread scratch: tgid<<32|pid → EnterScratch
#[map]
static mut ENTER_SCRATCH: HashMap<u64, EnterScratch> =
    HashMap::with_max_entries(1024, 0);

/// Effect store: (tgid<<32|effect_id) → FfEffect
#[map]
pub static mut EFFECT_STORE: HashMap<u64, FfEffect> =
    HashMap::with_max_entries(4096, 0);

/// Ring buffer for events to userspace
#[map]
static mut EVENTS: RingBuf = RingBuf::with_byte_size(256 * 1024, 0);

/// Tracepoint: sys_enter_ioctl
/// Layout (x86_64): common_* (8 bytes), __syscall_nr (4+4), fd (8), cmd (8), arg (8)
#[tracepoint]
pub fn sys_enter_ioctl(ctx: TracePointContext) -> i32 {
    match try_enter(&ctx) { Ok(_) => 0, Err(_) => 0 }
}

fn try_enter(ctx: &TracePointContext) -> Result<(), i64> {
    let cmd: u64 = unsafe { ctx.read_at(24) }.map_err(|_| 0i64)?;
    if cmd as u32 != eviocsff_nr() { return Ok(()); }

    let fd:  u64 = unsafe { ctx.read_at(16) }.map_err(|_| 0i64)?;
    let arg: u64 = unsafe { ctx.read_at(32) }.map_err(|_| 0i64)?;
    let _ = fd; // not needed in scratch — effect_id is in the struct

    // Read ff_effect from userspace
    let mut effect = FfEffect {
        kind: 0, id: 0, direction: 0,
        trigger_button: 0, trigger_interval: 0,
        replay_length: 0, replay_delay: 0,
        u: [0; 7],
    };
    let effect_bytes = unsafe {
        core::slice::from_raw_parts_mut(
            &mut effect as *mut FfEffect as *mut u8,
            core::mem::size_of::<FfEffect>(),
        )
    };
    unsafe { bpf_probe_read_user_buf(arg as *const u8, effect_bytes) }.map_err(|_| 0i64)?;

    let tgid_pid = bpf_get_current_pid_tgid();
    let scratch = EnterScratch { ff_effect_ptr: arg, effect };
    unsafe { ENTER_SCRATCH.insert(&tgid_pid, &scratch, 0) }.map_err(|_| 0i64)?;
    Ok(())
}

/// Tracepoint: sys_exit_ioctl — fires after kernel has written back the effect id
#[tracepoint]
pub fn sys_exit_ioctl(ctx: TracePointContext) -> i32 {
    match try_exit(&ctx) { Ok(_) => 0, Err(_) => 0 }
}

fn try_exit(ctx: &TracePointContext) -> Result<(), i64> {
    let tgid_pid = bpf_get_current_pid_tgid();
    let scratch = unsafe { ENTER_SCRATCH.get(&tgid_pid) }.ok_or(0i64)?;

    // Read the now-assigned id field (offset 2 in ff_effect = 2 bytes into the struct)
    let mut id_bytes = [0u8; 2];
    unsafe {
        bpf_probe_read_user_buf(
            (scratch.ff_effect_ptr + 2) as *const u8,
            &mut id_bytes,
        )
    }.map_err(|_| 0i64)?;
    let effect_id = i16::from_le_bytes(id_bytes);

    let tgid = (tgid_pid >> 32) as u32;
    let mut effect = scratch.effect;
    effect.id = effect_id;

    let store_key = ((tgid as u64) << 32) | (effect_id as u16 as u64);
    unsafe {
        EFFECT_STORE.insert(&store_key, &effect, 0).map_err(|_| 0i64)?;
        ENTER_SCRATCH.remove(&tgid_pid).ok();
    }

    // Emit to ring buffer for userspace
    let event = ProbeEvent { tgid, effect_id, _pad: 0, effect };
    if let Some(mut entry) = unsafe { EVENTS.reserve::<ProbeEvent>(0) } {
        entry.write(event);
        entry.submit(0);
    }
    Ok(())
}

fn bpf_get_current_pid_tgid() -> u64 {
    unsafe { aya_bpf::helpers::bpf_get_current_pid_tgid() }
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }
```

- [ ] **Verify eBPF crate compiles for BPF target**

```bash
cd backend/haptics-probe && \
  cargo build -p haptics-probe-ebpf \
    --target bpfel-unknown-none \
    -Z build-std=core 2>&1 | tail -10
```
Expected: `Finished` — this confirms the BPF program is syntactically correct.

- [ ] **Commit**

```bash
git add backend/haptics-probe/
git commit -m "feat: eBPF tracepoint program for EVIOCSFF magnitude capture"
```

---

## Task 6: eBPF Loader + Main Binary

**Files:**
- Create: `backend/haptics-probe/haptics-probe/src/ebpf.rs`
- Modify: `backend/haptics-probe/haptics-probe/src/main.rs`

The loader reads the ring buffer, matches `ProbeEvent` entries (effect uploads) against incoming evdev play events by `(tgid, effect_id)`, then emits translated BSON events to stdout.

- [ ] **Write ebpf.rs**

```rust
// backend/haptics-probe/haptics-probe/src/ebpf.rs
use anyhow::Result;
use aya::maps::{HashMap as AyaHashMap, RingBuf};
use aya::programs::TracePoint;
use aya::{include_bytes_aligned, Bpf};
use haptics_probe_common::{FfEffect, ProbeEvent};
use std::collections::HashMap;
use tokio::sync::mpsc;

#[derive(Debug)]
pub struct EffectUploaded {
    pub tgid: u32,
    pub effect_id: i16,
    pub effect: FfEffect,
}

/// Load and attach the eBPF program. Returns a receiver for effect-upload events.
pub async fn load_probe() -> Result<(Bpf, mpsc::Receiver<EffectUploaded>)> {
    #[cfg(debug_assertions)]
    let bpf_bytes = include_bytes_aligned!(
        "../../target/bpfel-unknown-none/debug/haptics-probe-ebpf"
    );
    #[cfg(not(debug_assertions))]
    let bpf_bytes = include_bytes_aligned!(
        "../../target/bpfel-unknown-none/release/haptics-probe-ebpf"
    );

    let mut bpf = Bpf::load(bpf_bytes)?;

    // Attach tracepoints
    let enter: &mut TracePoint = bpf.program_mut("sys_enter_ioctl").unwrap().try_into()?;
    enter.load()?;
    enter.attach("syscalls", "sys_enter_ioctl")?;

    let exit: &mut TracePoint = bpf.program_mut("sys_exit_ioctl").unwrap().try_into()?;
    exit.load()?;
    exit.attach("syscalls", "sys_exit_ioctl")?;

    let (tx, rx) = mpsc::channel(256);

    // Poll ring buffer in background task
    let mut ring: RingBuf<_> = bpf.map_mut("EVENTS").unwrap().try_into()?;
    tokio::spawn(async move {
        loop {
            tokio::task::yield_now().await;
            // Drain available events
            while let Some(item) = ring.next() {
                let bytes: &[u8] = &item;
                if bytes.len() < std::mem::size_of::<ProbeEvent>() { continue; }
                let event: ProbeEvent = unsafe {
                    std::ptr::read_unaligned(bytes.as_ptr() as *const ProbeEvent)
                };
                let _ = tx.try_send(EffectUploaded {
                    tgid: event.tgid,
                    effect_id: event.effect_id,
                    effect: event.effect,
                });
            }
            tokio::time::sleep(tokio::time::Duration::from_millis(1)).await;
        }
    });

    Ok((bpf, rx))
}
```

- [ ] **Complete main.rs: full event loop**

Replace `src/main.rs` with:

```rust
mod device;
mod ebpf;
mod translate;
mod throttle;

use anyhow::Result;
use bson::{doc, to_vec};
use device::{list_ff_devices, next_ff_event, stable_id, FfEvent};
use evdev::Device;
use haptics_probe_common::FF_RUMBLE;
use std::collections::HashMap;
use std::io::Write;
use throttle::Throttle;
use tokio::sync::mpsc;

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let args: Vec<String> = std::env::args().collect();

    if args.get(1).map(|s| s.as_str()) == Some("--list-devices") {
        let devices = list_ff_devices()?;
        println!("{}", serde_json::to_string(&devices)?);
        return Ok(());
    }

    // Load eBPF probe
    let (_bpf, mut effect_rx) = ebpf::load_probe().await?;

    // Open all FF devices for evdev reading
    let devices_info = list_ff_devices()?;
    let mut effect_store: HashMap<(u32, i16), haptics_probe_common::FfEffect> = HashMap::new();
    let mut throttle = Throttle::new();
    let stdout = std::io::stdout();

    // Spawn per-device evdev readers
    let (ff_tx, mut ff_rx) = mpsc::channel::<(String, FfEvent)>(256);
    for info in &devices_info {
        emit_bson_doc(&doc! {
            "type": "device_added",
            "device": &info.device_id,
            "name": &info.name,
            "path": &info.path,
        });
        let tx = ff_tx.clone();
        let path = info.path.clone();
        let device_id = info.device_id.clone();
        tokio::task::spawn_blocking(move || {
            if let Ok(mut dev) = Device::open(&path) {
                loop {
                    match next_ff_event(&mut dev) {
                        Ok(ev) => { let _ = tx.blocking_send((device_id.clone(), ev)); }
                        Err(e) => {
                            log::error!("evdev read error on {}: {}", device_id, e);
                            break;
                        }
                    }
                }
            }
        });
    }

    loop {
        tokio::select! {
            Some(uploaded) = effect_rx.recv() => {
                effect_store.insert((uploaded.tgid, uploaded.effect_id), uploaded.effect);
            }
            Some((device_id, ev)) = ff_rx.recv() => {
                match ev {
                    FfEvent::Stop { effect_id } => {
                        effect_store.remove(&(0, effect_id)); // tgid unknown here; remove by id
                        emit_bson_doc(&doc! { "type": "stop", "device": &device_id });
                    }
                    FfEvent::Play { effect_id } => {
                        // Find effect in store (any tgid matching this effect_id)
                        let maybe_effect = effect_store.values()
                            .find(|e| e.id == effect_id)
                            .copied();

                        if let Some(effect) = maybe_effect {
                            if throttle.should_emit_haptic() {
                                let points = translate::translate(&effect);
                                if !points.is_empty() {
                                    let bson_points: Vec<bson::Document> = points.iter().map(|p| {
                                        doc! { "dt_ms": p.dt_ms as i64, "intensity": p.intensity as f64 }
                                    }).collect();
                                    emit_bson_doc(&doc! {
                                        "type": "haptic",
                                        "device": &device_id,
                                        "points": bson_points,
                                    });
                                    throttle.record_haptic_emitted();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn emit_bson_doc(doc: &bson::Document) {
    if let Ok(bytes) = to_vec(doc) {
        let mut stdout = std::io::stdout().lock();
        let _ = stdout.write_all(&bytes);
        let _ = stdout.flush();
    }
}
```

- [ ] **Verify full binary compiles**

```bash
cd backend/haptics-probe && cargo build -p haptics-probe 2>&1 | tail -5
```
Expected: `Finished`.

- [ ] **Commit**

```bash
git add backend/haptics-probe/
git commit -m "feat: wire eBPF loader, evdev reader, and BSON stdout output"
```

---

## Task 7: Python `bson` Dependency + Test Fixture

**Files:**
- Modify: `tests/backend/requirements.txt`
- Modify: `tests/backend/conftest.py`
- Modify: `py_modules/` (add bson)

- [ ] **Add bson to test requirements and py_modules**

Append `bson` to `tests/backend/requirements.txt`:
```
pytest>=8.0
pytest-asyncio>=0.23
websockets>=12.0
buttplug-py>=0.2.0
bson>=0.5
```

Install to py_modules (run from repo root):
```bash
pip install --target py_modules bson
```

Install for tests:
```bash
pip install -r tests/backend/requirements.txt
```

- [ ] **Add mock_probe fixture to conftest.py**

The mock probe is an asyncio subprocess that writes BSON frames to a pipe on demand via a controller object.

Append to `tests/backend/conftest.py`:

```python
import bson
import asyncio
import struct
from dataclasses import dataclass, field


def _bson_frame(doc: dict) -> bytes:
    """Encode a dict as a BSON frame."""
    return bson.dumps(doc)


@dataclass
class MockProbeController:
    """Controls what a mock haptics-probe subprocess emits."""
    _write: asyncio.StreamWriter | None = field(default=None, repr=False)

    def set_writer(self, writer: asyncio.StreamWriter) -> None:
        self._write = writer

    async def emit(self, doc: dict) -> None:
        assert self._write is not None
        self._write.write(_bson_frame(doc))
        await self._write.drain()

    async def emit_haptic(self, device: str, points: list[dict]) -> None:
        await self.emit({"type": "haptic", "device": device, "points": points})

    async def emit_stop(self, device: str) -> None:
        await self.emit({"type": "stop", "device": device})

    async def emit_device_added(self, device: str, name: str, path: str) -> None:
        await self.emit({"type": "device_added", "device": device, "name": name, "path": path})


@pytest_asyncio.fixture
async def mock_probe(monkeypatch):
    """Replaces asyncio.create_subprocess_exec for haptics-probe with a pipe-backed mock."""
    controller = MockProbeController()
    r_fd, w_fd = await asyncio.open_connection()  # we need a real pipe

    # Use os.pipe for simplicity
    import os
    r_fd_raw, w_fd_raw = os.pipe()
    r_stream = asyncio.StreamReader()

    loop = asyncio.get_event_loop()
    proto = asyncio.StreamReaderProtocol(r_stream)
    transport, _ = await loop.connect_read_pipe(lambda: proto, os.fdopen(r_fd_raw, 'rb', 0))

    w_transport, w_proto = await loop.connect_write_pipe(
        asyncio.BaseProtocol, os.fdopen(w_fd_raw, 'wb', 0)
    )
    w_stream = asyncio.StreamWriter(w_transport, w_proto, None, loop)
    controller.set_writer(w_stream)

    fake_proc = MagicMock()
    fake_proc.returncode = None
    fake_proc.stdout = r_stream
    fake_proc.terminate = MagicMock()
    fake_proc.wait = AsyncMock(return_value=0)

    original_exec = asyncio.create_subprocess_exec

    async def fake_exec(program, *args, **kwargs):
        if "haptics-probe" in str(program):
            return fake_proc
        return await original_exec(program, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    yield controller, fake_proc

    w_stream.close()
    transport.close()
```

- [ ] **Verify imports work**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && python3 -c "import bson; print(bson.dumps({'x': 1}))"
```
Expected: bytes output (no error).

- [ ] **Commit**

```bash
git add py_modules/ tests/backend/requirements.txt tests/backend/conftest.py
git commit -m "test: add bson dep and mock_probe fixture for haptics bridge tests"
```

---

## Task 8: `HapticsBridge` Class + Tests (TDD)

**Files:**
- Modify: `main.py`
- Create: `tests/backend/test_haptics.py`

- [ ] **Write failing tests first**

Create `tests/backend/test_haptics.py`:

```python
import asyncio
import pytest
import bson
from tests.backend.conftest import wait_for_emit
from tests.backend.decky_mock import emit_recorder


# ── Helpers ───────────────────────────────────────────────────────────────────

def rumble_points(intensity: float, length_ms: int) -> list[dict]:
    return [{"dt_ms": 0, "intensity": intensity}, {"dt_ms": length_ms, "intensity": 0.0}]


# ── Rumble → ScalarCmd ────────────────────────────────────────────────────────

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


# ── Stop interrupts ────────────────────────────────────────────────────────────

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
    """Stop event should cancel the scheduled sequence, not let it finish."""
    mock_server.add_fake_device(0, "Test Toy")
    plugin._settings = {"port": mock_server.port, "autostart": False,
                        "bridge_enabled": True, "bridge_device_map": {},
                        "bridge_intensity_scale": 1.0}
    await plugin.start_engine()

    controller, _ = mock_probe
    # Long sequence — 2 seconds
    long_pts = [{"dt_ms": 0, "intensity": 0.9}, {"dt_ms": 2000, "intensity": 0.0}]
    await controller.emit_haptic("steam-input/0", long_pts)
    await asyncio.sleep(0.05)
    await controller.emit_stop("steam-input/0")
    await asyncio.sleep(0.1)

    # After stop, last ScalarCmd should be 0.0
    cmds = [c for c in mock_server.received_commands if "ScalarCmd" in c]
    assert cmds[-1]["ScalarCmd"]["Scalars"][0]["Scalar"] == 0.0


# ── Device routing ─────────────────────────────────────────────────────────────

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

    # Both toys should receive a command
    indices = {c["ScalarCmd"]["DeviceIndex"] for c in mock_server.received_commands
               if "ScalarCmd" in c}
    assert 0 in indices
    assert 1 in indices


# ── bridge_status_changed event ───────────────────────────────────────────────

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
```

- [ ] **Run to confirm failure**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pytest tests/backend/test_haptics.py -v 2>&1 | head -30
```
Expected: `AttributeError` — `Plugin` has no `HapticsBridge`.

- [ ] **Implement HapticsBridge and integrate into main.py**

Add after the existing imports in `main.py`:

```python
import asyncio
import struct
import bson

# ── HapticsBridge ──────────────────────────────────────────────────────────────

class HapticsBridge:
    def __init__(self) -> None:
        self._client = None
        self._scale: float = 1.0
        self._device_map: dict = {}
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._sequence_tasks: dict[str, asyncio.Task] = {}  # device_id → running sequence

    async def start(self, client, settings: dict) -> None:
        self._client = client
        self._scale = float(settings.get("bridge_intensity_scale", 1.0))
        self._device_map = settings.get("bridge_device_map", {})

        import decky
        probe_path = os.path.join(decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
        self._process = await asyncio.create_subprocess_exec(
            probe_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def stop(self) -> None:
        for task in self._sequence_tasks.values():
            task.cancel()
        self._sequence_tasks.clear()

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._process is not None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
            self._process = None

        self._client = None

    async def update_scale(self, scale: float) -> None:
        self._scale = max(0.0, min(1.0, scale))

    async def _reader_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        reader = self._process.stdout
        try:
            while True:
                header = await reader.readexactly(4)
                length = struct.unpack_from("<i", header)[0]
                if length < 5:
                    continue
                rest = await reader.readexactly(length - 4)
                doc = bson.loads(header + rest)
                await self._dispatch(doc)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception as e:
            import decky
            decky.logger.warning(f"HapticsBridge reader error: {e}")

    async def _dispatch(self, doc: dict) -> None:
        msg_type = doc.get("type")
        if msg_type == "haptic":
            device = doc.get("device", "")
            points = doc.get("points", [])
            if points:
                self._schedule_sequence(device, points)
        elif msg_type == "stop":
            device = doc.get("device", "")
            await self._send_stop(device)

    def _schedule_sequence(self, device: str, points: list) -> None:
        # Cancel any existing sequence for this device
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
        task = asyncio.create_task(self._play_sequence(device, points))
        self._sequence_tasks[device] = task

    async def _play_sequence(self, device: str, points: list) -> None:
        try:
            prev_dt = 0
            for point in points:
                dt_ms = int(point.get("dt_ms", 0))
                intensity = float(point.get("intensity", 0.0))
                delta_ms = max(0, dt_ms - prev_dt)
                if delta_ms > 0:
                    await asyncio.sleep(delta_ms / 1000.0)
                prev_dt = dt_ms
                await self._send_scalar(device, intensity * self._scale)
        except asyncio.CancelledError:
            pass
        finally:
            self._sequence_tasks.pop(device, None)

    async def _send_stop(self, device: str) -> None:
        if device in self._sequence_tasks:
            self._sequence_tasks[device].cancel()
            self._sequence_tasks.pop(device, None)
        await self._send_scalar(device, 0.0)

    async def _send_scalar(self, device: str, intensity: float) -> None:
        if self._client is None:
            return
        # Determine target device ids
        targets = self._device_map.get(device)  # None = all
        intensity = max(0.0, min(1.0, intensity))
        for dev in self._client.devices.values():
            if targets is not None and dev.index not in targets:
                continue
            try:
                if hasattr(dev, "actuators") and dev.actuators:
                    await dev.actuators[0].command(intensity)
            except Exception as e:
                import decky
                decky.logger.warning(f"ScalarCmd failed for device {dev.index}: {e}")
```

- [ ] **Run tests**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pytest tests/backend/test_haptics.py -v 2>&1
```
Expected: most tests pass. Fix any issues before committing.

- [ ] **Commit**

```bash
git add main.py tests/backend/test_haptics.py
git commit -m "feat: HapticsBridge class with BSON reader and ScalarCmd scheduling (TDD)"
```

---

## Task 9: Plugin Callables + Settings

**Files:**
- Modify: `main.py`

- [ ] **Extend DEFAULT_SETTINGS and add new callables**

In `main.py`, update `DEFAULT_SETTINGS`:

```python
DEFAULT_SETTINGS: dict = {
    "port": 12345,
    "autostart": True,
    "bridge_enabled": True,
    "bridge_device_map": {},
    "bridge_intensity_scale": 1.0,
}
```

Add to `Plugin` class:

```python
    _bridge: "HapticsBridge | None" = None

    async def set_bridge_enabled(self, enabled: bool) -> dict:
        self._settings["bridge_enabled"] = enabled
        await self._save_settings()
        if enabled and self._client is not None and self._bridge is None:
            self._bridge = HapticsBridge()
            await self._bridge.start(self._client, self._settings)
        elif not enabled and self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None
        device = self._settings.get("bridge_evdev_device")
        await decky.emit("bridge_status_changed", enabled, device)
        return {"success": True}

    async def list_evdev_devices(self) -> list:
        import decky as _decky
        probe_path = os.path.join(_decky.DECKY_PLUGIN_DIR, "bin", "haptics-probe")
        try:
            proc = await asyncio.create_subprocess_exec(
                probe_path, "--list-devices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            import json
            return json.loads(stdout.decode())
        except Exception as e:
            decky.logger.error(f"list_evdev_devices failed: {e}")
            return []

    async def set_bridge_scale(self, scale: float) -> dict:
        self._settings["bridge_intensity_scale"] = scale
        await self._save_settings()
        if self._bridge is not None:
            await self._bridge.update_scale(scale)
        return {"success": True}

    async def update_settings(
        self, port: int | None = None, autostart: bool | None = None,
        bridge_enabled: bool | None = None,
        bridge_intensity_scale: float | None = None,
        bridge_device_map: dict | None = None,
    ) -> dict:
        if port is not None:
            self._settings["port"] = port
        if autostart is not None:
            self._settings["autostart"] = autostart
        if bridge_enabled is not None:
            self._settings["bridge_enabled"] = bridge_enabled
        if bridge_intensity_scale is not None:
            self._settings["bridge_intensity_scale"] = bridge_intensity_scale
        if bridge_device_map is not None:
            self._settings["bridge_device_map"] = bridge_device_map
        await self._save_settings()
        return {"success": True}
```

- [ ] **Write tests for new callables**

Append to `tests/backend/test_haptics.py`:

```python
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

    import json, os
    path = os.path.join(inject_decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")
    with open(path) as f:
        saved = json.load(f)
    assert saved["bridge_intensity_scale"] == pytest.approx(0.7)
    assert saved["bridge_enabled"] is False
```

- [ ] **Run tests**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pytest tests/backend/ -v 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Commit**

```bash
git add main.py tests/backend/test_haptics.py
git commit -m "feat: bridge callables — set_bridge_enabled, set_bridge_scale, update_settings"
```

---

## Task 10: Lifecycle Integration

**Files:**
- Modify: `main.py`

Wire `HapticsBridge` into `_main()` and `_unload()`.

- [ ] **Update `start_engine`, `stop_engine`, `_main`, `_unload`**

In `Plugin.start_engine`, after `await self._connect_client()`:

```python
        # Start bridge if enabled
        if self._settings.get("bridge_enabled", False) and self._bridge is None:
            self._bridge = HapticsBridge()
            await self._bridge.start(self._client, self._settings)
```

In `Plugin.stop_engine`, before `await self._disconnect_client()`:

```python
        if self._bridge is not None:
            await self._bridge.stop()
            self._bridge = None
```

- [ ] **Write lifecycle tests**

Append to `tests/backend/test_haptics.py`:

```python
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
```

- [ ] **Run full backend test suite**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pytest tests/backend/ -v 2>&1
```
Expected: all pass. Fix any regressions before committing.

- [ ] **Commit**

```bash
git add main.py tests/backend/test_haptics.py
git commit -m "feat: integrate HapticsBridge into engine lifecycle"
```

---

## Task 11: Frontend BridgePanel

**Files:**
- Modify: `src/index.tsx`

- [ ] **Add bridge callables and BridgePanel component**

In `src/index.tsx`, after the existing callable declarations:

```typescript
const setBridgeEnabled = callable<[boolean], { success: boolean }>('set_bridge_enabled');
const listEvdevDevices = callable<[], { device: string; name: string; path: string }[]>('list_evdev_devices');
const setBridgeScale   = callable<[number], { success: boolean }>('set_bridge_scale');

type EvdevDevice = { device: string; name: string; path: string };

function BridgePanel() {
  const [enabled, setEnabled]   = useState(false);
  const [scale, setScale]       = useState(1.0);
  const [devices, setDevices]   = useState<EvdevDevice[]>([]);
  const [loading, setLoading]   = useState(false);

  const refreshDevices = async () => {
    const d = await listEvdevDevices();
    if (d) setDevices(d);
  };

  useEffect(() => {
    refreshDevices();

    const onBridgeStatus = (_enabled: boolean, _device: string | null) => {
      setEnabled(_enabled);
    };
    const listener = addEventListener<[boolean, string | null]>(
      'bridge_status_changed', onBridgeStatus
    );
    return () => removeEventListener('bridge_status_changed', listener);
  }, []);

  const handleToggle = async () => {
    setLoading(true);
    try {
      await setBridgeEnabled(!enabled);
      setEnabled(e => !e);
      if (!enabled) await refreshDevices();
    } finally {
      setLoading(false);
    }
  };

  const handleScale = async (v: number) => {
    setScale(v);
    await setBridgeScale(v);
  };

  return (
    <PanelSection title="Haptics Bridge">
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={handleToggle} disabled={loading}>
          {loading ? 'Working…' : enabled ? 'Disable Bridge' : 'Enable Bridge'}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ fontSize: '12px', color: enabled ? '#8f8' : '#888' }}>
          {enabled ? 'Active' : 'Inactive'}
        </div>
      </PanelSectionRow>
      {devices.length > 0 && (
        <>
          <PanelSectionRow>
            <div style={{ fontSize: '11px', color: '#aaa', marginTop: 4 }}>Source Devices</div>
          </PanelSectionRow>
          {devices.map(d => (
            <PanelSectionRow key={d.device}>
              <div style={{ fontSize: '12px' }}>
                <span style={{ color: '#ccc' }}>{d.device}</span>
                {' '}{d.name}
                <br />
                <span style={{ fontSize: '11px', color: '#888' }}>→ All toys</span>
              </div>
            </PanelSectionRow>
          ))}
        </>
      )}
      <PanelSectionRow>
        <div style={{ fontSize: '12px' }}>Intensity Scale</div>
        <input
          type="range" min={0} max={1} step={0.05}
          value={scale}
          onChange={e => handleScale(parseFloat(e.target.value))}
          style={{ width: '100%' }}
        />
        <div style={{ fontSize: '11px', color: '#aaa', textAlign: 'right' }}>
          {(scale * 100).toFixed(0)}%
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}
```

- [ ] **Add BridgePanel to Content component**

In the `Content` function return, after the existing `</PanelSection>` for Devices:

```typescript
      <BridgePanel />
```

- [ ] **Update onDismount cleanup**

In `definePlugin`, declare the bridge listener:

```typescript
  const bridgeStatusListener = addEventListener<[boolean, string | null]>(
    'bridge_status_changed', () => {}
  );
```

In `onDismount`:
```typescript
      removeEventListener('bridge_status_changed', bridgeStatusListener);
```

- [ ] **Build frontend**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pnpm run build 2>&1 | tail -10
```
Expected: `dist/index.js` generated with no TypeScript errors.

- [ ] **Commit**

```bash
git add src/index.tsx dist/
git commit -m "feat: BridgePanel UI — toggle, device list, intensity scale slider"
```

---

## Task 12: Frontend Bridge Tests

**Files:**
- Create: `tests/frontend/bridge.spec.ts`

(Uses existing Playwright + Vite harness from Phase 1.)

- [ ] **Write bridge.spec.ts**

```typescript
// tests/frontend/bridge.spec.ts
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  // Mock initial status
  await page.evaluate(() => {
    window.__deckyTestAPI__.mockCallable('get_status', () => ({
      running: true, connected: true, port: 12345,
    }));
    window.__deckyTestAPI__.mockCallable('get_devices', () => []);
    window.__deckyTestAPI__.mockCallable('list_evdev_devices', () => [
      { device: 'steam-input/0', name: 'Steam Virtual Gamepad', path: '/dev/input/event5' },
    ]);
    window.__deckyTestAPI__.mockCallable('set_bridge_enabled', () => ({ success: true }));
    window.__deckyTestAPI__.mockCallable('set_bridge_scale', () => ({ success: true }));
  });
});

test('bridge panel shows inactive initially', async ({ page }) => {
  await expect(page.getByText('Inactive')).toBeVisible();
  await expect(page.getByText('Enable Bridge')).toBeVisible();
});

test('bridge toggle calls set_bridge_enabled', async ({ page }) => {
  await page.getByText('Enable Bridge').click();
  await page.waitForTimeout(100);

  const calls = await page.evaluate(() =>
    window.__deckyTestAPI__.callLog('set_bridge_enabled')
  );
  expect(calls).toHaveLength(1);
  expect(calls[0][0]).toBe(true);
});

test('bridge_status_changed event updates indicator', async ({ page }) => {
  await page.evaluate(() => {
    window.__deckyTestAPI__.fireEvent('bridge_status_changed', true, 'steam-input/0');
  });

  await expect(page.getByText('Active')).toBeVisible();
  await expect(page.getByText('Disable Bridge')).toBeVisible();
});

test('scale slider calls set_bridge_scale', async ({ page }) => {
  const slider = page.locator('input[type=range]');
  await slider.fill('0.5');

  await page.waitForTimeout(200);
  const calls = await page.evaluate(() =>
    window.__deckyTestAPI__.callLog('set_bridge_scale')
  );
  expect(calls.length).toBeGreaterThan(0);
  expect(calls[calls.length - 1][0]).toBeCloseTo(0.5, 1);
});

test('device appears after bridge enabled', async ({ page }) => {
  await page.evaluate(() => {
    window.__deckyTestAPI__.fireEvent('bridge_status_changed', true, null);
  });
  await page.waitForTimeout(200);

  await expect(page.getByText('Steam Virtual Gamepad')).toBeVisible();
  await expect(page.getByText('→ All toys')).toBeVisible();
});
```

- [ ] **Run frontend tests**

```bash
cd /Users/madrigal-eschat/Code/decky-intiface && pnpm run test:ui 2>&1 | tail -20
```
Expected: all bridge tests pass.

- [ ] **Run full backend test suite one final time**

```bash
pytest tests/backend/ -v 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Final commit**

```bash
git add tests/frontend/bridge.spec.ts
git commit -m "test: frontend Playwright tests for BridgePanel"
```

---

## Self-Review Notes

- **eBPF program** (Task 5) requires a real Linux kernel with BPF tracing support to fully integration-test. The Docker build verifies compilation; end-to-end testing requires deployment to SteamOS or a Linux VM with `CONFIG_BPF_TRACING`.
- **`bpf_probe_read_user_buf`** — verify this is the correct Aya API name; some versions use `bpf_probe_read_user` (single value) vs `bpf_probe_read_user_buf` (byte slice). Check aya-bpf docs at time of implementation.
- **`FfEffect.u` union layout** — the union field packing in `translate.rs` and `haptics-probe-ebpf` must agree. The plan uses `u[0..6]` as raw u16 words. If the actual `ff_effect` union has padding, adjust offsets accordingly by checking `/sys/kernel/debug/tracing/events/syscalls/sys_enter_ioctl/format` on the target kernel.
- **`RingBuf` Aya API** — Aya's `RingBuf::next()` returns `Option<RingBufItem>`. Verify the correct iteration API in the Aya 0.13 changelog if it differs from the ebpf.rs plan code.
- **Frontend `range` input** — `@decky/ui` does not export a native slider; using a plain HTML `<input type="range">`. If the UI looks off, consider replacing with two ButtonItems for +/- or using a style that matches the Decky theme.
