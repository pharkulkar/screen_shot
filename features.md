# screen_shot — Feature List

The Python backend behind the Electron overlay (`../overlay_app`). It began as a
silent screenshot daemon and grew into a full **meeting copilot & screen
assistant**: it captures screenshots, runs OCR, answers questions with OpenAI,
transcribes live meeting audio, detects interview questions, and serves a web
gallery. Two cooperating processes:

- **`daemon.py`** — a global key-sequence listener that silently captures
  full-screen PNGs.
- **`server.py`** — a Flask server (default `http://localhost:3000`) exposing the
  web gallery, REST API, and WebSockets that the overlay talks to.

---

## 1. Silent screenshot daemon (`daemon.py`)

- **Global key-sequence trigger** — fires when a configured key is pressed N
  times within a time window (default: `C` × 4 within 2000 ms). Other keys in
  between are ignored; only timing between trigger-key presses matters.
- **Silent capture** — no window, no sound, no UI; all activity goes to a log.
- **Quit sequence** — `Q` × 4 (same timing window) cleanly shuts the daemon down.
- **Cross-platform capture:**
  - macOS & Linux — `mss` (in-process via ctypes; grabs the live compositor
    frame, captures all displays combined, no Screen Recording prompt).
  - Windows — Pillow `ImageGrab` (all screens).
- **Date-organized output** — saves to `screenshots/YYYY-MM-DD/screenshot-<ISO>.png`.
- **Single-instance guard** — a PID file prevents two daemons running at once
  (with stale-PID detection).
- **Rotating log files** — 5 MB × 5 backups, `debug`/`info` levels.
- **Graceful shutdown** on SIGINT/SIGTERM.
- **Config-driven** via `config.json` (hotkey char, press count, interval,
  output dir, log file/level).

## 2. Web gallery (`server.py`, served at `/`)

- **Browsable screenshot gallery** — cards grouped by day, newest first, with
  lazy-loaded thumbnails; self-contained HTML/CSS/JS (no frameworks, works
  offline).
- **Lightbox** — click a thumbnail to view the full image.
- **Per-image hover actions** — Solution (OCR), Edit, Delete.
- **In-browser image editor** (HTML canvas):
  - **Draw** freehand annotations.
  - **Crop** a selected area.
  - **Save** (overwrite) or **Save As New Version** (incremental `_v1`, `_v2`…).
  - Reset to the original.
- **Image versioning** — version picker in the OCR modal lists related versions
  of an image.
- **Delete** individual screenshots with confirmation.
- **Safe file serving** — path traversal is blocked; only files under the
  screenshots dir are served.
- **Thumbnails** generated on the fly with Pillow.

## 3. Live typing / second-screen view (`/typings`)

- **Live shared text panel** — type in one place; the preview syncs to every
  connected device in real time over **Server-Sent Events (SSE)**.
- **Transparent, draggable overlay styling** so it can sit on a second screen.
- **Auto-reconnecting SSE** with a connection-status dot and a live character
  count; collapsible/resizable input panel.

## 4. OCR — text extraction

Unified `extract_text(image, engine=...)` entry point (`ocr_engine.py`) with two
engines:

- **PaddleOCR via `SmartQuestionOCR`** (`OCR.py`) — the default, question-aware
  engine:
  - Document orientation, unwarping, and textline-orientation handling.
  - Image preprocessing — upscales small images, light bilateral denoising.
  - **Smart question detection from layout** — three strategies:
    1. Numbered anchors (`Q1`, `Q.1`, `Question 1`).
    2. Explicit `A./B./C./D.` option groups.
    3. Plain vertically left-aligned option groups.
  - Extracts the question text sitting above an option group, stitches wrapped
    lines, strips embedded answer options, filters UI noise (timers, progress
    counters, "Next/Submit", input placeholders), and de-duplicates by
    confidence/method priority.
  - Confidence-scored, lazily loaded (models are heavy).
- **easyocr** — a lighter baseline, reusing the server's shared reader.
- **Engine is overridable per request** and via `OCR_ENGINE` env (default
  `paddle`); failures degrade gracefully so the server stays up.

## 5. OpenAI answering (`ai.py`)

- **Answer mode** — given screen/typed text, directly answers the on-screen
  question (handles multiple-choice vs open questions, notes assumptions when
  ambiguous), tuned to be short and glanceable.
- **Streaming or full answers** — `ask()` and `ask_stream()` (SSE deltas).
- **Tone presets** — Concise / Detailed / Professional / Casual, appended to the
  system prompt.
- **Audio transcription** — `transcribe()` sends an audio chunk to OpenAI STT
  (`gpt-4o-mini-transcribe` by default).
- **Conversation coaching** — `suggest()` returns 1–3 ready-to-say reply options
  from the recent dialogue.
- **Interview answering** — dedicated prompts per category (technical, coding,
  behavioral/STAR, system design, general), streaming or full, with a strict
  "never fabricate resume details" rule and a language directive.
- **Lazy, defensive client** — the server boots for gallery/OCR even with no key;
  SDK errors (auth, rate limit, timeout, connection) map to clean, user-safe
  messages. The key is read server-side only, never exposed to the overlay.
- **Env-tunable models/timeout** (`OPENAI_CHAT_MODEL`, `OPENAI_TRANSCRIBE_MODEL`,
  `OPENAI_TIMEOUT`, `ANSWER_TONE`).

## 6. Records, caching & history (`db.py`, SQLite)

- **One record per answer** (screenshot / region / audio / manual) — stored in
  SQLite with WAL mode for smooth concurrent reads; images stay on disk and are
  referenced by path.
- **Answer caching** — once a record is answered, revisiting it is a cache hit:
  no re-OCR, no OpenAI call.
- **Answer history** — every Ask on a record appends a (question, answer) pair;
  the record keeps the latest answer, history keeps them all (newest first).
- **Lifecycle status** — captured → processing → answered / error.
- **Retention** — delete one record, clear all, or delete records older than N
  days.

## 7. REST API (`server.py`)

- **Health** — `GET /api/health` (OpenAI-configured flag, chat model, default
  language/locale, supported languages).
- **OCR** — `POST /api/ocr` (gallery image) and `POST /api/ocr-only` (inline
  base64 capture → text only, creates a reviewable record).
- **Ask** — `POST /api/ask` (text → answer, streaming optional, persists to a
  record + history).
- **Solve** — `POST /api/solve` (image → OCR → OpenAI → answer, cache-aware,
  `force` to bypass cache).
- **Records** — list / get / delete / clear, plus full-image and thumbnail
  endpoints (`/api/records…`).
- **Transcript** — get the in-memory rolling transcript, clear it, or opt-in save
  to disk (`transcripts/…`).
- **Suggestions** — `POST /api/suggest` (1–3 reply options from the buffer or an
  override dialogue).
- **Image edit save** — `POST /api/save-edit` (crop/draw result, overwrite or new
  version).
- **Versions** — `GET /api/versions/<date>/<filename>`.

## 8. Live meeting transcription & suggestions (WebSocket `/ws/audio`)

- **Dual-speaker audio in** — accepts `me` / `them` audio chunks (base64 webm),
  transcribes each, and streams back `transcript` events tagged by speaker.
- **Rolling in-memory transcript** (`conversation.py`) — bounded to the last 60
  turns; speaker-tagged; discarded unless explicitly saved (privacy by default).
- **"What should I say" suggestions** — on-demand (`suggest_now`) or automatic:
  after "Them" speaks, a silence-watcher waits out a configurable silence window
  and auto-generates suggestions, throttled to control cost.
- **Cost knobs** (env) — `SUGGEST_CONTEXT_TURNS`, `AUTO_SUGGEST_SILENCE_S`,
  `AUTO_SUGGEST_THROTTLE_S`.

## 9. Automatic interview Q&A engine

The backend half of the overlay's Interview tab — detects interviewer questions
and answers them automatically.

- **Question detection** (`question_detector.py`):
  - Fast, free **heuristics first** — wh-words, request/imperative openers,
    follow-up openers, implicit "your approach/opinion" phrasing, with category
    classification (technical / coding / behavioral / system_design / general).
  - **Ignores** greetings, acknowledgements, filler, and interviewer
    self-introductions; detects mid-sentence/incomplete fragments and waits.
  - **Optional LLM confirmation** only for ambiguous confidence bands (cost
    control), reusing `ai.py`; never crashes, always falls back to heuristics.
- **Session orchestration** (`interview_session.py`):
  - Per-session transcript with **end-of-utterance (EOU) debouncing** — merges
    partials/finals, uses a short grace window for already-complete sentences so
    answers start fast.
  - **Deduplicates** repeated questions within a time window.
  - **Cancel/replace** — a newer question supersedes a still-pending one.
  - **At-most-one active generation per question**, bounded global concurrency
    via a thread pool; per-answer **timeout** watchdog.
  - **Streamed answer events** — `SESSION_STARTED`, `TRANSCRIPT_PARTIAL/FINAL`,
    `QUESTION_DETECTED`, `ANSWER_GENERATION_STARTED`, `ANSWER_CHUNK`,
    `ANSWER_COMPLETED`, `QUESTION_CANCELLED`, `ERROR`.
  - **Isolated sessions** never share transcript/context; **best-effort persist**
    of each Q/A into the records DB.
- **Transports** — low-latency **WebSocket `/ws/interview`** plus a REST fallback
  (`/api/interview/start|transcript|events|history|cancel|stop`) with a buffered
  event queue for polling clients.
- **Configurable** (`interview_config.py` / `config.json` `interview` block /
  `INTERVIEW_*` env) — confidence threshold, EOU window, min chars, answer
  timeout, history cap, models, temperature, streaming, dedup window, max
  concurrency, LLM-classifier toggle, default language/locale.
- **Language registry** — English default with `en-IN` STT locale; never
  auto-switches to an unsupported language.

## 10. Configuration & environment

- **`config.json`** — daemon settings + an `interview` block.
- **`.env`** (gitignored) — `OPENAI_API_KEY` and other secrets, read server-side
  only; `.env.example` provided.
- **Extensive env overrides** — models, tones, OCR engine, interview tunables,
  auto-suggest timing, DB path.
- **Configurable port/host** — `python3 server.py --port 8080 --host ...`.

## 11. Deployment & platform

- **Launchers** — `run.sh` (macOS/Linux) and `run.bat` (Windows) start both the
  daemon and the server.
- **Login-service installers** under `install/`:
  - macOS — launchd `.plist` (install/uninstall scripts).
  - Linux — systemd `--user` service (install/uninstall scripts).
  - Windows — Task Scheduler (two hidden tasks) via PowerShell scripts, with
    hidden-launch VBS wrappers.
- **LAN access** — the server prints both a localhost and a network URL so a
  phone / second screen can reach the gallery and `/typings`.
- **Dependencies** — Flask, flask-sock (WebSockets), Pillow, pynput, mss,
  PaddleOCR/easyocr (OCR), OpenAI SDK, python-dotenv; most imports are defensive
  so missing optional pieces disable just that feature instead of the whole
  server.

---

## Running

```bash
# 1. Install deps and set the key
pip3 install -r requirements.txt
cp .env.example .env            # add OPENAI_API_KEY=sk-...

# 2a. Both processes together
./run.sh                        # macOS/Linux   (run.bat on Windows)

# 2b. Or separately
python3 daemon.py               # key listener (needs Accessibility on macOS)
python3 server.py               # web gallery + API at http://localhost:3000
python3 server.py --port 3737   # custom port
```

macOS permissions on first run: **Accessibility** (global key listener),
**Microphone** (meeting audio), and **Screen Recording** (screen capture).
