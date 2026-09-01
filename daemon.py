#!/usr/bin/env python3
"""
silent-screenshot-daemon
========================
Cross-platform background utility that listens globally for a key pressed
N times within a time window, then silently captures a full-screen PNG.

  macOS   — uses built-in `screencapture -x`
  Windows — uses Pillow (ImageGrab)
  Linux   — uses `scrot` (install via: sudo apt install scrot)

No window. No sound. No UI. All activity goes to the log file.

Usage:
    python3 daemon.py          # foreground / manual
    pythonw daemon.py          # Windows: no console window
"""

import json
import logging
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pynput import keyboard

# ── Platform ──────────────────────────────────────────────────────────────────
PLATFORM = platform.system()   # "Darwin" | "Windows" | "Linux"

# ── Resolve project root ──────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parent
PIDFILE = ROOT / "daemon.pid"


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found at {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {
        "output_dir":      cfg.get("outputDir",     "./screenshots"),
        "hotkey_char":     cfg.get("hotkeyChar",    "C").upper(),
        "press_count":     int(cfg.get("pressCount",    4)),
        "max_interval_ms": int(cfg.get("maxIntervalMs", 2000)),
        "log_file":        cfg.get("logFile",       "./logs/daemon.log"),
        "log_level":       cfg.get("logLevel",      "debug").upper(),
    }


# ── Logger ────────────────────────────────────────────────────────────────────

def build_logger(log_file: str, log_level: str) -> logging.Logger:
    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("daemon")
    logger.handlers.clear()
    logger.setLevel(getattr(logging, log_level, logging.DEBUG))

    fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


# ── PID file ──────────────────────────────────────────────────────────────────

def write_pidfile():
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")

def remove_pidfile():
    try:
        PIDFILE.unlink()
    except FileNotFoundError:
        pass

def check_already_running() -> bool:
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)   # signal 0: existence check only
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False      # stale PID file


# ── Screenshot ────────────────────────────────────────────────────────────────

def _build_output_path(output_dir: str) -> Path:
    base = Path(output_dir)
    if not base.is_absolute():
        base = ROOT / base
    now      = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    ts_str   = now.strftime("%Y-%m-%dT%H-%M-%S-%f")
    out_dir  = base / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"screenshot-{ts_str}.png"


def _capture_with_mss(out_path: Path, log: logging.Logger):
    """
    Capture all displays using the `mss` library (macOS + Linux).

    mss runs in-process via ctypes — no subprocess, no Screen Recording
    permission dialog. Captures the live compositor frame directly.
    monitor[0] = all displays combined into one image.
    """
    import mss
    import mss.tools

    with mss.MSS() as sct:
        monitor = sct.monitors[0]   # index 0 = all displays combined
        raw = sct.grab(monitor)
        mss.tools.to_png(raw.rgb, raw.size, output=str(out_path))

    size = out_path.stat().st_size if out_path.exists() else 0
    if size < 50_000:
        log.error(f"mss capture unexpectedly small ({size} bytes) — check display connection")
    else:
        log.info(f"Screenshot saved: {out_path}  ({size // 1024} KB)")


def _capture_macos(out_path: Path, log: logging.Logger):
    _capture_with_mss(out_path, log)


def _capture_windows(out_path: Path, log: logging.Logger):
    """Windows: Pillow ImageGrab — works without any extra tools."""
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=True)
    img.save(str(out_path), format="PNG")
    size = out_path.stat().st_size if out_path.exists() else 0
    log.info(f"Screenshot saved: {out_path}  ({size // 1024} KB)")


def _capture_linux(out_path: Path, log: logging.Logger):
    """Linux: mss (works on X11; Wayland requires XCB backend)."""
    _capture_with_mss(out_path, log)


def take_screenshot(output_dir: str, log: logging.Logger) -> None:
    out_path = _build_output_path(output_dir)
    log.info(f"Trigger detected — saving to: {out_path}")
    try:
        if PLATFORM == "Darwin":
            _capture_macos(out_path, log)
        elif PLATFORM == "Windows":
            _capture_windows(out_path, log)
        else:
            _capture_linux(out_path, log)
    except subprocess.TimeoutExpired:
        log.error("Capture timed out after 10s")
    except Exception as e:
        log.error(f"Screenshot error: {e}", exc_info=True)


# ── Sequence detector ─────────────────────────────────────────────────────────

class SequenceDetector:
    """
    Fires on_trigger() when the target key is pressed press_count times,
    each within max_interval_ms of the previous one.
    All other keys are completely ignored — only timing between target-key
    presses matters.
    """

    def __init__(self, char: str, press_count: int, max_interval_ms: int,
                 on_trigger, log: logging.Logger):
        self._char            = char.lower()
        self._press_count     = press_count
        self._max_interval_ms = max_interval_ms
        self._on_trigger      = on_trigger
        self._log             = log
        self._count           = 0
        self._last_ms         = 0.0
        self._lock            = threading.Lock()

    def handle(self, key) -> None:
        try:
            ch = key.char
        except AttributeError:
            return          # modifier / special key — ignore
        if ch is None:
            return
        if ch != self._char:
            return          # different key — ignore, don't reset

        now_ms = time.monotonic() * 1000

        with self._lock:
            if self._count > 0 and (now_ms - self._last_ms) > self._max_interval_ms:
                self._log.debug(
                    f"Timeout ({now_ms - self._last_ms:.0f}ms). Restarting counter."
                )
                self._count = 0

            self._count  += 1
            self._last_ms = now_ms
            self._log.debug(
                f"Key '{ch.upper()}' press {self._count}/{self._press_count}"
            )

            if self._count >= self._press_count:
                self._count = 0
                threading.Thread(target=self._on_trigger, daemon=True).start()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if check_already_running():
        print(
            f"ERROR: daemon already running "
            f"(PID {PIDFILE.read_text(encoding='utf-8').strip()}). "
            "Kill it first with:  pkill -f 'python.*daemon.py'",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = load_config()
    log = build_logger(cfg["log_file"], cfg["log_level"])
    write_pidfile()

    log.info("=" * 60)
    log.info("silent-screenshot-daemon starting")
    log.info(
        f"Config: trigger='{cfg['hotkey_char']}' "
        f"x{cfg['press_count']} within {cfg['max_interval_ms']}ms"
    )
    log.info(f"Quit:   'Q' x{cfg['press_count']} within {cfg['max_interval_ms']}ms")
    log.info(f"Output: {(ROOT / cfg['output_dir']).resolve()}")
    log.info(f"PID: {os.getpid()} | Python {sys.version.split()[0]} | {PLATFORM}")

    # Event set by the quit sequence; causes the listener loop to exit cleanly.
    stop_event = threading.Event()

    def on_trigger():
        take_screenshot(cfg["output_dir"], log)

    def on_quit():
        log.info("Quit sequence detected (Q x4) — shutting down.")
        remove_pidfile()
        stop_event.set()

    # Screenshot detector — configured hotkey (default C x4)
    screenshot_detector = SequenceDetector(
        char=cfg["hotkey_char"],
        press_count=cfg["press_count"],
        max_interval_ms=cfg["max_interval_ms"],
        on_trigger=on_trigger,
        log=log,
    )

    # Quit detector — always Q x4, same timing window
    quit_detector = SequenceDetector(
        char="Q",
        press_count=cfg["press_count"],
        max_interval_ms=cfg["max_interval_ms"],
        on_trigger=on_quit,
        log=log,
    )

    def on_key(key):
        screenshot_detector.handle(key)
        quit_detector.handle(key)
        # Return False to stop the listener once stop_event is set.
        if stop_event.is_set():
            return False

    def shutdown(signum, frame):
        log.info(f"Signal {signum} — shutting down.")
        remove_pidfile()
        raise SystemExit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Global key listener active. Waiting for trigger sequence…")

    try:
        with keyboard.Listener(on_press=on_key) as listener:
            listener.join()
    except SystemExit:
        pass
    except Exception as e:
        log.error(f"Listener crashed: {e}", exc_info=True)
    finally:
        remove_pidfile()

    log.info("Daemon stopped.")


if __name__ == "__main__":
    main()
