# Requirements — Meeting Copilot & Screen-Region Assistant Overlay

## 1. Overview

A desktop assistant for online meetings and screen-based tasks. It ships as a
single installable app and runs quietly in the background. It has three core
capabilities that feed into one always-on-top overlay that is invisible to
screen sharing:

1. **Screenshot (full or region) → OCR → OpenAI → Overlay.** The user captures
   the screen via a global hotkey — either full-screen or a drag-selected
   region. The capture is OCR'd, the text is sent to OpenAI, and the answer is
   displayed on the overlay.
2. **Gallery of past captures with cached answers.** The overlay lets the user
   browse previous captures. Each capture is a stored record. If its answer was
   already fetched, clicking it shows the cached answer instantly — no repeat
   OCR and no repeat OpenAI call. If no answer exists yet, clicking it runs the
   OCR → OpenAI pipeline once and stores the result.
3. **Dual-audio meeting copilot.** The app listens to both the user's
   microphone ("Me") and the system/output audio ("Them"), transcribes both
   in real time, sends the conversation context to OpenAI, and shows
   suggested replies ("what should I say") on the overlay.

The product goal: help a user in a live online meeting who is unsure what to
say or how to respond, and help answer on-screen questions/content, without
the other participants seeing the assistance.

## 1a. Deployment model (resolved)

- The overlay (Electron) and backend (Python) run on the **same machine**,
  communicating over **localhost**. This is the only supported model for the
  core product; it keeps networking simple and fast, keeps screen/audio capture
  native in Electron, and makes screen-share invisibility coherent (the overlay
  sits on the same screen being shared).
- An **optional phone/second-screen read-only view** (backend also pushes
  answers/suggestions to a phone web page) is a possible **future enhancement**,
  not part of the core architecture.
- The product ships as **one installable application**: an Electron app that
  spawns the Python backend as a hidden background child process and manages its
  lifecycle. The user installs and launches one icon; no terminals, no separate
  processes visible. See §10 (Packaging & distribution).

## 2. Actors

- **User** — the meeting participant running the app.
- **OpenAI** — provides transcription (optional) and reply/answer generation.
- **Overlay** — the Electron window the user reads from.
- **Backend** — the Python service that performs OCR, calls OpenAI, and
  coordinates data to the overlay.

## 3. System components (existing + new)

### Existing
- `screen_shot/` (Python): `daemon.py` (global hotkey screenshot capture),
  `server.py` (Flask gallery + `/api/ocr` via easyocr + `/typings` SSE page),
  `OCR.py` (standalone PaddleOCR `SmartQuestionOCR` question/option detector,
  not currently wired into the server), `config.json`.
- `Overlay_Experiment/my-overlay-app/` (Electron): `main.js` (frameless,
  transparent, always-on-top window with `setContentProtection(true)`,
  currently loads a remote `/typings` URL), `preload.js`, `index.html`
  (local speech-transcription UI using webkitSpeechRecognition, not currently
  loaded).

### New / to be built
- Backend API endpoints for capture-solve, record listing/fetch (cache), and
  audio-copilot.
- OpenAI integration (server-side).
- Full-screen and region-selection capture flow in Electron (global hotkeys).
- SQLite data layer (records + cached answers; images on disk).
- WebSocket transport for live audio + streamed suggestions.
- Redesigned overlay UI with four view states (dot / answer / gallery / audio).
- System-audio capture path (BlackHole first, ScreenCaptureKit later).
- Single-app packaging: Electron spawns a PyInstaller-frozen Python backend;
  electron-builder installer; background/tray operation.

## 4. Functional requirements

### 4.1 Screenshot → OCR → OpenAI → Overlay (Feature A)

- **FR-A1** User can trigger capture via global shortcuts from any app:
  **full-screen capture** and **region (drag-selection) capture** on separate
  hotkeys.
- **FR-A2** For region capture, a transparent full-screen selection layer lets
  the user drag a rectangle; the selected coordinates are captured.
- **FR-A3** The capture is taken at full (physical) resolution, correctly
  accounting for display scale factor (Retina).
- **FR-A4** The captured image is saved to disk and recorded in the DB (see
  §11), then sent to the backend for processing.
- **FR-A5** The backend runs OCR on the image and extracts text.
- **FR-A6** The backend sends the extracted text (with an appropriate prompt)
  to OpenAI and receives an answer.
- **FR-A7** The answer is displayed in the overlay's answer zone, streamed.
- **FR-A8** The selection layer and overlay must not appear in the captured
  image (self-capture exclusion).
- **FR-A9** OCR engine is configurable: easyocr (baseline) or PaddleOCR
  (`OCR.py` `SmartQuestionOCR`, preferred for quiz/question content).
- **FR-A10** The OCR text and OpenAI answer are stored on the capture's record
  so they can be shown later without reprocessing (see Feature C).

### 4.1b Gallery & answer caching (Feature C)

- **FR-C1** The overlay provides a gallery of past captures, newest first,
  grouped by day (evolves the existing Flask gallery into the overlay).
- **FR-C2** Each gallery item shows a thumbnail (screenshots) or a transcript
  snippet (audio records) and a status badge: answered vs not-yet-answered.
- **FR-C3** Clicking an **answered** item shows the stored answer instantly,
  with **no OCR and no OpenAI call** (cache hit).
- **FR-C4** Clicking a **not-yet-answered** item runs the OCR → OpenAI pipeline
  once, stores the answer on the record, and flips its badge to answered.
- **FR-C5** Gallery items support delete and re-run (force reprocess) actions.
- **FR-C6** Audio-derived answers are also recorded and browsable in the same
  gallery (unified record list across sources).

### 4.2 Dual-audio meeting copilot (Feature B)

- **FR-B1** App captures the user's microphone audio ("Me").
- **FR-B2** App captures system/output audio ("Them") — the other
  participant's voice coming through the speakers.
- **FR-B3** Both streams are transcribed in real time, each line tagged with
  its speaker **by source** (mic = "Me", system audio = "Them") — no
  diarization. Default: "Them" transcribed continuously, "Me" on demand;
  voice-activity gating avoids transcribing silence.
- **FR-B4** Live transcript (Me/Them, color-coded) is shown in the overlay.
- **FR-B5** A rolling conversation context (last N turns) is maintained.
- **FR-B6** Suggestions are generated by OpenAI in two trigger modes:
  - **Automatic** — when "Them" stops speaking (silence detection).
  - **On-demand** — when the user presses a global hotkey.
- **FR-B7** 1–3 concise, ready-to-say suggestions are shown in the overlay
  suggestion zone, streamed token-by-token.
- **FR-B8** User can select suggestion tone (concise / detailed /
  professional / casual).
- **FR-B9** User can start/stop capture and choose sources (Me / Them / Both).

### 4.3 Overlay (shared)

- **FR-O1** Overlay is always-on-top, frameless, transparent, draggable.
- **FR-O2** Overlay is hidden from screen sharing / recording via
  `setContentProtection(true)`.
- **FR-O3** Overlay can minimize to a small floating dot and re-expand.
- **FR-O4** Overlay can be instantly hidden/shown via a global shortcut.
- **FR-O5** Overlay shows a clear status (listening / thinking / idle).
- **FR-O6** Answer/suggestion content is large, high-contrast, glanceable, with
  limited text per item; secondary content (raw OCR/transcript) is collapsible.
- **FR-O7** The overlay has four view states the user navigates between:
  - **S0 — Floating dot:** minimized/idle resting state.
  - **S1 — Answer view (default expanded):** hero answer zone (streamed),
    collapsible source-text zone, actions (regenerate / more detail / copy).
  - **S2 — Gallery view:** scrollable records grouped by day with
    answered/not-yet badges (Feature C). Clicking a record opens S1.
  - **S3 — Audio/live copilot view:** hero suggestion zone (1–3 streamed
    replies, tone selector, regenerate), secondary live Me/Them transcript.
- **FR-O8** Navigation is available via global hotkeys (capture-full,
  capture-region, ask-now, hide/show), in-overlay nav (Answer / Gallery /
  Audio), and automatic transitions (a capture auto-opens S1 in "thinking"
  state, then fills with the streamed answer).

### 4.4 Backend / integration

- **FR-I1** OpenAI API key is read from an environment variable, server-side
  only. It is never present in the Electron renderer or any committed file.
- **FR-I2** Backend exposes an endpoint to solve a capture image
  (image → OCR → OpenAI → text), writing the result to the capture's record.
- **FR-I3** Backend exposes a WebSocket channel for live audio in and
  transcript/suggestion out.
- **FR-I4** Overlay and backend communicate over localhost by default
  (configurable host/port); no hardcoded LAN IP.
- **FR-I5** Backend exposes endpoints to list records (gallery), fetch a single
  record's stored answer (cache hit, no reprocessing), and force a re-run.
- **FR-I6** The backend is spawned and lifecycle-managed by the Electron app as
  a hidden child process (started on app launch, stopped on quit); it signals
  readiness so the overlay can show a "starting…" state until the backend is
  up.

## 5. Non-functional requirements

- **NFR-1 Latency.** Suggestion text should begin appearing within ~2s of
  trigger; use streaming so partial text shows immediately.
- **NFR-2 Discretion.** Overlay default position is a screen corner, dim and
  compact; invisible to screen share at all times.
- **NFR-3 Privacy & consent (OQ-3 resolved).** The app records meeting audio.
  Policy:
  - **Answers/suggestions are persisted** as records in SQLite (required for
    the caching behavior — Feature C).
  - **The full raw live transcript is NOT persisted by default** — it is held
    in memory during a call and discarded when the call ends. An optional
    "save transcript" toggle lets the user opt in to persisting it.
  - A **one-time consent notice** is shown informing the user the app listens
    to meeting audio. Recording laws vary (one-party vs two-party consent) by
    jurisdiction.
- **NFR-4 Security.** API keys stay server-side (env var). Treat all captured
  content and external responses as sensitive.
- **NFR-5 Cost control.** Avoid transcribing/LLM-calling on every utterance;
  prefer on-silence or on-demand triggers; keep suggestions short.
  Transcription reference cost: ~$0.003/min (`gpt-4o-mini-transcribe`), i.e.
  roughly $0.35–$0.70 per hour with both streams at higher-tier rates; reduced
  by transcribing only "Them" continuously + voice-activity gating, or
  eliminated entirely by the local Whisper fallback.
- **NFR-6 Platform targets (OQ-4 resolved).**
  - **macOS 13+** (Ventura and later). This also satisfies ScreenCaptureKit's
    macOS 13+ requirement for the production system-audio path.
  - **Windows 10+** is the realistic supported floor (modern Electron, Python,
    and WASAPI loopback audio require it). **Windows 7 is requested but is
    best-effort / effectively unsupported:** it is end-of-life (no security
    updates since Jan 2020), and current Electron/Python/Chromium and the audio
    APIs we rely on do not reliably run on it. We will not block the design on
    Windows 7; if it happens to work, good, but it is not a tested target.
  - Linux kept in mind (X11 works; Wayland needs XCB) but not a primary target.
- **NFR-7 Permissions.** macOS requires Microphone, Accessibility (global
  hotkeys), and Screen Recording (ScreenCaptureKit) permissions; onboarding
  must request these clearly. Windows: microphone permission; AV may flag the
  global key listener (document an exclusion).
- **NFR-8 Reliability.** Continuous audio sessions must auto-reconnect STT and
  recover from transient network errors without crashing.

## 6. Key technical decisions (chosen defaults)

- **System audio capture:** BlackHole virtual device for the prototype;
  ScreenCaptureKit native helper for production (removes user audio-routing
  setup). Windows uses WASAPI loopback.
- **Transcription (OQ-2 resolved):** **OpenAI transcription**, model
  `gpt-4o-mini-transcribe` (~$0.003/min). **Local Whisper (`faster-whisper`)**
  is the zero-cost fallback. **No diarization is purchased or needed** — speaker
  identity comes from the capture *source* (mic = "Me", system audio = "Them"),
  captured as two separate labeled streams. To control cost: transcribe "Them"
  continuously, "Me" on demand, with voice-activity gating (don't send silence).
  Headphones (or echo cancellation) prevent mic/speaker bleed.
- **Suggestion generation:** OpenAI, called from the Python backend.
- **Transport:** WebSockets between Electron and Python for live audio +
  streamed suggestions (SSE is retained only for the existing `/typings`
  demo path).
- **OCR:** easyocr baseline, PaddleOCR (`OCR.py`) preferred for
  question/option-heavy content.
- **Overlay loading:** load local `index.html` (`loadFile`) and render
  answers locally, rather than the remote `/typings` URL.

## 7. Out of scope (initial)

- Meeting-platform-specific bots/SDKs (Zoom SDK, Teams bot, etc.).
- Multi-user / cloud-hosted deployment.
- Mobile clients.
- Fine-tuned or self-hosted LLMs.

## 8. Open questions

- **OQ-1 — RESOLVED.** Overlay and backend run on the **same machine** over
  **localhost**, packaged as one installable app (Electron spawns the Python
  backend as a hidden child). An optional phone/second-screen read-only view is
  a future enhancement only.
- **OQ-2 — RESOLVED.** OpenAI transcription (`gpt-4o-mini-transcribe`) with
  local Whisper (`faster-whisper`) as the zero-cost fallback. No diarization;
  speaker identity is by capture source (two labeled streams). Cost controlled
  by transcribing "Them" continuously, "Me" on demand, + voice-activity gating.
- **OQ-3 — RESOLVED.** Answers/suggestions persist in SQLite (for caching);
  the raw live transcript is in-memory-only by default with an optional save
  toggle; a one-time consent notice is shown. Storage stays SQLite (not JSON);
  growth bounded by a retention/cleanup policy (DS-8).
- **OQ-4 — RESOLVED.** Targets: macOS 13+ and Windows 10+ (Windows 7 is
  best-effort/unsupported — EOL and incompatible with the modern stack).

## 9. Known issues in current code (to address when touched)

- `my-overlay-app/main.js` uses `fs` in the `save-transcript` IPC handler but
  never imports it — will throw when triggered.
- `my-overlay-app/main.js` hardcodes `http://192.168.0.102:3000/typings`.
- `screen_shot/requirements.txt` does not list `easyocr`, `numpy` (used by
  `server.py`) or `paddleocr`, `opencv-python` (used by `OCR.py`).
- `server.py` default port is 3000, but README and docstrings say 5000.

## 10. Packaging & distribution

- **PK-1** Ship as a **single installable Electron app** (macOS `.dmg`/`.app`,
  Windows `.exe`) built with **electron-builder**.
- **PK-2** The **Python backend is frozen with PyInstaller** into a standalone
  binary (no user Python install required) and bundled inside the app as an
  extra resource. SQLite ships for free as part of Python's stdlib.
- **PK-3** Electron **spawns the frozen backend as a hidden/detached child**
  on launch (no console window) and terminates it on quit.
- **PK-4** The app runs in the **background**: menu-bar/system-tray presence
  plus the minimizable floating dot; optional "launch at login" toggle via
  Electron's built-in setting (replacing the launchd/systemd/Task Scheduler
  scripts for the packaged build).
- **PK-5** During development, Electron and Python run **separately**
  (`npm start` + `python server.py`) for fast iteration; bundling happens only
  at packaging time (hardening phase).
- **PK-6** For real distribution on macOS, the app must be **code-signed and
  notarized** (Apple Developer ID) because it uses Screen Recording, Microphone,
  Accessibility, and a global key listener. Unsigned is acceptable for local
  development only.
- **PK-7** App size is a known concern: easyocr/PaddleOCR pull heavy ML deps
  (PyTorch/Paddle), so the frozen binary may be several hundred MB to ~1 GB.
  Mitigations to decide: ship a single OCR engine, a lighter OCR, or move OCR
  to an API.
- **PK-8** On first run, Electron shows a "starting…" state until the backend
  signals ready (freezing + first ML model load adds startup latency).

## 11. Data storage

- **DS-1** Use **SQLite** as the datastore — zero install, zero server, a
  single portable `.db` file, and part of Python's stdlib (`sqlite3`). The user
  never installs or runs a database.
- **DS-2** **Split storage:** SQLite holds metadata + text (records, OCR text,
  answers, status, timestamps, image path); the **actual images stay as PNG
  files on disk** in the existing `screenshots/YYYY-MM-DD/` structure. The DB
  references images by path (no large blobs in the DB).
- **DS-3** Enable **WAL mode** for smooth concurrent reads alongside writes.
- **DS-4** DB file location: project folder during development; the OS per-user
  app-data directory (e.g. `~/Library/Application Support/<app>` on macOS) in
  the packaged build, so it survives updates/reinstalls.
- **DS-5** The DB is local and unencrypted by default (acceptable for a personal
  tool); optional encryption is a possible later enhancement given the
  privacy/consent note (NFR-3).
- **DS-6** Not for multi-user/cloud; migrating to Postgres is only relevant if
  the out-of-scope multi-user direction is ever pursued.
- **DS-7** **SQLite is used, not per-answer JSON files.** Rationale: the heavy
  data (PNGs) already lives on disk, so the DB only holds small text and stays
  small; SQLite gives instant id lookups (the cache), gallery filtering, and
  safe writes that JSON files do not. Growth is managed by a retention policy
  (DS-8), not by changing storage format.
- **DS-8** **Retention / cleanup policy:** support auto-delete of records older
  than N days and a manual "clear history" action, to bound long-term growth.

### 11a. Record (answer) data model

Each answer — whether from a screenshot or from audio — is one record:

- **id** — unique identifier.
- **created_at** — timestamp.
- **source_type** — `screenshot-full` | `screenshot-region` | `audio`.
- **input_ref** — image path (screenshots) or transcript snippet (audio).
- **extracted_text** — OCR output or transcript text.
- **answer** — the OpenAI answer (null until fetched).
- **status** — `captured` | `processing` | `answered` | `error`.

Caching rule (Feature C): on open, if `status == answered`, show `answer`
directly (no OCR, no OpenAI); if `captured`, run the pipeline once, store the
`answer`, and set `status = answered`.
