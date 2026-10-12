# silent-screenshot-daemon

A cross-platform Python background utility that:

1. **Listens globally** for a key pressed N times in quick succession (default: `C` × 4 within 2 seconds)
2. **Silently captures** a full-screen PNG — no window, no sound, no UI
3. **Serves a web gallery** of all screenshots at `http://localhost:3000`

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.8+ |
| pynput | global key listener |
| Flask | web gallery server |
| Pillow | thumbnails + Windows screenshot capture |

**Platform screenshot tool:**

| Platform | Tool | Notes |
|---|---|---|
| macOS | `screencapture` | Built-in, no install needed |
| Windows | `Pillow.ImageGrab` | Installed via requirements.txt |
| Linux | `scrot` | `sudo apt install scrot` |

---

## Installation

### 1. Install Python dependencies (all platforms)

```bash
pip3 install -r requirements.txt
```

### 2. Configure your API key

Copy the example env file and add your OpenAI key:

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY=sk-...
```

`.env` is gitignored and read server-side only — the key is never exposed to
the overlay. The server runs fine without a key for the existing gallery/OCR
features; the key is required once OpenAI-backed answers are enabled.

### 3. Grant Accessibility permission (macOS only)

pynput uses `CGEventTap` to receive global key events. macOS requires
explicit permission for the app that owns the process.

1. Open **System Settings → Privacy & Security → Accessibility**
2. Click **+** and add the terminal app you use to run the daemon
   - Terminal.app → add `/Applications/Utilities/Terminal.app`
   - iTerm2 → add `/Applications/iTerm.app`
3. Toggle the switch **ON**
4. Restart the daemon after granting (takes effect on next launch)

---

## Running

### macOS / Linux

```bash
./run.sh
```

This starts both the daemon and the web server, then prints the gallery URL.

Or run them separately:

```bash
# Terminal 1 — daemon (must be in Terminal.app, not an IDE terminal)
python3 daemon.py

# Terminal 2 — web gallery
python3 server.py
```

### Windows

Double-click `run.bat`, or in PowerShell:

```powershell
.\run.bat
```

Both processes start minimised with no console window.

### Open the gallery

```
http://localhost:3000
```

---

## Triggering a screenshot

Press your hotkey character **4 times within 2 seconds** in any app.
Default trigger: `C C C C`

Only the timing between your trigger-key presses matters — other keys typed
in between are ignored. The sequence resets only if you take longer than
`maxIntervalMs` between presses.

---

## Configuration (`config.json`)

```json
{
  "outputDir":     "./screenshots",
  "hotkeyChar":    "C",
  "pressCount":    4,
  "maxIntervalMs": 2000,
  "logFile":       "./logs/daemon.log",
  "logLevel":      "debug"
}
```

| Key | Default | Meaning |
|---|---|---|
| `outputDir` | `./screenshots` | Where PNGs are saved |
| `hotkeyChar` | `C` | Single uppercase letter to watch |
| `pressCount` | `4` | Number of presses to trigger |
| `maxIntervalMs` | `2000` | Max ms between presses before reset |
| `logFile` | `./logs/daemon.log` | Log output path |
| `logLevel` | `debug` | `debug` or `info` |

Screenshots are saved as:
```
<outputDir>/YYYY-MM-DD/screenshot-<ISO-timestamp>.png
```

---

## Install as a login service

### macOS (launchd)

```bash
chmod +x install/macos/install-macos.sh
./install/macos/install-macos.sh
```

Uninstall:
```bash
./install/macos/uninstall-macos.sh
```

### Linux (systemd --user)

```bash
chmod +x install/linux/install-linux.sh
./install/linux/install-linux.sh
```

Uninstall:
```bash
./install/linux/uninstall-linux.sh
```

### Windows (Task Scheduler)

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\install\windows\install-windows.ps1
```

This registers two hidden tasks that start at login:
- `SilentScreenshotDaemon` — key listener
- `SilentScreenshotServer` — web gallery at http://localhost:3000

Uninstall:
```powershell
.\install\windows\uninstall-windows.ps1
```

---

## Project structure

```
screen_shot/
├── daemon.py              Key listener + screenshot capture (cross-platform)
├── server.py              Flask web gallery (http://localhost:3000)
├── config.json            Configuration
├── requirements.txt       Python dependencies
├── run.sh                 macOS/Linux launcher (daemon + server)
├── run.bat                Windows launcher (daemon + server)
│
├── install/
│   ├── macos/
│   │   ├── com.silent-screenshot-daemon.plist
│   │   ├── install-macos.sh
│   │   └── uninstall-macos.sh
│   ├── linux/
│   │   ├── silent-screenshot-daemon.service
│   │   ├── install-linux.sh
│   │   └── uninstall-linux.sh
│   └── windows/
│       ├── run-daemon-hidden.vbs
│       ├── run-server-hidden.vbs
│       ├── install-windows.ps1
│       └── uninstall-windows.ps1
│
├── screenshots/           YYYY-MM-DD/screenshot-<timestamp>.png
└── logs/
    └── daemon.log
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No debug lines in log | Accessibility not granted — see macOS section above |
| `Key 'C' press 1/4` but never reaches 4 | Sequence timing out — press faster, or increase `maxIntervalMs` |
| `ModuleNotFoundError: pynput` | `pip3 install -r requirements.txt` |
| Gallery shows "No screenshots yet" | Check daemon is running and `outputDir` in config matches |
| Port 3000 already in use | `python3 server.py --port 8080` |
| Windows: AV flags the process | Add a Windows Defender exclusion for the project folder — see note below |

### Windows — antivirus alerts

Global keyboard hooks are the same API used by keyloggers, so AV software
routinely flags them even for legitimate use. If Windows Defender or another
AV tool quarantines the process:

1. Review the source code to confirm it does nothing malicious
2. Add an exclusion in Windows Security for the project folder
3. On managed/corporate machines, inform your IT team before running

---

## License

MIT




cd /Users/pranayharkulkar/Desktop/pranay/Job_Hunt/screen_shot
./run.sh

---

# Meeting Copilot & Screen Assistant (Phases 0–7)

The project has grown beyond the original screenshot daemon into a desktop
assistant with two halves that share one always-on-top, screen-share-invisible
overlay (the Electron app in `../Overlay_Experiment/my-overlay-app`):

1. **Screenshot → OCR → OpenAI → Overlay** (full screen or drag-selected
   region), with a browsable gallery and answer caching.
2. **Dual-audio meeting copilot** — captures your mic ("Me") and system audio
   ("Them"), transcribes both live, and suggests what to say.

See `requirements.md`, `phases.md`, and `memory.md` for the full design.

## Run (development — two processes, same machine)

```bash
# 1. Backend (this folder)
cp .env.example .env            # add your OPENAI_API_KEY
pip3 install -r requirements.txt
python3 server.py               # default http://localhost:3000

# 2. Overlay (Electron)
cd ../Overlay_Experiment/my-overlay-app
npm start
```

If port 3000 is taken: `python3 server.py --port 3737` and launch the overlay
with `BACKEND_PORT=3737 npm start`.

## Global hotkeys (configurable via env)

| Action | Default | Env var |
|---|---|---|
| Capture full screen | ⌘⇧1 | `HOTKEY_CAPTURE_FULL` |
| Capture region | ⌘⇧2 | `HOTKEY_CAPTURE_REGION` |
| Ask now (meeting suggestion) | ⌘⇧A | `HOTKEY_ASK_NOW` |
| Hide/show overlay | ⌘⇧H | `HOTKEY_TOGGLE_OVERLAY` |

## macOS permissions (first run)

Grant these in **System Settings → Privacy & Security**:
- **Microphone** — for capturing your voice ("Me").
- **Accessibility** — for global hotkeys (grant to the app launching Electron).
- **Screen Recording** — for screen capture (and ScreenCaptureKit in Phase 8).

## System audio ("Them") — BlackHole + Multi-Output Device

macOS can't record system output directly, so route it through a virtual
device:
1. `brew install blackhole-2ch`, then **reboot**.
2. **Audio MIDI Setup** → **+** → **Create Multi-Output Device**; check both
   your real output and **BlackHole 2ch** (real output as primary).
3. Set the Mac's system output to that Multi-Output Device during meetings.
4. In the overlay's **Audio** view: Me = your mic, Them = **BlackHole 2ch**.
   Use headphones to avoid mic↔speaker bleed.

## Privacy

- The live transcript is **in memory only** and discarded when you stop/clear.
- "💾 Save" in the Audio view is the only thing that writes a transcript to
  disk (`transcripts/`, gitignored).
- A one-time consent notice is shown on first launch.
- Recording other people may require their consent depending on your location.

## Cost / tuning knobs (env)

| Var | Default | Meaning |
|---|---|---|
| `OPENAI_CHAT_MODEL` | gpt-4o-mini | Chat/answer/suggestion model |
| `OPENAI_TRANSCRIBE_MODEL` | gpt-4o-mini-transcribe | STT model |
| `OCR_ENGINE` | paddle | `paddle` or `easyocr` |
| `ANSWER_TONE` | concise | Default answer tone |
| `SUGGEST_CONTEXT_TURNS` | 16 | Dialogue turns sent to the LLM |
| `AUTO_SUGGEST_SILENCE_S` | 2.5 | Silence before auto-suggest |
| `AUTO_SUGGEST_THROTTLE_S` | 12 | Min seconds between auto-suggests |

## Windows notes

- Windows 10+ supported; system audio uses WASAPI loopback. Windows 7 is not a
  supported target (end-of-life, incompatible with the modern stack).
- Antivirus may flag the global key listener; add a project-folder exclusion.


How to run - 

1. Backend (Python) — Terminal 1
cd /Users/pranayharkulkar/Desktop/pranay/Job_Hunt/screen_shot
python3 server.py --port 3737

2. Overlay (Electron) — Terminal 2
cd /Users/pranayharkulkar/Desktop/pranay/Job_Hunt/Overlay_Experiment/my-overlay-app
BACKEND_PORT=3737 npm start
