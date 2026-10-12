# Build Phases — Meeting Copilot & Screen-Region Assistant Overlay

This plan builds the product incrementally. Each phase is independently
testable and ends with a working, demonstrable result. Feature A (screenshot
→ OCR → OpenAI → overlay) is built first because it is simpler and exercises
the full backend ↔ overlay ↔ OpenAI pipeline. Feature C (gallery + answer
caching) layers on the data model. Feature B (dual-audio copilot) builds on
that foundation. The whole thing is collapsed into one installable background
app in the packaging phase.

**Deployment model (resolved):** overlay (Electron) + backend (Python) run on
the **same machine over localhost**. During development they run **separately**
(`npm start` + `python server.py`); they are collapsed into a single installable
app only at packaging time (Phase 9).

Legend: **[BE]** backend/Python, **[OV]** overlay/Electron, **[INFRA]** setup.

---

## Phase 0 — Foundation & cleanup

Goal: get both existing apps running cleanly on one machine and fix the known
rough edges, so later phases build on solid ground.

- **[INFRA]** Document and verify local run: Python server + Electron overlay
  on the same machine over `localhost`.
- **[OV]** Replace hardcoded `http://192.168.0.102:3000` with a configurable
  host/port (default `localhost`).
- **[OV]** Fix the `fs` bug in `main.js` (import `fs`, or remove unused
  transcript handler for now).
- **[BE]** Fix `requirements.txt` to include actually-used deps (`easyocr`,
  `numpy`; and `paddleocr`, `opencv-python` if PaddleOCR is used).
- **[BE]** Reconcile port: pick one (e.g. 3000) and make README consistent.
- **[INFRA]** Add `.env` support for the OpenAI key (server-side), and
  document required macOS permissions (Mic, Accessibility, Screen Recording).

Exit criteria: overlay loads from localhost; both apps start without errors;
API key loads from env.

---

## Phase 1 — Backend OpenAI plumbing (text in → answer out)

Goal: a backend endpoint that takes text and returns an OpenAI answer.

- **[BE]** Add OpenAI SDK; read key from env var.
- **[BE]** Add `POST /api/ask` (text → prompt → OpenAI → answer). Support
  streaming response.
- **[BE]** Add a system prompt template suited to "answer this question /
  content" use.
- **[BE]** Basic error handling (missing key, API error, timeouts).

Exit criteria: calling `/api/ask` with sample text returns a sensible answer;
streaming works.

---

## Phase 1b — Data layer (SQLite records + caching)

Goal: a portable datastore that holds answer records and enables caching.

- **[BE]** Add a **SQLite** DB (`sqlite3` stdlib, no install). Create the
  `records` table per the data model: id, created_at, source_type, input_ref,
  extracted_text, answer, status.
- **[BE]** Enable **WAL mode**. DB file in the project folder for dev (per-user
  app-data location is set at packaging time).
- **[BE]** Keep **images on disk** (existing `screenshots/YYYY-MM-DD/`); store
  only the path in the DB.
- **[BE]** Add record endpoints: list records (gallery), get one record
  (returns cached answer if present), create a record on capture, update with
  answer, delete, and force re-run.
- **[BE]** Caching rule: on get, if `status == answered` return stored answer
  (no OCR, no OpenAI); if `captured`, pipeline runs and stores result.
- **[BE]** Retention/cleanup hooks: auto-delete records older than N days +
  manual "clear history" (bounds DB growth; images on disk cleaned alongside).
- Note: storage is **SQLite, not per-answer JSON files** (small text only;
  PNGs stay on disk).

Exit criteria: records persist across restarts; a record with an answer is
returned from the DB without any reprocessing.

---

## Phase 2 — Feature A: screenshot (full + region) → OCR → OpenAI → overlay

Goal: full first feature end-to-end, writing to the data layer.

- **[OV]** Register **two global shortcuts**: full-screen capture and region
  (drag-selection) capture.
- **[OV]** Build a transparent, full-screen, always-on-top, content-protected
  **selection window**; user drags a rectangle; capture coordinates via IPC.
- **[OV]** Capture full screen or the selected region (via `desktopCapturer`
  + crop), handling Retina scale factor; exclude overlay/selection window from
  capture; save PNG to disk.
- **[BE]** On capture, create a `records` row (`status = captured`).
- **[BE]** Add `POST /api/solve` (record/image → OCR → OpenAI → answer),
  reusing `/api/ask` after OCR, and **write the answer back to the record**
  (`status = answered`).
- **[BE]** Wire OCR engine selection (easyocr baseline; option to use
  `OCR.py` `SmartQuestionOCR`).
- **[OV]** Trigger solve; render the streamed answer in the overlay.

Exit criteria: user captures full screen or a region, the OpenAI answer appears
on the overlay (invisible to screen share), and the result is stored as a
record.

---

## Phase 2b — Feature C: gallery & answer caching

Goal: browse past captures and reuse cached answers.

- **[OV]** Add the **Gallery view (S2)** inside the overlay: records newest
  first, grouped by day, with thumbnails and an answered/not-yet badge.
- **[OV]** Click an **answered** record → open Answer view, show cached answer
  instantly (cache hit, no reprocessing).
- **[OV]** Click a **not-yet-answered** record → run the pipeline once, flip
  the badge to answered.
- **[OV]** Delete and force-re-run actions on records.

Exit criteria: previously answered captures open instantly with no repeat OCR
or OpenAI call; unanswered ones process on demand and are then cached.

---

## Phase 3 — Overlay UI/UX redesign (shared surface)

Goal: the overlay becomes the polished, glanceable surface all features use,
with the four view states.

- **[OV]** Switch overlay to load local `index.html` (`loadFile`) instead of
  remote URL.
- **[OV]** Implement the four view states: **S0** floating dot, **S1** answer
  view (hero streamed answer + collapsible source text + actions), **S2**
  gallery (from Phase 2b), **S3** audio/live copilot (built out in Phase 6).
- **[OV]** In-overlay nav (Answer / Gallery / Audio) + automatic transition
  (capture → S1 "thinking" → streamed answer).
- **[OV]** Status states: idle / listening / thinking; immediate "thinking…"
  feedback.
- **[OV]** Keep/polish minimize-to-dot; add global shortcut to hide/show the
  whole overlay.
- **[OV]** Tone selector (concise / detailed / professional / casual) wired
  to backend prompts.

Exit criteria: Feature A/C render in the new multi-state UI; overlay is
discreet, glanceable, and controllable via hotkeys.

---

## Phase 4 — Audio capture foundation (mic + system audio)

Goal: reliably capture both audio streams on macOS.

- **[INFRA]** Install/configure BlackHole; set up a Multi-Output Device so the
  user still hears the call while system audio is captured.
- **[OV]** Capture microphone via `getUserMedia` ("Me").
- **[OV]** Capture system audio via the BlackHole input device ("Them").
- **[OV]** Verify both streams independently (levels/VU feedback in a debug
  view).

Exit criteria: both audio streams are captured simultaneously and
distinguishable; user still hears the meeting.

---

## Phase 5 — Real-time transcription (streaming STT)

Goal: both streams transcribed live, tagged by speaker.

- **[BE]** Add WebSocket channel for audio in / transcript out.
- **[BE]** Integrate STT: **OpenAI `gpt-4o-mini-transcribe`** primary, **local
  Whisper (`faster-whisper`)** as zero-cost fallback. Run **two sessions**, one
  per source stream (mic = "Me", system = "Them") — **no diarization**.
- **[BE]** Tag each transcript line by **source** (not AI guess); maintain
  rolling context. Default: "Them" continuous, "Me" on demand; voice-activity
  gating to skip silence (cost control).
- **[OV]** Stream audio chunks to backend over WebSocket.
- **[OV]** Render live Me/Them transcript (color-coded) in the transcript
  zone.
- **[BE]** Auto-reconnect STT on transient failures.

Exit criteria: speaking into mic and playing system audio both produce
accurate, speaker-tagged live transcript on the overlay.

---

## Phase 6 — Feature B: suggestion generation ("what should I say")

Goal: the meeting copilot produces reply suggestions.

- **[BE]** Build the coach system prompt (given dialogue, suggest a concise
  natural reply); use rolling context.
- **[BE]** Two trigger modes: automatic on "Them" silence; on-demand via
  hotkey. Debounce/throttle to control cost.
- **[BE]** Stream 1–3 short suggestions back over WebSocket.
- **[OV]** Render streamed suggestions in the hero zone; on-demand hotkey;
  "regenerate" / "more detail" affordances; apply tone selection.
- **[BE]** Store audio-derived answers as `records` (`source_type = audio`,
  transcript snippet as `input_ref`) so they appear in the same gallery.

Exit criteria: during a live call, when the other person stops talking (or on
hotkey), relevant ready-to-say suggestions appear quickly on the overlay, and
audio answers are browsable in the gallery alongside screenshots.

---

## Phase 7 — Hardening, privacy, polish

Goal: production readiness.

- **[OV/BE]** One-time consent notice; **raw live transcript in-memory-only by
  default** with an optional "save transcript" toggle; answers/suggestions
  stay persisted (caching). Retention/cleanup: auto-delete records older than
  N days + manual "clear history".
- **[INFRA]** Onboarding flow for macOS permissions (Mic, Accessibility,
  Screen Recording) and Windows (mic + AV-exclusion note).
- **[BE]** Cost controls: transcribe "Them" continuously but gate LLM calls;
  configurable limits.
- **[BE/OV]** Error states, reconnection UX, latency tuning.
- **[OV]** Position memory, theming/readability pass, keyboard-only operation.

Exit criteria: app is discreet, stable over long sessions, respects
permissions/consent, and controls cost.

---

## Phase 8 — Production system audio (remove setup friction)

Goal: replace BlackHole with a native path.

- **[INFRA/BE]** Build a ScreenCaptureKit native helper (macOS 13+) to capture
  system audio without a virtual device.
- **[OV]** Swap the audio source from BlackHole to the native helper.
- **[INFRA]** Windows path via WASAPI loopback.

Exit criteria: system-audio capture works with no manual audio-device setup by
the user.

---

## Phase 9 — Packaging: single installable background app

Goal: collapse the two processes into one installable app that runs in the
background. (Can start in parallel with Phase 7 hardening.)

- **[BE]** Freeze the Python backend with **PyInstaller** into a standalone
  binary (bundles deps + SQLite; no user Python needed).
- **[OV]** Electron **spawns the frozen backend as a hidden child** on launch,
  waits for a readiness signal (show "starting…"), and stops it on quit.
- **[INFRA]** Set the DB + data location to the per-user **app-data directory**
  for the packaged build.
- **[INFRA]** Package with **electron-builder** → macOS `.dmg`/`.app` (macOS
  13+), Windows `.exe` (Windows 10+). Bundle the frozen binary as an extra
  resource. (Windows 7 is best-effort/unsupported — see NFR-6.)
- **[OV]** Background/tray operation: menu-bar/tray presence + floating dot;
  optional **launch-at-login** toggle (replaces the launchd/systemd/Task
  Scheduler scripts for the packaged build).
- **[INFRA]** macOS **code-signing + notarization** (Developer ID) for real
  distribution; address app-size (PK-7) — decide single vs lighter OCR engine
  or API-based OCR.

Exit criteria: a user installs one artifact, launches one icon, and the app
runs in the background with no visible terminals or separate processes.

---

## Dependency / ordering notes

- Feature A (Phases 1, 1b, 2) + caching (2b) + the UI (Phase 3) are
  prerequisites for a usable shared overlay before audio work begins.
- Phase 1b (data layer) must precede Phase 2 (records written on capture) and
  Phase 2b (gallery/caching reads records).
- Phase 4 (capture) must precede Phase 5 (transcription), which must precede
  Phase 6 (suggestions).
- Phase 8 can be deferred; BlackHole (Phase 4) is sufficient for a working
  product and demos.
- Phase 9 (packaging) is best done late (needs the app feature-complete) but
  can begin in parallel with Phase 7. During all earlier phases, Electron and
  Python run **separately** for fast iteration.
- **OQ-1 and OQ-2 are resolved.** OQ-1: same machine / localhost. OQ-2: OpenAI
  `gpt-4o-mini-transcribe` with local Whisper fallback, speaker-by-source (no
  diarization).
