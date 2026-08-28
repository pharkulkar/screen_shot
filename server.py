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
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, render_template_string, send_file

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

TYPINGS_TEMPLATE = """

<!DOCTYPE html>

<html lang="en">

<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />

  <title>Live Typing</title>

  <style>

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

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

    header p {
      font-size: 0.85rem;
      color: #777;
    }

    .content {
      flex: 1;
      display: grid;
      grid-template-rows: minmax(180px, 1fr) minmax(180px, 1fr);
      gap: 20px;
    }

    .panel {
      background: #171717;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      overflow: hidden;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }

    .panel-header {
      padding: 12px 16px;
      border-bottom: 1px solid #2a2a2a;
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #777;
    }

    textarea {
      width: 100%;
      flex: 1;
      resize: none;
      border: none;
      outline: none;
      background: transparent;
      color: #f0f0f0;
      padding: 18px;
      font-family: inherit;
      font-size: 1rem;
      line-height: 1.6;
    }

    textarea::placeholder {
      color: #555;
    }

    .preview {
      flex: 1;
      padding: 18px;
      overflow-y: auto;
      font-size: 1rem;
      line-height: 1.6;
      color: #f0f0f0;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .placeholder {
      color: #555;
    }

    .footer {
      text-align: right;
      font-size: 0.75rem;
      color: #555;
    }

    /*
      Tablet and desktop:
      Input and preview appear side by side.
    */
    @media (min-width: 768px) {

      .app {
        padding: 32px;
      }

      .content {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        grid-template-rows: 1fr;
      }

      .panel {
        min-height: 500px;
      }

    }

    /*
      Smaller mobile devices
    */
    @media (max-width: 480px) {

      .app {
        padding: 14px;
        gap: 14px;
      }

      header h1 {
        font-size: 1.2rem;
      }

      .content {
        gap: 14px;
      }

      textarea,
      .preview {
        padding: 14px;
        font-size: 0.95rem;
      }

    }

  </style>

</head>

<body>

  <main class="app">

```
<header>
  <h1>Live Typing</h1>
  <p>Whatever you type below will appear here instantly.</p>
</header>


<section class="content">

  <!-- Input Panel -->
  <div class="panel">

    <div class="panel-header">
      Type Here
    </div>

    <textarea
      id="typing-input"
      placeholder="Start typing here..."
      autofocus
    ></textarea>

  </div>


  <!-- Preview Panel -->
  <div class="panel">

    <div class="panel-header">
      Live Preview
    </div>

    <div
      id="typing-preview"
      class="preview placeholder"
    >
      Your typed text will appear here...
    </div>

  </div>

</section>


<div class="footer">
  <span id="character-count">0</span> characters
</div>
```

  </main>

  <script>

    const input = document.getElementById('typing-input');
    const preview = document.getElementById('typing-preview');
    const characterCount = document.getElementById('character-count');

    input.addEventListener('input', function () {

      const value = input.value;

      characterCount.textContent = value.length;

      if (value.length > 0) {

        preview.textContent = value;
        preview.classList.remove('placeholder');

      } else {

        preview.textContent = 'Your typed text will appear here...';
        preview.classList.add('placeholder');

      }

    });

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
def index():
    days = get_days()
    return render_template_string(
        TYPINGS_TEMPLATE,
        days=days,
        total=total_count(days),
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

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
