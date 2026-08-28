#!/usr/bin/env python3
"""
screenshot-viewer server
========================
Serves a lightweight web gallery of all captured screenshots on:

    http://localhost:5000

Organised by date, newest first. Click any thumbnail to view full-size.
No external CSS/JS frameworks — plain HTML + inline styles so it works
completely offline.

Usage:
    python3 server.py              # starts on port 5000
    python3 server.py --port 8080  # custom port
    pythonw server.py              # Windows: no console window
"""

import argparse
import json
import logging
import os
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, render_template_string, request, Response, send_file

# ── Resolve project root ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent


# ── Load config ───────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        return {"outputDir": "./screenshots"}
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)

CFG        = load_config()
SHOTS_DIR  = ROOT / CFG.get("outputDir", "./screenshots")


# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

# Silence Flask's default request logger — keep the terminal/log clean.
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)


# ── Live-typing shared state (SSE broadcast) ──────────────────────────────────

_typing_lock     = threading.Lock()
_typing_text     = ""          # latest text from any connected typer
_typing_listeners: list[queue.Queue] = []  # one queue per SSE subscriber


def _broadcast(text: str) -> None:
    """Push the current text to every waiting SSE subscriber."""
    with _typing_lock:
        listeners = list(_typing_listeners)
    for q in listeners:
        try:
            q.put_nowait(text)
        except queue.Full:
            pass  # slow client — skip this frame


# ── HTML template ─────────────────────────────────────────────────────────────

GALLERY_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Screenshots</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f0f0f;
      color: #e0e0e0;
      min-height: 100vh;
      padding: 24px;
    }

    header {
      display: flex;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 32px;
      border-bottom: 1px solid #2a2a2a;
      padding-bottom: 16px;
    }

    header h1 { font-size: 1.4rem; font-weight: 600; color: #fff; }
    header span { font-size: 0.85rem; color: #666; }

    .day-group { margin-bottom: 40px; }

    .day-label {
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #555;
      margin-bottom: 14px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px;
    }

    .card {
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 8px;
      overflow: hidden;
      transition: border-color 0.15s, transform 0.15s;
      cursor: pointer;
      text-decoration: none;
      display: block;
    }
    .card:hover {
      border-color: #555;
      transform: translateY(-2px);
    }

    .card img {
      width: 100%;
      height: 130px;
      object-fit: cover;
      display: block;
      background: #111;
    }

    .card-meta {
      padding: 8px 10px;
      font-size: 0.72rem;
      color: #666;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .empty {
      color: #444;
      font-size: 0.9rem;
      margin-top: 60px;
      text-align: center;
    }

    /* Lightbox */
    #lb {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.92);
      z-index: 100;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 16px;
    }
    #lb.open { display: flex; }
    #lb img {
      max-width: 95vw;
      max-height: 88vh;
      border-radius: 6px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.6);
    }
    #lb-close {
      position: fixed;
      top: 18px;
      right: 24px;
      font-size: 2rem;
      color: #aaa;
      cursor: pointer;
      line-height: 1;
      user-select: none;
    }
    #lb-close:hover { color: #fff; }
    #lb-name { font-size: 0.78rem; color: #666; }
  </style>
</head>
<body>

<header>
  <h1>Screenshots</h1>
  <span>{{ total }} screenshot{% if total != 1 %}s{% endif %} across {{ days|length }} day{% if days|length != 1 %}s{% endif %}</span>
</header>

{% if days %}
  {% for date, files in days %}
  <div class="day-group">
    <div class="day-label">{{ date }}</div>
    <div class="grid">
      {% for f in files %}
      <a class="card" href="#" onclick="openLb('/img/{{ date }}/{{ f }}','{{ f }}'); return false;">
        <img src="/thumb/{{ date }}/{{ f }}" alt="{{ f }}" loading="lazy" />
        <div class="card-meta">{{ f | replace('screenshot-','') | replace('.png','') }}</div>
      </a>
      {% endfor %}
    </div>
  </div>
  {% endfor %}
{% else %}
  <p class="empty">No screenshots yet. Trigger the daemon by pressing the hotkey sequence.</p>
{% endif %}

<!-- Lightbox -->
<div id="lb">
  <span id="lb-close" onclick="closeLb()">&#x2715;</span>
  <img id="lb-img" src="" alt="" />
  <div id="lb-name"></div>
</div>

<script>
  function openLb(src, name) {
    document.getElementById('lb-img').src = src;
    document.getElementById('lb-name').textContent = name;
    document.getElementById('lb').classList.add('open');
  }
  function closeLb() {
    document.getElementById('lb').classList.remove('open');
    document.getElementById('lb-img').src = '';
  }
  document.getElementById('lb').addEventListener('click', function(e) {
    if (e.target === this) closeLb();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeLb();
  });
</script>
</body>
</html>
"""

TYPINGS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Live Typing</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0f0f0f;
      color: #e0e0e0;
      min-height: 100vh;
    }

    .app {
      width: 100%;
      min-height: 100vh;
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    header {
      padding-bottom: 16px;
      border-bottom: 1px solid #2a2a2a;
    }

    header h1 {
      font-size: 1.4rem;
      font-weight: 600;
      color: #ffffff;
      margin-bottom: 5px;
    }

    header p { font-size: 0.85rem; color: #777; }

    .workspace {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 20px;
      min-height: 0;
    }

    .panel {
      background: #171717;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    .input-panel {
      min-height: 180px;
      height: 300px;
      max-height: 70vh;
    }

    .panel-header {
      min-height: 48px;
      padding: 12px 16px;
      border-bottom: 1px solid #2a2a2a;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-shrink: 0;
    }

    .panel-title {
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #777;
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #444;
      transition: background 0.3s;
      flex-shrink: 0;
    }
    .status-dot.connected { background: #4caf50; }
    .status-dot.error     { background: #f44336; }

    .collapse-button {
      border: 1px solid #333;
      background: #222;
      color: #aaa;
      width: 30px;
      height: 30px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 1rem;
      line-height: 1;
      transition: background 0.15s, color 0.15s;
    }
    .collapse-button:hover { background: #2a2a2a; color: #fff; }

    .input-wrapper { flex: 1; min-height: 0; display: flex; }

    textarea {
      width: 100%;
      height: 100%;
      resize: vertical;
      border: none;
      outline: none;
      background: transparent;
      color: #f0f0f0;
      padding: 18px;
      font-family: inherit;
      font-size: 1rem;
      line-height: 1.6;
    }
    textarea::placeholder { color: #555; }

    .resize-handle {
      height: 10px;
      cursor: ns-resize;
      background: transparent;
      flex-shrink: 0;
      position: relative;
    }
    .resize-handle::after {
      content: "";
      width: 40px;
      height: 4px;
      border-radius: 10px;
      background: #3a3a3a;
      position: absolute;
      left: 50%;
      top: 3px;
      transform: translateX(-50%);
    }

    .preview-panel { flex: 1; min-height: 250px; }

    .preview {
      flex: 1;
      min-height: 0;
      padding: 22px;
      overflow-y: auto;
      font-size: 1rem;
      line-height: 1.7;
      color: #f0f0f0;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .placeholder { color: #555; }

    .input-panel.collapsed {
      height: 48px !important;
      min-height: 48px;
    }
    .input-panel.collapsed .input-wrapper,
    .input-panel.collapsed .resize-handle { display: none; }
    .input-panel.collapsed .collapse-button { transform: rotate(180deg); }

    .footer {
      text-align: right;
      font-size: 0.75rem;
      color: #555;
      flex-shrink: 0;
    }

    @media (max-width: 768px) {
      .app { padding: 16px; gap: 14px; }
      .workspace { gap: 14px; }
      .input-panel { height: 260px; min-height: 140px; }
      .preview-panel { min-height: 220px; }
      textarea, .preview { font-size: 0.95rem; }
      textarea { padding: 14px; }
      .preview { padding: 16px; }
    }

    @media (max-width: 480px) {
      .app { padding: 12px; }
      header h1 { font-size: 1.2rem; }
      header p { font-size: 0.78rem; }
      .input-panel { height: 220px; }
      .panel-header { min-height: 44px; padding: 10px 12px; }
      .collapse-button { width: 28px; height: 28px; }
    }
  </style>
</head>
<body>
  <main class="app">

    <header>
      <h1>Live Typing</h1>
      <p>Type in the editor below — the preview syncs to every connected device.</p>
    </header>

    <section class="workspace">

      <!-- Input Panel -->
      <div class="panel input-panel" id="input-panel">
        <div class="panel-header">
          <span class="panel-title">Type Here</span>
          <button class="collapse-button" id="collapse-button" type="button"
            title="Collapse input" aria-label="Collapse input">&#9650;</button>
        </div>
        <div class="input-wrapper">
          <textarea id="typing-input" placeholder="Start typing here..." autofocus></textarea>
        </div>
        <div class="resize-handle" id="resize-handle" title="Drag to resize"></div>
      </div>

      <!-- Preview Panel -->
      <div class="panel preview-panel">
        <div class="panel-header">
          <span class="panel-title">Live Preview</span>
          <span class="status-dot" id="status-dot" title="SSE connection status"></span>
        </div>
        <div id="typing-preview" class="preview placeholder">
          Your typed text will appear here...
        </div>
      </div>

    </section>

    <div class="footer">
      <span id="character-count">0</span> characters
    </div>

  </main>

  <script>
    const input          = document.getElementById('typing-input');
    const preview        = document.getElementById('typing-preview');
    const charCount      = document.getElementById('character-count');
    const inputPanel     = document.getElementById('input-panel');
    const collapseButton = document.getElementById('collapse-button');
    const resizeHandle   = document.getElementById('resize-handle');
    const statusDot      = document.getElementById('status-dot');

    // ── SSE: receive updates from server ──────────────────────────────────────
    function setPreview(value) {
      charCount.textContent = value.length;
      if (value.length > 0) {
        preview.textContent = value;
        preview.classList.remove('placeholder');
      } else {
        preview.textContent = 'Your typed text will appear here...';
        preview.classList.add('placeholder');
      }
    }

    function connectSSE() {
      const es = new EventSource('/typings/stream');

      es.addEventListener('update', function (e) {
        statusDot.className = 'status-dot connected';
        // Server sends text JSON-encoded to handle newlines safely
        try {
          const value = JSON.parse(e.data);
          setPreview(value);
          // Keep local textarea in sync too (another device may have typed)
          if (document.activeElement !== input) {
            input.value = value;
          }
        } catch (_) {}
      });

      es.addEventListener('open', function () {
        statusDot.className = 'status-dot connected';
      });

      es.addEventListener('error', function () {
        statusDot.className = 'status-dot error';
        es.close();
        setTimeout(connectSSE, 2000);
      });
    }

    connectSSE();

    // ── Input: broadcast to server on every keystroke ─────────────────────────
    input.addEventListener('input', function () {
      const value = input.value;
      setPreview(value);
      fetch('/typings/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: value }),
        keepalive: true
      }).catch(function () {});
    });

    // ── Collapse / Expand ─────────────────────────────────────────────────────
    collapseButton.addEventListener('click', function () {
      inputPanel.classList.toggle('collapsed');
      const collapsed = inputPanel.classList.contains('collapsed');
      collapseButton.innerHTML = collapsed ? '&#9660;' : '&#9650;';
      collapseButton.title       = collapsed ? 'Expand input'   : 'Collapse input';
      collapseButton.setAttribute('aria-label', collapsed ? 'Expand input' : 'Collapse input');
    });

    // ── Resize handle ─────────────────────────────────────────────────────────
    let isResizing = false, startY = 0, startHeight = 0;

    resizeHandle.addEventListener('mousedown', function (e) {
      if (inputPanel.classList.contains('collapsed')) return;
      isResizing = true;
      startY = e.clientY;
      startHeight = inputPanel.getBoundingClientRect().height;
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', function (e) {
      if (!isResizing) return;
      const h = Math.max(120, Math.min(startHeight + e.clientY - startY, window.innerHeight * 0.75));
      inputPanel.style.height = h + 'px';
    });

    document.addEventListener('mouseup', function () {
      if (!isResizing) return;
      isResizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });

    // ── Touch resize ──────────────────────────────────────────────────────────
    resizeHandle.addEventListener('touchstart', function (e) {
      if (inputPanel.classList.contains('collapsed')) return;
      isResizing = true;
      startY = e.touches[0].clientY;
      startHeight = inputPanel.getBoundingClientRect().height;
    }, { passive: true });

    document.addEventListener('touchmove', function (e) {
      if (!isResizing) return;
      const h = Math.max(120, Math.min(startHeight + e.touches[0].clientY - startY, window.innerHeight * 0.75));
      inputPanel.style.height = h + 'px';
    }, { passive: true });

    document.addEventListener('touchend', function () { isResizing = false; });
  </script>
</body>
</html>
"""




# ── Helpers ───────────────────────────────────────────────────────────────────

def get_days() -> list[tuple[str, list[str]]]:
    """Return [(date_str, [filenames newest-first]), ...] newest date first."""
    if not SHOTS_DIR.exists():
        return []
    days = []
    for day_dir in sorted(SHOTS_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        files = sorted(
            [f.name for f in day_dir.iterdir() if f.suffix == ".png"],
            reverse=True,
        )
        if files:
            days.append((day_dir.name, files))
    return days


def total_count(days) -> int:
    return sum(len(files) for _, files in days)


def safe_path(date: str, filename: str) -> Path:
    """Resolve and validate the path is inside SHOTS_DIR (no traversal)."""
    candidate = (SHOTS_DIR / date / filename).resolve()
    if not str(candidate).startswith(str(SHOTS_DIR.resolve())):
        abort(403)
    if not candidate.exists():
        abort(404)
    return candidate


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    days = get_days()
    return render_template_string(
        GALLERY_TEMPLATE,
        days=days,
        total=total_count(days),
    )

@app.route("/typings")
def typings():
    days = get_days()
    return render_template_string(
        TYPINGS_TEMPLATE,
        days=days,
        total=total_count(days),
    )


@app.route("/typings/update", methods=["POST"])
def typings_update():
    """Receive the current typed text and broadcast it to all SSE subscribers."""
    global _typing_text
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    with _typing_lock:
        _typing_text = text
    _broadcast(text)
    return "", 204


@app.route("/typings/stream")
def typings_stream():
    """SSE endpoint — streams live typing updates to every connected device."""
    q: queue.Queue = queue.Queue(maxsize=64)

    # Send current text immediately so the new subscriber is in sync
    with _typing_lock:
        initial = _typing_text
        _typing_listeners.append(q)

    def generate():
        # Push the current snapshot first (JSON-encoded so newlines are safe)
        yield f"event: update\ndata: {json.dumps(initial)}\n\n"
        try:
            while True:
                try:
                    text = q.get(timeout=20)
                    yield f"event: update\ndata: {json.dumps(text)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            with _typing_lock:
                try:
                    _typing_listeners.remove(q)
                except ValueError:
                    pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/img/<date>/<filename>")
def full_image(date: str, filename: str):
    """Serve the original full-resolution PNG."""
    path = safe_path(date, filename)
    return send_file(path, mimetype="image/png")


@app.route("/thumb/<date>/<filename>")
def thumbnail(date: str, filename: str):
    """
    Serve a scaled-down thumbnail.
    Uses Pillow if available, falls back to the original image.
    """
    path = safe_path(date, filename)
    try:
        from PIL import Image
        import io
        with Image.open(path) as img:
            img.thumbnail((440, 280))
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            return send_file(buf, mimetype="image/png")
    except Exception:
        # Pillow not installed or error — serve original.
        return send_file(path, mimetype="image/png")


@app.route("/api/screenshots")
def api_list():
    """JSON API: list all screenshots grouped by date."""
    from flask import jsonify
    days = get_days()
    return jsonify([
        {"date": date, "files": files}
        for date, files in days
    ])


# ── Entry point ───────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Return the machine's LAN IP (the one reachable from other devices)."""
    import socket
    try:
        # Connect to an external address (doesn't send data) just to find
        # which local interface the OS would use for outbound traffic.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Screenshot viewer server")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    # Default to 0.0.0.0 so the server is reachable from any device on the
    # local network (iPhone, iPad, other computers, etc.)
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    args = parser.parse_args()

    local_ip = get_local_ip()

    print()
    print("  Screenshot viewer")
    print(f"  Local (this machine):  http://localhost:{args.port}")
    print(f"  Network (iPhone/etc):  http://{local_ip}:{args.port}")
    print()
    print(f"  Screenshots folder:    {SHOTS_DIR}")
    print()
    print("  Press Ctrl-C to stop.")
    print()

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
