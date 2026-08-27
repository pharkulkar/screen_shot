# silent-screenshot-daemon

A cross-platform Python background utility that:

1. **Listens globally** for a key pressed N times in quick succession (default: `C` × 4 within 2 seconds)
2. **Silently captures** a full-screen PNG — no window, no sound, no UI
3. **Serves a web gallery** of all screenshots at `http://localhost:5000`

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

### 2. Grant Accessibility permission (macOS only)

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
http://localhost:5000
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
- `SilentScreenshotServer` — web gallery at http://localhost:5000

Uninstall:
```powershell
.\install\windows\uninstall-windows.ps1
```

---

## Project structure

```
screen_shot/
├── daemon.py              Key listener + screenshot capture (cross-platform)
├── server.py              Flask web gallery (http://localhost:5000)
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
| Port 5000 already in use | `python3 server.py --port 8080` |
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