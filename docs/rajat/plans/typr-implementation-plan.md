# Typr — Implementation Plan

**Paired with:** `docs/specs/typr-spec.md`
**Status:** Draft v1 — awaiting approval before any code is written
**Estimated total time:** 7–9 hours focused work
**Parallelization:** Phases 3+4 can run in parallel (audio vs Groq); phases 8+9 can run in parallel (downloader vs local whisper)

---

## Phase 0 — Scaffold

**Goal:** Empty Tauri window launches.

1. `npm create tauri-app@latest typr -- --template vanilla-ts` (run in `~/Downloads/`, will create `typr/`; we'll move existing `docs/` into it)
2. `cd typr && npm install`
3. Install JS plugins:
   ```
   npm i @tauri-apps/plugin-global-shortcut \
         @tauri-apps/plugin-store \
         @tauri-apps/plugin-clipboard-manager \
         @tauri-apps/plugin-shell
   ```
4. Add Rust deps in `src-tauri/Cargo.toml`:
   - `tauri-plugin-global-shortcut`, `tauri-plugin-store`, `tauri-plugin-clipboard-manager`, `tauri-plugin-shell`
   - `cpal`, `rubato`, `hound`
   - `reqwest = { features = ["multipart", "stream"] }`, `tokio = { features = ["full"] }`, `futures-util`
   - `whisper-rs`
   - `arboard`, `enigo`
   - `serde`, `serde_json`, `anyhow`, `thiserror`, `once_cell`, `dirs`, `num_cpus`
5. Register plugins in `src-tauri/src/lib.rs` `run()` builder
6. Smoke test: `npm run tauri dev`

**Verify:** Empty window opens. No errors in console.

---

## Phase 1 — Main window shell

**Goal:** Frameless, draggable, dark-mode settings window with all controls visible (not wired).

1. `tauri.conf.json`:
   - `decorations: false`
   - `transparent: true`
   - `width: 440, height: 620, resizable: false`
   - `dragDropEnabled: true` (bug #3)
2. `index.html`: set viewport, load `main.ts`, mount root `<div id="app">`
3. `styles.css`: design tokens, Inter font (from `/fonts/`), body `background: transparent`
4. `main.ts`: render static markup — top drag bar + sections (Engine, Mic, Hotkey, Behavior, Groq key, Models)
5. Top bar: `<div class="titlebar" data-tauri-drag-region>Typr</div>` + close button (invokes `window.close()`)
6. Root element: `border-radius: 12px; background: #0B0B0E;` so rounded corners show through the transparent window

**Verify:**
- Window drags by top bar
- Corners are visibly rounded
- No native title bar
- All form controls visible, dark mode, Linear-ish aesthetic
- Close button closes the app

---

## Phase 2 — Settings store + wiring

**Goal:** Settings persist across restarts.

1. Rust: `settings.rs` module with `Settings` struct (matches §5 of spec), `Default` impl
2. Commands: `get_settings() -> Settings`, `set_setting(key: String, value: Value)`
3. Use `tauri-plugin-store` backed by `settings.json` in app data dir
4. Frontend `settings.ts` module: `loadSettings()`, `saveSetting(key, value)` wrappers around `invoke`
5. Wire every control on the main window: onChange → `saveSetting`; on mount → `loadSettings` + populate

**Verify:**
- Change mic dropdown → close app → reopen → mic still selected
- Same for engine, behavior, local model, API key

---

## Phase 3 — Audio capture (parallelizable with Phase 4)

**Goal:** Record a 3-second test clip, write to WAV on disk, open in an audio tool — sample rate correct.

1. Rust `audio.rs`:
   - `list_input_devices() -> Vec<String>` command
   - `Recorder` struct wrapping `Option<cpal::Stream>` + `Arc<Mutex<Vec<f32>>>` + `(native_sr, channels)`
   - `start_recording(device_name: Option<String>)` — opens stream, records interleaved samples
   - `stop_recording() -> AudioClip` where `AudioClip = { samples: Vec<f32>, sample_rate: 16000 }`
     - Drops stream (bug #4)
     - Downmix to mono
     - Resample to 16 kHz via rubato
   - 120 s hard cap: in cpal callback, if buffer length exceeds native_sr * 120, stop writing and flag
2. Populate mic dropdown in frontend from `list_input_devices`
3. Temporary debug command `save_last_clip_wav(path)` that writes `hound::WavWriter` — remove before phase 11

**Verify:**
- Dropdown shows at least the system default mic
- Call start → wait 3s → stop → save WAV → inspect in Audacity or QuickTime
- WAV is 16 kHz mono 16-bit, duration ≈ 3s, audio is clean

---

## Phase 4 — Groq transcription (parallelizable with Phase 3)

**Goal:** Feed a pre-recorded WAV (or Phase 3's output) and get correct text back.

1. Rust `transcribe/groq.rs`:
   - `transcribe_groq(wav_bytes: Vec<u8>, api_key: String) -> Result<String>` command
   - `reqwest::multipart::Form` with `file` (WAV bytes, filename `audio.wav`), `model=whisper-large-v3-turbo`, `response_format=json`, `language=en`
   - POST to `https://api.groq.com/openai/v1/audio/transcriptions` with `Authorization: Bearer <key>`
   - 30 s timeout
   - Parse `{ "text": "..." }` → return
2. Frontend test button on settings page (remove before ship): "Test Groq" — records 3s, POSTs, shows result

**Verify:**
- With valid key + recorded clip: correct transcription returned
- With invalid key: error surfaced clearly
- With no key: fail fast before POST

---

## Phase 5 — Global hotkey + mode dispatch

**Goal:** Press hotkey anywhere on system → see `recorder-state` event flip.

1. Register in `setup()` hook after `app.ready()` (bug #6):
   ```rust
   app.global_shortcut().on_shortcut("Shift+CommandOrControl+Space", |app, _shortcut, event| {
       match event.state() {
           ShortcutState::Pressed  => handle_hotkey_press(app),
           ShortcutState::Released => handle_hotkey_release(app),
       }
   })
   ```
2. Dispatch in `handle_hotkey_press`:
   - If mode=push_to_talk → `start_recording_with_active_engine()`
   - If mode=toggle → flip `is_recording`; on transition start, call start; on transition stop, call stop
3. `handle_hotkey_release`:
   - If mode=push_to_talk → `stop_and_transcribe()`
   - If mode=toggle → ignore
4. Emit `recorder-state` event on every transition: `"idle" | "recording" | "transcribing"`
5. On Mac: if accessibility permission is missing, show modal with instructions (open System Settings via `tauri-plugin-shell` `open`)

**Verify:**
- Press hotkey globally (outside app focus) → state changes visible in dev console via event listener
- Both modes work
- Releasing when idle doesn't crash

---

## Phase 6 — Overlay window

**Goal:** Red pulsing circle top-right while recording, yellow while transcribing, invisible when idle.

1. Add second window to `tauri.conf.json`:
   - label `overlay`
   - `width: 40, height: 40`
   - `transparent: true, decorations: false, alwaysOnTop: true, skipTaskbar: true, resizable: false, focus: false, shadow: false`
   - `visible: false` initially
2. `overlay.html` + `overlay.css` + `overlay.ts`:
   - `<body><div class="mic"></div></body>`, body transparent
   - `.mic { width: 40px; height: 40px; border-radius: 50%; }`
   - `[data-state="idle"] .mic { display: none; }`
   - `[data-state="recording"] .mic { background: #FF3B30; animation: pulse 1.1s ease-in-out infinite alternate; }`
   - Same for transcribing with `#FFCC00`
   - `@keyframes pulse { from { transform: scale(1); opacity: 1; } to { transform: scale(1.15); opacity: 0.6; } }`
3. On DOM load, subscribe to `recorder-state` event → `document.body.dataset.state = payload`
4. Rust: on app setup, position overlay top-right via primary monitor size minus (40+16, 40+16 from top), and call `set_ignore_cursor_events(true)` (click-through)
5. Show/hide overlay on state transitions: show on record start, keep visible through transcribing, hide on return to idle

**Verify:**
- Trigger hotkey → red pulse appears top-right
- Stop → switches to yellow
- Transcription completes → overlay hides
- Mouse clicks through the overlay (can click apps behind it)

---

## Phase 7 — Auto-paste

**Goal:** Record → transcribe → text appears at cursor in whatever app is focused.

1. After `transcribe_*` returns text:
   a. Post-process (§10 of spec)
   b. `arboard::Clipboard::new()?.set_text(cleaned)`
   c. `std::thread::sleep(Duration::from_millis(40))`
   d. `enigo::Enigo::new()?` → synthesize Cmd+V (Mac) / Ctrl+V (Win)
2. Platform detection via `#[cfg(target_os = "macos")]` + `#[cfg(target_os = "windows")]`
3. Swallow any paste error (don't crash) but toast it in main window

**Verify:**
- Open TextEdit / Notepad, trigger hotkey, speak "Hello world", release
- "Hello world" appears in the editor

---

## Phase 8 — Model downloader (parallelizable with Phase 9)

**Goal:** Click Download → progress bar fills → file on disk.

1. Shared helper `models.rs`:
   - `fn models_dir() -> PathBuf { app_data_dir().join("models") }`
   - `fn model_path(size: ModelSize) -> PathBuf { models_dir().join(format!("ggml-{}.bin", size.as_str())) }`
   - `fn list_downloaded() -> Vec<ModelSize>` — scans dir
2. Command `download_model(size: String) -> Result<()>`:
   - URL: `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{size}.bin`
   - `reqwest::get(url).await?` → `.bytes_stream()`
   - Write chunks to `.partial` file
   - Every 250 ms, emit `model-download-progress` `{ size, bytes_done, bytes_total, percent }`
   - On EOF: rename `.partial` → final, emit `model-download-complete { size }`
   - On error: delete partial, emit `model-download-error { size, message }`
3. Command `list_downloaded_models() -> Vec<String>`
4. Frontend Models section:
   - Dropdown of sizes
   - Disabled state on sizes not yet downloaded — option label shows "(not downloaded)"
   - Download button next to dropdown
   - Progress bar below (hidden when idle, shows 0–100%)
   - Status line "X / 5 downloaded"
5. On app startup, frontend calls `list_downloaded_models()` → refreshes `downloaded_models` setting

**Verify:**
- Select `tiny` (75 MB for fast test), click Download
- Progress bar moves smoothly from 0 → 100
- File exists at `~/Library/Application Support/com.typr.dev/models/ggml-tiny.bin` (Mac) or equivalent on Win
- Status line updates to "1 / 5 downloaded"
- Dropdown can now select Tiny

---

## Phase 9 — Local Whisper (parallelizable with Phase 8)

**Goal:** Disconnect wifi, record, transcribe locally.

1. `transcribe/local.rs`:
   - `static CONTEXTS: Lazy<Mutex<HashMap<ModelSize, Arc<WhisperContext>>>>` cache
   - `fn get_ctx(size)`: lazy-load `WhisperContext::new_with_params(&model_path(size), ctx_params)`
   - `transcribe_local(samples: Vec<f32>, size: String) -> Result<String>` command
   - Params: `strategy=BeamSearch { beam_size: 5, patience: 1.0 }`, `n_threads = (num_cpus::get() - 1).max(1)`, `language=Some("en")`, `no_timestamps=true`, `suppress_blank=true`
   - Run `state.full(params, &samples)`, concatenate segments, return
2. Wire engine dispatcher:
   - If `settings.engine == "groq"` → encode clip to WAV bytes → `transcribe_groq`
   - If `settings.engine == "local"` → pass samples directly to `transcribe_local`
3. Guardrails:
   - If engine=local and model not downloaded → toast "Download the model first" + no paste
   - If engine=groq and api_key empty → toast "Set a Groq key first"

**Verify:**
- Download `tiny` model, set engine=local, set model=tiny
- Airplane mode ON
- Hotkey → speak → release → transcription appears
- Try `medium` model (slower but higher quality) — still works

---

## Phase 10 — Polish

**Goal:** First-launch UX + error surface + remove debug code.

1. Remove any Phase 3/4 debug buttons and save-WAV command
2. Onboarding modal on first launch (detected via `settings.first_run_completed = false`):
   - Welcome copy
   - Mac-only: step-by-step for granting Mic + Accessibility
   - "Got it" button sets `first_run_completed = true`
3. Error toast component: listens to a `toast` event, shows 4s then fades
4. Loading states:
   - Disable hotkey while transcribing (ignore new press)
   - Disable Download button while any download in progress
5. Validation:
   - If engine=groq and key missing → inline warning under the Groq section
   - If engine=local and no models downloaded → inline warning under Models section
6. Info.plist entries (Mac, bug #7): `NSMicrophoneUsageDescription` + hardened-runtime entitlements for mic and accessibility

**Verify:**
- Fresh install (delete app data dir first) → onboarding modal shows
- After dismiss, never shows again
- Trigger both error states manually — toasts appear + fade

---

## Phase 11 — Build + self-ship

**Goal:** Installable bundle on both platforms.

1. `npm run tauri build` on Mac → `.dmg` in `src-tauri/target/release/bundle/dmg/`
2. Install the dmg, drag to Applications
3. Run full `POST-BUILD CHECKLIST` from user's original plan doc (§ of that file)
4. Same on Windows: `.msi` output
5. Git:
   ```
   cd ~/Downloads/typr
   git init
   git add .
   git commit -m "Initial Typr build"
   ```
   (Push to GitHub is deferred — ask Rajat when ready; see §13 below.)

**Verify:** Every item in user's POST-BUILD CHECKLIST passes in the bundled build (not just dev mode).

---

## Phase ordering + parallelization

```
0 → 1 → 2 → ┬─> 3 ─┐
            │     ├─> 5 → 6 → 7 → ┬─> 8 ─┐
            └─> 4 ─┘                ├─> 10 → 11
                                    └─> 9 ─┘
```

Claude sub-agents run Phase 3 and Phase 4 in parallel, then Phase 8 and Phase 9 in parallel.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| whisper-rs build fails on Windows | Medium | Fallback: shell out to `whisper.cpp` binary. Decision point after Phase 9 first attempt. |
| enigo key synthesis blocked on Mac without accessibility | High | Explicit permission modal in onboarding + check-and-warn at first paste attempt |
| cpal + specific USB mics: sample rate oddities | Medium | Resample unconditionally; log native SR on record start for debugging |
| Hotkey conflict with another system app | Low | Fallback: if registration fails, show error in main window; user-configurable hotkey is v2 scope |
| Groq API rate limits / auth errors | Low | Clear error message; no retry loop in v1 |

## What counts as "done" for v1

All items in user's POST-BUILD CHECKLIST pass. Rajat uses Typr for a full workday of dictation without hitting a blocker he has to debug manually.

## Deferred to v2 (do not implement now)

- User-configurable hotkey
- OS keychain for API key (via `keyring` crate)
- Transcript history (SQLite via Tauri SQL plugin)
- Auto-punctuation LLM pass
- Custom dictionary
- Tauri updater
- Onboarding video
- Code signing / notarization

## Open questions for Rajat

1. GitHub repo — push to `github.com/rajats2022-coder/typr`, or a different account/name? (Deferred until after phase 11.)
2. App name confirmed as "Typr"? Affects bundle ID (`com.typr.dev`), Info.plist display name, window title.
3. Any personal-use proper nouns / phrases Whisper commonly butchers? (Not a v1 requirement, but if yes, bumps "custom dictionary" up in v2 priority.)

---
