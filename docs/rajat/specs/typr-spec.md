# Typr — Spec

**Owner:** Rajat (S4 AI Agency — personal tool)
**Status:** Draft v1 — awaiting approval before implementation
**Last updated:** 2026-04-22

---

## 1. Purpose

Local, private dictation app. Clone of Whisper Flow. For Rajat's personal use only, runs on macOS + Windows. Global hotkey → record → transcribe (local Whisper or Groq) → auto-paste into whatever app is currently focused.

No transcript history, no cloud sync, no multi-user. Fire and forget.

## 2. User stories

1. Press hotkey anywhere on the system, speak, release → transcribed text appears at the cursor position in the current app.
2. Switch between local Whisper and Groq API without restarting the app.
3. Download local Whisper models from inside the app (progress bar), no CLI or manual install.
4. See a small visual indicator in the top-right of the screen while recording (red pulsing) and while transcribing (yellow pulsing), nothing when idle.
5. Reconfigure mic, engine, hotkey mode, and API key in a single settings window.
6. Close and reopen the app — settings persist.

## 3. Non-goals (v1)

- Transcript history / search
- Auto-punctuation (a second LLM pass after Whisper)
- Custom dictionary / proper-noun handling
- Streaming transcription (v1 is wait-and-return)
- Auto-updates
- Onboarding video / tutorial
- Cloud sync, accounts, payments
- Windows ARM support (Intel/AMD64 only in v1)

## 4. Architecture

### 4.1 High-level

```
┌─────────────────┐        ┌───────────────────────────────┐        ┌───────────────┐
│  Main Window    │◄──────►│         Tauri Core            │◄──────►│ Overlay Window│
│  (settings UI)  │  IPC   │         (Rust backend)        │  IPC   │  (indicator)  │
└─────────────────┘        └──────┬───────┬────────┬───────┘        └───────────────┘
                                  │       │        │
                                  ▼       ▼        ▼
                            Global       Audio    Transcription
                            Hotkey       Capture  (whisper-rs
                            (plugin)     (cpal)    OR Groq API)
                                                  │
                                                  ▼
                                      Auto-paste (arboard + enigo)
```

### 4.2 Tech choices

| Concern | Choice | Why |
|---|---|---|
| Framework | Tauri v2 | Native perf, small binary, Rust backend |
| Frontend | Vite + vanilla TS | Matches reference template, no heavy deps |
| Global hotkey | `tauri-plugin-global-shortcut` v2 | Official; supports key-up events (needed for push-to-talk) |
| Audio capture | `cpal` | De-facto Rust audio crate, cross-platform |
| Audio resampling | `rubato` | Clean native→16kHz conversion for Whisper |
| WAV encoding | `hound` | Simple PCM WAV write for Groq payload |
| Local Whisper | `whisper-rs` crate | Pure Rust bindings to whisper.cpp — no separate binary to bundle or locate |
| Cloud Whisper | `reqwest` multipart → Groq `/audio/transcriptions` | Standard HTTP client |
| Auto-paste | `arboard` (clipboard) + `enigo` (Cmd/Ctrl+V) | More reliable than synthesizing each keystroke |
| Settings storage | `tauri-plugin-store` | Official, JSON-backed, app-data-dir scoped |
| Model download | `reqwest` streaming + Tauri event emitter | No extra deps |
| Monitor info (overlay) | Tauri `Monitor` APIs | No need for `display-info` crate |

### 4.3 Decisions I made (flag if you want to change)

- **Local engine:** `whisper-rs` crate, NOT a bundled `whisper.cpp` binary. Cleaner cross-platform story, no PATH resolution issues. (Avoids known bug #2.)
- **Paste method:** copy-to-clipboard then synthesize Cmd/Ctrl+V, NOT character-by-character typing. Faster, handles special characters, closer to how Whisper Flow behaves.
- **Overlay:** click-through (`set_ignore_cursor_events(true)`) — so cursor can move over it without stealing focus.
- **API key storage:** plain JSON via `tauri-plugin-store` in v1. OS keychain via `keyring` crate flagged as v2 enhancement. Personal-use app, file is already in user's home dir.
- **Hotkey default mode:** `push-to-talk` (matches Whisper Flow feel). User can switch to toggle in settings.
- **Max recording length:** hard cap at 120 seconds. Prevents runaway buffer if hotkey release is missed.
- **Overlay size / position:** 40×40 px, 16 px margin from top + right of primary monitor.
- **Main window size:** 440×620 px, not resizable (fixed layout is simpler and the settings form doesn't need to grow).
- **Bundled default model:** none. First-launch UX is "set Groq key OR download a local model," not "ships with a 466 MB file."

## 5. Settings (persisted)

Stored in `app_data_dir()/settings.json` via `tauri-plugin-store`.

| Key | Type | Default | Notes |
|---|---|---|---|
| `engine` | `"local"` \| `"groq"` | `"groq"` | Groq is fastest + simplest first-run |
| `mic_device_name` | string | `null` (system default) | Store name, not index — indexes shift when devices plug/unplug |
| `hotkey_mode` | `"toggle"` \| `"push_to_talk"` | `"push_to_talk"` | |
| `local_model` | `"tiny"` \| `"base"` \| `"small"` \| `"medium"` \| `"large-v3"` | `"medium"` | Only selectable if downloaded |
| `groq_api_key` | string | `""` | Required when engine=groq |
| `downloaded_models` | string[] | `[]` | Populated by downloader + startup scan |

Hotkey itself is fixed at `Shift+Cmd+Space` (Mac) / `Shift+Ctrl+Space` (Win) in v1. User-configurable hotkey is a v2 enhancement — keeps phase 1 scope tight.

## 6. Windows

### 6.1 Main window

- Frameless: `decorations: false`
- Rounded corners: 12 px (via CSS `border-radius` on root + `transparent: true` on window)
- Draggable via a `<div data-tauri-drag-region>` as the top 48 px bar
- `dragDropEnabled: true` in `tauri.conf.json` (known bug #3)
- Dark mode only — Linear-inspired: near-black bg `#0B0B0E`, surface `#16161A`, accent `#7C5CFF`, text `#E8E8EC`
- Font: Inter (bundled) + system mono fallback for the hotkey display
- Fixed size 440×620, not resizable
- Single page, sections top→bottom:
  1. Drag-region header with app name "Typr" and a close button
  2. **Engine** — radio: Local / Groq
  3. **Microphone** — dropdown, populated from `navigator.mediaDevices.enumerateDevices`
  4. **Hotkey** — read-only display ("⇧⌘Space") + subtitle showing current mode
  5. **Behavior** — radio: Push-to-talk / Toggle
  6. **Groq API key** — password-masked input, test-connection button (optional)
  7. **Local models** — dropdown of sizes + download button + progress bar (hidden when idle) + "X / 5 downloaded" status line

### 6.2 Overlay window

- 40×40 px, positioned top-right with 16 px margin from primary monitor work-area
- `transparent: true`, `decorations: false`, `alwaysOnTop: true`, `skipTaskbar: true`, `focus: false`, `resizable: false`, `shadow: false`
- Click-through via `set_ignore_cursor_events(true)` on window creation
- Body CSS `background: transparent` (known bug #5)
- Three states, driven by a `data-state` attribute on `<body>`:
  - `idle` → `display: none` on the circle
  - `recording` → red `#FF3B30` circle, pulsing (scale 1 → 1.15, opacity 1 → 0.6, 1.1 s ease-in-out infinite alternate)
  - `transcribing` → yellow `#FFCC00` circle, same pulse
- States driven by `tauri://event` listener subscribed to `recorder-state` event from backend

## 7. Hotkey behavior

- Registered in Rust `setup()` hook, AFTER `app.ready()`, AFTER first-launch permission prompts resolve (known bug #6)
- Plugin fires on both Pressed and Released — use `ShortcutEvent::state`
- **Push-to-talk:** Pressed → start recording, Released → stop recording
- **Toggle:** Pressed → toggle `is_recording` boolean, Released → ignored
- Hotkey stays registered across app lifetime; unregistered on app quit

## 8. Audio pipeline

1. `start_recording(device_name)` command:
   - Opens cpal input stream on the selected device (or default)
   - Detects device native sample rate and channel count
   - Writes interleaved f32 samples into a shared `Arc<Mutex<Vec<f32>>>`
   - Also stores `(native_sr, channels)` alongside
2. `stop_recording()` command:
   - Stops the stream, drops it (known bug #4: stream must be dropped, not muted)
   - Downmixes to mono if needed (average channels)
   - Resamples to 16 kHz via `rubato::SincFixedIn`
   - Returns the mono-16kHz f32 buffer (for whisper-rs) OR wraps in WAV via `hound` (for Groq multipart)
3. 120 s hard cap — if buffer exceeds, auto-stop and proceed

Safety: all cpal callbacks wrap buffer writes in `try_lock` + log-and-drop on contention; never panic from audio thread.

## 9. Transcription engines

### 9.1 Groq

- `POST https://api.groq.com/openai/v1/audio/transcriptions`
- Multipart: `file=audio.wav`, `model=whisper-large-v3-turbo`, `response_format=json`, `language=en`
- Auth: `Authorization: Bearer <api_key>`
- Timeout: 30 s
- Errors surfaced as toast in main window + overlay snap back to idle

### 9.2 Local (whisper-rs)

- Model path resolved by single `model_path(size: ModelSize) -> PathBuf` function — used by both downloader and loader (known bug #2)
- Load: `WhisperContext::new_with_params(&model_path, ctx_params)` — cached in `OnceCell` keyed by model size
- Run: `state.full(params, &samples)` with `n_threads = num_cpus::get() - 1`, English mode, no-timestamps
- Returns concatenated segment text

## 10. Post-processing

Applied to both engines' output before pasting:

1. Trim leading/trailing whitespace
2. Remove Whisper artifacts: `[BLANK_AUDIO]`, `[MUSIC]`, `[SILENCE]`, `(sighs)`, parenthesized stage directions
3. Collapse multiple whitespace → single space
4. If the original first character was lowercase AND the cursor is likely at start of line (heuristic: previous char is `\n` or string is empty) → uppercase first letter. Actually — skip this for v1, cursor-position inspection is fragile across apps. Just return Whisper output as-is after artifact strip.

## 11. Auto-paste

1. `arboard::Clipboard::new()?.set_text(cleaned_text)`
2. Sleep 40 ms (clipboard propagation)
3. `enigo.key(Key::Meta, Direction::Press)` + `enigo.key(Key::Unicode('v'), Direction::Click)` + `enigo.key(Key::Meta, Direction::Release)` on Mac
4. On Windows: same with `Key::Control`
5. Clipboard is left holding the transcribed text — intentional, matches Whisper Flow (user can re-paste if needed)

## 12. Model download flow

1. User selects size from dropdown, clicks **Download**
2. Frontend invokes `download_model(size)` command
3. Backend:
   a. Streams `GET https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{size}.bin`
   b. Writes to `app_data_dir()/models/ggml-{size}.bin.partial`
   c. Emits `model-download-progress` event every 250 ms: `{ size, bytes_done, bytes_total, percent }`
   d. On complete: rename `.partial` → final, emit `model-download-complete`
   e. On error: delete partial, emit `model-download-error`
4. Frontend updates progress bar from event stream
5. On app startup: scan models dir, populate `downloaded_models` setting — source of truth

## 13. Permissions

### macOS
- `NSMicrophoneUsageDescription = "Typr needs the microphone to transcribe your voice."` in `src-tauri/Info.plist` (known bug #7)
- Accessibility permission requested on first hotkey register — macOS will prompt automatically when the global shortcut API is first called; the app shows a modal explaining why
- Hardened runtime entitlements set for dev + prod

### Windows
- No special manifest needed; mic + global hotkey work without UAC
- Defender SmartScreen warning on first run — expected for unsigned builds, note in README

## 14. Bug-prevention map (1:1 with YouTube demo issues)

| # | Bug | Preemption |
|---|---|---|
| 1 | Sample rate mismatch | Detect native SR in `start_recording`, resample via rubato in `stop_recording`. Never assume 16 kHz. |
| 2 | "Fail to run whisper: no such file" | Single `model_path(size)` helper used by downloader AND loader. No two places allowed to build model paths. |
| 3 | Window not draggable | `decorations: false` + `<div data-tauri-drag-region>` across top 48 px + `dragDropEnabled: true` in tauri.conf.json. |
| 4 | Overlay picks up voice when idle | Recorder state machine with exactly two states (Idle, Recording). Transition to Idle drops the cpal stream via `drop(self.stream.take())`. No "paused" state. |
| 5 | Overlay square background | Overlay window `transparent: true`, body CSS `background: transparent`, only circle element has background. |
| 6 | Hotkey does nothing on first launch | Register in `setup()` hook, inside `tauri::async_runtime::spawn(async move { ... })`, after `app.ready()`. On Mac, surface accessibility prompt proactively. |
| 7 | Crash on record start (Mac) | `NSMicrophoneUsageDescription` in Info.plist, entitlements set for dev. Document first-launch permission grant in README. |

## 15. Testing

### Manual acceptance (done after each phase)
Phase-level verification checks are listed in `docs/plans/typr-implementation-plan.md`.

### v1 final acceptance
Run through `POST-BUILD CHECKLIST` from user's original plan doc. All items must pass.

### Automated
- No test suite in v1. Personal tool, fast iteration > coverage.
- `cargo check` + `cargo clippy` must pass on commit.
- `npm run build` must succeed.

## 16. Open questions for Rajat

None blocking. Nominal defaults chosen. Flag any of the "Decisions I made" (§4.3) you want to change.

---
