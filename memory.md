# Project Memory — Meeting Copilot & Screen-Region Assistant Overlay

> Living context document. Update it as decisions change and phases complete.
> Companion docs: `requirements.md` (what to build), `phases.md` (build order).

## Product summary

A discreet desktop assistant for online meetings and on-screen tasks. Ships as
**one installable background app**. Three features feed one always-on-top
overlay that is invisible to screen sharing:

1. **Feature A — Screenshot (full or region) → OCR → OpenAI → Overlay.** Global
   hotkey captures full-screen or a drag-selected region → OCR → OpenAI →
   answer shown on overlay. Each capture is saved as a record.
2. **Feature C — Gallery + answer caching.** Browse past captures in the
   overlay. Answered records open instantly from storage (no repeat OCR/OpenAI);
   unanswered ones run the pipeline once, then cache.
3. **Feature B — Dual-audio meeting copilot.** Listen to mic ("Me") and
   system audio ("Them") → transcribe live → OpenAI suggests "what should I
   say" → shown on overlay. Audio answers are also stored as records.

Target user: someone in a live online meeting who is unsure what to say, or
who needs help answering on-screen content, without others noticing.

## Repositories / locations

- **Backend (Python):** `/Users/pranayharkulkar/Desktop/pranay/Job_Hunt/screen_shot`
- **Overlay (Electron):** `/Users/pranayharkulkar/Desktop/pranay/Job_Hunt/Overlay_Experiment/my-overlay-app`
- Both are sibling folders under `.../Job_Hunt`.

## Existing code — what it does today

### screen_shot (Python)
- `daemon.py` — global hotkey listener (pynput). Default trigger `C` x4 within
  2s captures a full-screen PNG into `screenshots/YYYY-MM-DD/`. `Q` x4 quits.
  Captures via `mss` (macOS/Linux) / Pillow ImageGrab (Windows).
- `server.py` — Flask app. **Default port 3000, binds 0.0.0.0.** Serves:
  - `/` gallery, `/img`, `/thumb`, `/api/delete`, `/api/versions`,
    `/api/save-edit` (canvas crop/draw).
  - `/api/ocr` — OCR via **easyocr** (`reader = easyocr.Reader(['en'], gpu=False)`).
  - `/typings` + `/typings/stream` (SSE) + `/typings/update` — live-typing
    page broadcast via Server-Sent Events.
- `OCR.py` — standalone `SmartQuestionOCR` using **PaddleOCR**. Detects quiz
  questions + answer options with layout heuristics. **Not imported by
  server.py.** Better than easyocr for question/option content.
- `config.json` — outputDir, hotkeyChar=C, pressCount=4, maxIntervalMs=2000,
  logFile, logLevel.
- `run.sh` / `run.bat` — launch daemon + server together. Only check for
  pynput + flask (not easyocr/paddleocr).

### my-overlay-app (Electron)
- `main.js` — frameless, transparent, always-on-top (`screen-saver` level),
  pinned to all workspaces, `setContentProtection(true)` (hidden from screen
  share). Currently `loadURL('http://192.168.0.102:3000/typings')`. Has IPC
  for `toggle-overlay-mode` and `save-transcript`.
- `preload.js` — exposes `electronAPI.toggleOverlayMode`,
  `electronAPI.saveTranscript`.
- `index.html` — local UI with webkitSpeechRecognition speech transcription
  + minimize-to-dot. **Not currently loaded** (main.js loads the remote URL).
- `package.json` — `start: electron .`.

## Current integration seam

The overlay already projects the Flask `/typings` SSE page over HTTP. That
SSE push model is the proof-of-concept link between the two apps. We are
evolving this into: Electron as controller (capture + UI), Python as the
OCR/OpenAI service, with WebSockets for live audio.

## Architecture decisions (chosen)

- **Deployment: same machine, localhost (OQ-1 resolved).** Overlay (Electron)
  + backend (Python) run on one machine. Optional phone/second-screen
  read-only view is a *future* enhancement only.
- **Electron = controller/UI; Python = OCR + OpenAI service.** Region
  selection and screen/audio capture live in Electron (native strengths);
  OCR, OpenAI, STT coordination live in Python.
- **OpenAI key stays server-side** (env var in Python). Never in the Electron
  renderer or committed files.
- **Transport:** WebSockets for live audio + streamed suggestions. Existing
  SSE kept only for the `/typings` demo.
- **System audio capture:** BlackHole virtual device for prototype →
  ScreenCaptureKit native helper (macOS 13+) for production. Windows = WASAPI
  loopback.
- **Transcription (OQ-2 resolved):** OpenAI `gpt-4o-mini-transcribe`
  (~$0.003/min); local Whisper (`faster-whisper`) = zero-cost fallback.
  **No diarization** — speaker = capture source (mic "Me", system "Them"), two
  labeled streams. Cost control: "Them" continuous, "Me" on demand, +
  voice-activity gating. ~$0.35–$0.70/hr at higher rates with both streams;
  less with mini + gating; $0 with local Whisper. Headphones avoid mic bleed.
- **OCR:** easyocr baseline; PaddleOCR (`OCR.py`) preferred for
  question/option content.
- **Overlay loading:** switch to local `loadFile('index.html')` and render
  answers locally (removes hardcoded LAN IP dependency).

Rationale (why Electron owns region selection): it has `globalShortcut`,
`desktopCapturer`, `screen`, and can exclude its own windows from capture via
`setContentProtection`. Doing it from the Flask/browser side is clumsy and
can't coordinate with the always-on-top overlay.

## Data storage (chosen)

- **SQLite** (`sqlite3` stdlib) — zero install, zero server, one portable
  `.db` file; bundles for free when Python is frozen. **WAL mode** on.
- **Split storage:** DB holds metadata + text (records, OCR text, answers,
  status, timestamps, image path); **images stay as PNGs on disk** in the
  existing `screenshots/YYYY-MM-DD/` structure (DB references by path).
- **DB location:** project folder in dev; per-user app-data dir
  (`~/Library/Application Support/<app>`) in the packaged build.
- **Record model (one per answer, any source):** id, created_at, source_type
  (`screenshot-full` | `screenshot-region` | `audio`), input_ref (image path
  or transcript snippet), extracted_text, answer (null until fetched), status
  (`captured` | `processing` | `answered` | `error`).
- **Caching rule (Feature C):** on open, `answered` → show stored answer (no
  OCR/OpenAI); `captured` → run pipeline once, store answer, set `answered`.
- Local + unencrypted by default (fine for personal tool); optional encryption
  later. Not for multi-user/cloud (would need Postgres — out of scope).
- **SQLite, not per-answer JSON files** (decided). The "DB will get full" worry
  doesn't apply: PNGs live on disk, so the DB holds only small text. SQLite
  gives instant id lookups (cache), gallery queries, and safe writes; JSON
  files would be slower/riskier. Growth bounded by a **retention policy**
  (auto-delete older than N days + manual "clear history"), not by format.
- **Live transcript (OQ-3):** raw running Me/Them transcript is
  **in-memory-only by default**, discarded at call end; optional "save
  transcript" toggle to opt in. Answers/suggestions ARE persisted (caching).
  **One-time consent notice** on first use.

## Overlay view states (chosen)

- **S0 — Floating dot:** minimized/idle resting state.
- **S1 — Answer view (default):** hero streamed answer + collapsible source
  text + actions (regenerate / more detail / copy).
- **S2 — Gallery view:** records grouped by day with answered/not-yet badges
  (Feature C); click opens S1.
- **S3 — Audio/live copilot:** hero suggestions (1–3, streamed, tone selector)
  + secondary live Me/Them transcript.
- Navigation: global hotkeys (capture-full, capture-region, ask-now,
  hide/show) + in-overlay nav + automatic transition (capture → S1 "thinking"
  → streamed answer).

## Codebase vs app — what "clubbing together" means

- **Functional integration begins at Phase 2** (overlay captures → sends to
  Python backend → shows answer). From Phase 2 on they behave as one product
  but still **run as two separate processes** started manually during dev
  (`npm start` + `python server.py`), cooperating over localhost.
- **Physical packaging into one installable app is Phase 9.** One
  `.dmg`/`.exe`, one icon, Python spawned as a hidden child.
- The code stays **Python + JavaScript** internally — two languages can't
  literally merge. "Single app" = one deliverable, not one language.
- **Phase 9 folder layout (chosen — Option A):** consolidate into **one repo**
  with the **Electron app at the root** and the **Python backend under
  `backend/`** (e.g. `backend/server.py`, `backend/OCR.py`,
  `backend/requirements.txt`); electron-builder bundles the frozen backend.
  Until Phase 9 the two folders stay separate (current layout) for fast
  iteration — no consolidation before then.

## Packaging / distribution (chosen)

- **One installable Electron app** built with **electron-builder** (macOS
  `.dmg`/`.app`, Windows `.exe`).
- **Python backend frozen with PyInstaller** into a standalone binary, bundled
  inside the app; Electron **spawns it as a hidden child** on launch (readiness
  signal → "starting…" state), stops it on quit.
- **Background/tray** operation + floating dot; optional **launch-at-login**
  toggle (replaces launchd/systemd/Task Scheduler scripts for packaged build).
- **Dev runs separately** (`npm start` + `python server.py`); bundle only at
  packaging time (Phase 9).
- **Code-sign + notarize** (Apple Developer ID) required for real macOS
  distribution (screen/mic/accessibility/global-key usage).
- **App-size concern (PK-7):** easyocr/PaddleOCR pull heavy ML deps
  (several hundred MB–~1 GB frozen). Decide single/lighter OCR engine or
  API-based OCR.

## Known issues / tech debt (fix when touched)

- `main.js` uses `fs` in `save-transcript` but never imports it → will throw.
- `main.js` hardcodes `http://192.168.0.102:3000/typings` → make configurable
  (default localhost).
- `requirements.txt` missing `easyocr`, `numpy` (server.py) and `paddleocr`,
  `opencv-python` (OCR.py). Add `openai` when integrated.
- `server.py` default port 3000 vs README/docstrings saying 5000.
- Retina scale factor: region crop must multiply logical coords by display
  scale, else crop is wrong on macOS.

## Platform targets & permissions (OQ-4 resolved)

- **Targets:** **macOS 13+** (also satisfies ScreenCaptureKit's 13+ need) and
  **Windows 10+**. **Windows 7 is best-effort/unsupported** — EOL since Jan
  2020 and incompatible with modern Electron/Python/Chromium + the audio APIs;
  not a tested target, won't block the design.
- Global key listener (daemon / global shortcuts) needs **Accessibility**
  permission granted to the launching app (Terminal.app, not IDE terminal).
- Mic capture needs **Microphone** permission.
- ScreenCaptureKit (production system audio) needs **Screen Recording**
  permission and macOS 13+.
- BlackHole requires a **Multi-Output Device** so the user still hears the
  call while system audio is captured.
- Windows: mic permission; WASAPI loopback for system audio; AV may flag the
  global key listener (document an exclusion).

## Chosen defaults (minor decisions, changeable)

- **OpenAI key:** user has one; loaded from `.env` (`OPENAI_API_KEY`),
  server-side only. User will add it to `.env` later.
- **OCR engine:** **PaddleOCR** (`OCR.py` `SmartQuestionOCR`) as the default
  for quality on question/option content; easyocr remains available. App-size
  impact handled at packaging (PK-7).
- **LLM model:** **`gpt-4o-mini`** for both screenshot answers and meeting
  suggestions (cost/latency); upgradeable to `gpt-4o` later.
- **Screenshot prompt behavior:** **answer mode** by default (answer the
  on-screen question); explain/summarize modes may be added later as a
  selector.
- **Audio suggestions:** **1–3 short reply options** by default.
- **System audio (prototype):** **BlackHole** + Multi-Output Device; native
  ScreenCaptureKit later (Phase 8).
- **Global hotkeys:** sensible defaults chosen by implementer, **user-
  configurable** (capture-full, capture-region, ask-now, hide/show).
- **Standalone browser gallery:** **retired** once the gallery lives in the
  overlay (overlay-only).

## Open questions

- **OQ-1 — RESOLVED:** same machine / localhost; one installable app (Electron
  spawns hidden Python child). Optional phone second-screen = future only.
- **OQ-2 — RESOLVED:** OpenAI `gpt-4o-mini-transcribe` + local Whisper fallback;
  no diarization (speaker by capture source). See Architecture decisions.
- **OQ-3 — RESOLVED:** answers/suggestions persisted (caching); raw live
  transcript in-memory-only by default + optional save toggle; one-time consent
  notice; SQLite (not JSON) + retention policy. See Data storage.
- **OQ-4 — RESOLVED:** macOS 13+ and Windows 10+ (Windows 7 best-effort/
  unsupported). See Platform targets.

## Legal / ethical

Recording meeting audio has consent implications that vary by jurisdiction
(one-party vs two-party). The app needs a visible notice and an explicit
choice about transcript persistence.

## Backend files & endpoints (built Phase 1–2)

- `ai.py` — OpenAI helper: `ask()`, `ask_stream()`, `ANSWER_SYSTEM_PROMPT`,
  `AIError`, `is_configured()`. Model via `OPENAI_CHAT_MODEL` (default
  gpt-4o-mini).
- `db.py` — SQLite data layer. `records` table (id, created_at, source_type,
  input_ref, extracted_text, answer, status), WAL. CRUD + `has_answer()`
  (cache), `delete_older_than()`, `clear_all()`. DB at `APP_DB_PATH`
  (default `app.db` in project root; set to app-data dir when packaged).
  `source_type` now includes **'manual'** (typed question, no capture).
  Second table **`answer_history`** (id, record_id, question, answer,
  created_at): every Ask appends a row; `add_history`/`get_history`
  (newest-first). Record's own `answer` = LATEST; history = full log. Delete/
  retention/clear purge history too.
- `ocr_engine.py` — `extract_text(path, engine)`; `easyocr` (reader shared
  from server) or `paddle` (lazy SmartQuestionOCR from `OCR.py`). Default via
  `OCR_ENGINE` (paddle).
- `server.py` endpoints added:
  - `GET  /api/health` — openai_configured + model.
  - `POST /api/ask` — text → answer (JSON or SSE stream).
  - `GET  /api/records` — list (gallery).
  - `GET  /api/records/<id>` — fetch one (cache read; returns `cached` flag).
  - `DELETE /api/records/<id>` — delete record + its image.
  - `POST /api/records/clear` — clear history.
  - `GET  /api/records/<id>/image` — full image (under SHOTS_DIR only).
  - `GET  /api/records/<id>/thumb` — downscaled thumbnail for the gallery.
  - `POST /api/solve` — image (inline base64 or record_id) → OCR → OpenAI →
    answer, stored on record. Cache hit if already answered and not `force`.
    (One-shot path; still available but the overlay now uses the two-step flow.)
  - `POST /api/ocr-only` — image → OCR text ONLY (no OpenAI); creates a
    'captured' record; returns `{record_id, extracted_text}`. (Editable-OCR flow.)
  - `POST /api/ask` now accepts optional `record_id` → persists the (edited)
    text + answer onto that record (status 'answered').
  - `GET  /api/transcript` — current rolling transcript turns (in-memory).
  - `POST /api/transcript/clear` — clear the rolling transcript.
  - `POST /api/suggest` — 1-3 reply suggestions from the buffer (or a provided
    `dialogue`), tone-aware (Phase 6).
  - `WS   /ws/audio` — live audio-in/transcript-out + suggestions. Client sends
    `{speaker, audio(data-url), filename, auto_suggest, tone}` or
    `{type:suggest_now, tone}`; server transcribes with `gpt-4o-mini-transcribe`,
    adds to the buffer, replies `{type:transcript,...}`,
    `{type:suggestions, suggestions, trigger:auto|manual}`, or `{type:error}`.
    Auto-suggest fires after `AUTO_SUGGEST_SILENCE_S` (2.5s) of post-"Them"
    silence, throttled by `AUTO_SUGGEST_THROTTLE_S` (12s), via a per-connection
    watcher thread.
- `ai.py` also has `suggest(dialogue, tone)` + `COACH_SYSTEM_PROMPT` +
  `_parse_suggestions`.
- `ai.py` also has `transcribe(audio_bytes, filename)` and
  `TRANSCRIBE_MODEL` (env `OPENAI_TRANSCRIBE_MODEL`).
- `conversation.py` — in-memory rolling buffer (deque, max 60 turns):
  `add_turn`, `get_turns`, `as_dialogue` (Me:/Them: for Phase 6), `clear`.
  Raw transcript NOT persisted (OQ-3).

## Audio view — select-to-ask (transcript-first redesign)

The Audio view (S3) is now **transcript-first**, modeled on ChatGPT's
"select text → ask":
- Compact controls row: Start, Transcribe (on by default), two mini level
  meters, a ⚙︎ device-settings toggle (device selectors collapsed by default),
  and "💡 Ask latest".
- The **live transcript is the hero** (large, scrollable, selectable, speaker-
  colored Me/Them).
- **Select transcript text → right-click → "Ask" / "Ask with context"**
  (native Electron context menu). "Ask with context" prepends the recent
  transcript. The selection goes to `/api/ask`, the answer shows in the Answer
  view, and it's saved as a record (gallery + history).
- **Auto-scroll pauses** while the mouse is over the transcript or text is
  selected, so highlighting isn't disrupted; resumes afterward.
- Silence-based **auto-suggest is demoted** (off by default); "Ask latest"
  (⌘⇧A) remains as a one-click fallback that asks about recent dialogue.
- Wiring: renderer `contextmenu` → `showTranscriptMenu(selection)` → main
  builds a native `Menu` → `ask-selection` IPC back → renderer asks via
  `askText`. (preload: `showTranscriptMenu`, `onAskSelection`.)

## Overlay UI — view states (built Phase 3)

`index.html` rewritten as a polished four-state card:
- **S0 Floating dot** — minimized resting state (click to expand).
- **S1 Answer** — status dot (idle/thinking/ok/error, pulsing when thinking) +
  nav; large answer hero (streamed/filled); collapsible "Source text"
  (OCR/transcript); actions: Regenerate (force re-run w/ tone), Copy, and a
  **Tone selector** (concise/detailed/professional/casual).
- **S2 Gallery** — records grouped by day; thumbnail (or 🎙 for audio) + status
  badge (✓/○/!); delete per item + Clear history. Click = cache-read first
  (instant if answered) else solve once.
- **S3 Audio** — placeholder until Phases 4–6.
- Tone selection is pushed to main via `set-tone` so hotkey captures also use
  it. Backend `ai.py` applies tone via `TONE_SUFFIXES`; `/api/ask` + `/api/solve`
  accept a `tone` param.

## Overlay files (built Phase 2)

- `main.js` — global shortcuts (capture-full `Cmd/Ctrl+Shift+1`,
  capture-region `Cmd/Ctrl+Shift+2`, toggle-overlay `Cmd/Ctrl+Shift+H`;
  env-overridable). Native capture via `desktopCapturer` with Retina
  scale-factor handling. Posts captures to `/api/solve`, relays
  solve-status/answer/error to the overlay. Now loads local `index.html`.
- `selection.html` — transparent full-screen region selector (drag rectangle,
  size readout, Esc cancels), content-protected.
- `preload.js` — exposes sendRegion/cancelRegion + onSolveStatus/Answer/Error.
- `index.html` — added an answer panel wired to the solve IPC events.

## How to run (Phase 2, dev — two processes)

1. Backend: `cd screen_shot && python3 server.py`  (default port 3000; use
   `--port N` if 3000 is taken — see the port-3000 conflict note below).
   Add `.env` with `OPENAI_API_KEY` for real answers.
2. Overlay: `cd Overlay_Experiment/my-overlay-app && npm start`
   (set `BACKEND_PORT=N` to match if you changed the server port).
3. Grant macOS permissions when prompted: Screen Recording (capture),
   Accessibility (global hotkeys).
4. Press the capture hotkey → answer appears in the overlay's answer panel.

## Known runtime notes / caveats

- **Port 3000 is in use by another program** on this machine (found in
  Phase 0). Free it or run the server on another port + set `BACKEND_PORT`.
- `my-overlay-app/package.json` lists no `dependencies` though electron is in
  `node_modules`; tidy this before Phase 9 packaging.
- The overlay currently uses non-streaming `/api/solve` (single answer). The
  streaming `/api/ask` path exists and will be used where live typing helps.

## Current status

- Planning docs created and updated: `requirements.md`, `phases.md`,
  `memory.md`.
- Design locked: 3 features, same-machine/localhost, SQLite data layer +
  caching, 4 overlay view states, single-app packaging.
- **Phases 0–4 COMPLETE (code).** Backend OpenAI plumbing, SQLite data layer +
  caching, OCR engine selection, `/api/solve`, record image/thumb endpoints,
  Electron capture flow (full + region, Retina-aware), gallery + caching,
  polished four-state overlay UI (S0–S3) with tone selector, and the **audio
  capture foundation** (dual-stream Me/Them + level meters) are built. BlackHole
  2ch installed via Homebrew.
- **Phase 4 + 5 live test PENDING user action:** reboot (BlackHole driver loads
  at boot) + create a Multi-Output Device in Audio MIDI Setup, add OPENAI key to
  .env, then open the Audio view, enable "Transcribe", and confirm both meters
  move + live Me/Them transcript appears. See "Audio setup" below.
- **Phase 5 + 6 COMPLETE (code).** Phase 5: WS transcription pipeline (chunked
  ~4s segments → gpt-4o-mini-transcribe → tagged transcript + rolling buffer).
  Phase 6: coach suggestions (`suggest()`, `/api/suggest`, auto-trigger on
  "Them" silence + on-demand `suggest_now`/⌘⇧A hotkey, suggestions hero in the
  Audio view). Verified: all JS node --check OK; `/api/suggest` + the shared
  `_generate_suggestions` logic smoke-tested (empty→[], dialogue+no-key→clean
  error). WS transport proven in Phase 5 (the minimal websocket-client test lib
  can't decode permessage-deflate — a test-tool limitation, not a server bug).
- **Phase 7 COMPLETE (code).** Privacy (consent notice + opt-in transcript
  save, in-memory default), cost controls (context cap + throttle knobs), WS
  auto-reconnect with backoff + status UX, overlay window-position persistence,
  backend-readiness/no-key indicator, README onboarding (permissions, hotkeys,
  BlackHole, cost knobs, Windows notes).
- **Next up: Phase 8** (ScreenCaptureKit native system audio) — or Phase 9
  (packaging). Live audio test still pending user reboot + key.
- Phase order: 0✓ → 1✓ → 1b✓ → 2✓ → 2b✓ → 3✓ → 4✓(code) → 5✓(code) →
  6✓(code) → 7✓(code) → 8 (ScreenCaptureKit) → 9 (packaging).

## Audio setup (BlackHole + Multi-Output Device) — one-time

1. **Reboot** (BlackHole 2ch is installed; its CoreAudio driver loads at boot).
2. Open **Audio MIDI Setup** (`/Applications/Utilities`).
3. **+** (bottom-left) → **Create Multi-Output Device**. Check both your real
   output (speakers/headphones) AND **BlackHole 2ch**; keep the real output as
   primary/master so sound still reaches your ears.
4. In a meeting, set the Mac's **system output** to that Multi-Output Device.
5. In the overlay's **Audio** view: Me = your microphone, Them = **BlackHole
   2ch** input. Press **Start**; both meters should move (you speak → Me moves;
   audio plays → Them moves). Headphones avoid mic↔speaker bleed.

## Changelog

- **(initial)** Investigated both codebases; agreed architecture (Electron
  controller + Python service, WebSockets, BlackHole→ScreenCaptureKit,
  OpenAI Realtime); authored requirements, phases, and memory docs.
- **(design update)** Resolved OQ-1 (same machine / localhost). Added Feature C
  (gallery + answer caching). Chose SQLite data layer (images on disk, record
  model + caching rule). Defined 4 overlay view states (S0–S3). Added
  single-app packaging decision (PyInstaller-frozen Python spawned by Electron,
  electron-builder, tray/background, code-signing). Updated requirements.md,
  phases.md (new Phase 1b, 2b, 9), and memory.md accordingly.
- **(transcription decision)** Resolved OQ-2: OpenAI `gpt-4o-mini-transcribe`
  for STT with local Whisper (`faster-whisper`) as the zero-cost fallback.
  Confirmed **no diarization needed** — speaker identity comes from the capture
  source (mic = Me, system = Them), two labeled streams. Cost controls: "Them"
  continuous / "Me" on demand / voice-activity gating. Recorded reference
  pricing (~$0.003–0.006/min; ~$0.35–0.70/hr both streams).
- **(privacy + platform decision)** Resolved OQ-3 and OQ-4. OQ-3: keep SQLite
  (not JSON — clarified the "DB full" concern doesn't apply since images are on
  disk); answers/suggestions persisted for caching; raw live transcript
  in-memory-only by default + optional save toggle; one-time consent notice;
  added retention/cleanup policy (DS-7/DS-8). OQ-4: targets macOS 13+ and
  Windows 10+; recorded Windows 7 as best-effort/unsupported (EOL,
  incompatible with the modern stack). Updated all three docs.
- **(Phase 0 build)** Fixed main.js (fs import, configurable BACKEND_URL),
  requirements.txt deps, added .env support + .env.example + .gitignore,
  reconciled port to 3000. Verified server boots + serves / and /typings.
- **(Phase 1 build)** Added ai.py (OpenAI helper) + /api/ask (JSON + SSE) +
  /api/health. Verified error paths (400/502/SSE error) without a key.
- **(Phase 1b + 2 build)** Added db.py (SQLite records + caching),
  ocr_engine.py (easyocr/paddle), /api/records*, /api/solve. Rewrote Electron
  main.js for global-shortcut capture (full + region, Retina-aware) →
  /api/solve, added selection.html, updated preload.js + index.html answer
  panel. Backend smoke-tested end to end (OCR → record stored; OpenAI step
  pending a key). Overlay switched to local index.html.
- **(Phase 2b build)** Added record image/thumb endpoints
  (`/api/records/<id>/image` + `/thumb`). Added gallery view to overlay
  index.html (Answer/Gallery nav; records grouped by day; thumbnail + status
  badge ✓/○/!; delete + clear-history). preload.js exposes backendUrl + REST
  helpers (listRecords/getRecord/solveRecord/deleteRecord/clearRecords).
  openRecord() does cache-read first (instant if answered) else solve once.
  Verified end to end: image/thumb serve, 404 for missing, cache flips
  false→true, solve on answered record returns cached:true instantly (no
  OCR/OpenAI). Cleaned up test record/image/db.
- **(Phase 3 build)** Added tone support to ai.py (TONE_SUFFIXES + tone param
  on ask/ask_stream) threaded through /api/ask + /api/solve. main.js tracks
  currentTone via set-tone IPC and includes it in captures; preload exposes
  setTone + solveRecord(id,force,tone). Rewrote index.html as the polished
  four-state overlay (S0 dot, S1 answer hero + collapsible source + regenerate/
  copy/tone, S2 gallery, S3 audio placeholder). Verified: all JS node --check
  OK; server boots; tone accepted through routes; _build_messages injects the
  right tone suffix (detailed/casual/default-concise). Cleaned test db.
- **(Phase 4 build)** Installed BlackHole 2ch (brew, needs reboot). Added
  audio.js (window.AudioCapture: dual-stream Me/Them capture via getUserMedia +
  Web Audio RMS level metering; auto-guesses loopback device for Them). Rebuilt
  the overlay Audio view (S3) with Me/Them device selectors, Start/Stop, and
  two live level meters. Added media-permission handlers in main.js. Verified:
  all JS (main/preload/audio/index-inline) node --check OK. Live test (both
  meters moving) pending user reboot + Multi-Output Device setup.
- **(Phase 5 build)** Added ai.transcribe() (gpt-4o-mini-transcribe),
  conversation.py (in-memory rolling buffer, OQ-3 no-persist), flask-sock +
  /ws/audio WebSocket (tagged audio chunk → transcribe → buffer → transcript
  frame), /api/transcript[/clear]. Renderer: audio.js records ~4s self-contained
  webm segments per stream (MediaRecorder restarted each interval) → WS with
  speaker tag; index.html Audio view got a Transcribe toggle + live color-coded
  Me/Them transcript + clear; preload clearTranscript. Verified: all JS
  node --check OK; WS handshake + chunk roundtrip + bad-message handling return
  clean frames (error w/o key). Deps: flask-sock (prod), websocket-client (test
  only). Live STT pending user reboot + key.
- **(Phase 6 build)** Added ai.suggest() + COACH_SYSTEM_PROMPT +
  _parse_suggestions; server _generate_suggestions helper + POST /api/suggest;
  rewrote /ws/audio with safe_send + per-connection silence-watcher thread
  (auto suggestions after 2.5s Them-silence, 12s throttle) + on-demand
  suggest_now. main.js ask-now hotkey ⌘⇧A → overlay; preload onAskNow;
  audio.js suggestNow/setAutoSuggest/setTone + routes suggestions frame;
  index.html Audio view suggestions hero (Auto toggle + Ask now, numbered
  click-to-copy rows). Verified: all JS node --check OK; /api/suggest empty→[],
  dialogue+no-key→clean 502; _generate_suggestions direct test OK. (websocket-
  client test lib chokes on compressed frames — not a server bug; WS proven in
  Phase 5.) Live suggestions pending user reboot + key.
- **(Phase 7 build)** Privacy: POST /api/transcript/save (opt-in, writes
  transcripts/ gitignored), one-time consent banner (localStorage), Save button;
  transcript stays in-memory by default. Cost: SUGGEST_CONTEXT_TURNS=16 caps LLM
  context; throttle/silence knobs documented. Resilience: audio.js WS
  auto-reconnect (1s→10s backoff) + onStatus surfaced; stop() clears flags
  before close. Polish: overlay window bounds persisted (userData JSON);
  checkBackend() shows offline/no-key state via /api/health. README: appended
  copilot section (run, hotkeys, macOS permissions, BlackHole setup, privacy,
  cost knobs, Windows). Verified: all JS node --check OK; /api/transcript/save
  empty→400, with content→200 writes correct Me:/Them: file (Flask test client,
  same-process buffer). Cleaned test artifacts.
- **(Editable-OCR flow)** Changed capture UX per user request: capture no
  longer auto-answers. New flow = capture → `/api/ocr-only` (OCR, no OpenAI) →
  overlay shows the extracted text in an EDITABLE textarea (#ocr-input) →
  user edits → presses ➤ Ask (or ⌘⏎) → `/api/ask` with text + record_id →
  answer shows below + persisted to the record (status answered). main.js
  sendToSolve now hits /api/ocr-only and emits `ocr-ready`; preload adds
  `onOcrReady` + `askText(text,tone,recordId)`; index.html Answer view rebuilt
  (editable textarea on top, answer-hero below, Ask/Regenerate/Clear/Copy).
  openRecord loads a record's text into the textarea (cached answer shown
  instantly). Verified end-to-end on 3737 with real key: ocr-only returns text
  w/o answer; ask w/ edited text + record_id returns answer and record becomes
  answered storing the edited text. Live context note: user confirmed capture
  works (hotkey+screen grab OK); earlier "failed to load resource" was an
  overlay↔backend PORT MISMATCH (overlay must use BACKEND_PORT matching the
  server; another node app sometimes occupies 3000).
- **(Answer history + manual questions)** DB: added `answer_history` table +
  'manual' source_type. /api/ask now always persists (uses given record_id or
  creates a 'manual' record for typed questions), updates latest answer, and
  appends to history; returns record_id. /api/records/<id> returns `history`
  (newest-first). Overlay: gallery renders manual records as 💬 text-snippet
  tiles; record view shows the LATEST answer in the box + a collapsible
  "History (N)" of previous Q/A (hidden when <2). Verified end-to-end on 3737
  with key: manual question creates gallery record + answer; re-ask on same
  record builds 2-entry history newest-first (Italy→Rome latest, France→Paris
  below); manual record appears in gallery list. Cleaned up test record.
- **(Select-to-ask build)** Redesigned the Audio view to transcript-first with
  select-text → right-click → Ask (native Electron context menu via
  transcript-context-menu / ask-selection IPC; preload showTranscriptMenu +
  onAskSelection). "Ask with context" prepends ~last 1200 chars of transcript.
  Answers route to the Answer view + saved as records. Auto-scroll pauses on
  hover/selection (maybeScroll/shouldAutoScroll). Transcribe on by default;
  auto-suggest demoted (off). Compact controls + collapsible device panel +
  mini meters. Verified: all JS node --check OK; no dangling getElementById
  refs (46 referenced / 48 defined, 0 missing); backend untouched. Still
  pending live test. Also recently fixed: gallery clicks (no-drag), floating
  dot click-to-expand + restore size, re-enabled HW accel for smoother drag,
  resizable+collapsible OCR input, openRecord shows stored answer whenever
  present.
- **(LIVE TEST PASSED)** User confirmed audio transcription works live
  (mic + system audio via BlackHole) AND the select-to-ask feature works. Core
  product is now proven end to end on the user's machine: screenshot→OCR→answer,
  gallery+caching+history, manual questions, and dual-audio copilot with
  select-to-ask. Phases 4/5/6 are now verified live (not just code-complete).
- **(Screen-share leak fixes)** Two leaks fixed: (1) the transcript right-click
  menu was a NATIVE Electron Menu.popup() — native OS menus are NOT covered by
  setContentProtection, so they appeared in screen share. Replaced with an
  in-overlay HTML menu (#ctx-menu) drawn inside the content-protected window
  (Ask / Ask with context / Copy). Removed the native-menu IPC + dead preload
  showTranscriptMenu/onAskSelection. (2) The region-selection crosshair/box
  leaked: the selection window now is created hidden (show:false,
  paintWhenInitiallyHidden), setContentProtection(true) applied BEFORE first
  paint, then shown on 'ready-to-show' (re-asserted). KEY LESSON: content
  protection only covers BrowserWindows it's set on, applied before paint;
  native popups/menus are never covered. Verified: all JS node --check OK, no
  dangling refs, no native Menu usage. User to re-test in a real screen share.
