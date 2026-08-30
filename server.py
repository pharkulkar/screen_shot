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
#!/usr/bin/env python3
"""
screenshot-viewer server
========================
Serves a lightweight web gallery of all captured screenshots on:

    http://localhost:5000

Organised by date, newest first. Includes interactive hover actions:
Solution (OCR), Edit, and Delete.
"""
#!/usr/bin/env python3
"""
screenshot-viewer server
========================
Serves a lightweight web gallery of all captured screenshots on:

    http://localhost:5000

Organised by date, newest first. Includes interactive hover actions:
Solution (OCR), Edit (Crop/Draw with Save/Save As), and Delete.
"""

import argparse
import base64
import io
import json
import logging
import os
import queue
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from flask import (Flask, Response, abort, jsonify, render_template_string,
                   request, send_file)

# Try importing PIL for thumbnail/editing generation
try:
    from PIL import Image
except ImportError:
    Image = None

import easyocr
import numpy as np
from PIL import Image

# Initialize reader once globally at startup (loads weights into memory)
# 'en' for English. Set gpu=False if you don't have CUDA set up.
reader = easyocr.Reader(['en'], gpu=False)

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

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# ── Live-typing shared state (SSE broadcast) ──────────────────────────────────
_typing_lock     = threading.Lock()
_typing_text     = ""
_typing_listeners: list[queue.Queue] = []

def _broadcast(text: str) -> None:
    with _typing_lock:
        listeners = list(_typing_listeners)
    for q in listeners:
        try:
            q.put_nowait(text)
        except queue.Full:
            pass

# ── HTML Template with Hover Overlay, Cropping & Versioning ────────────────────

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
      position: relative;
      display: block;
    }
    .card:hover {
      border-color: #555;
      transform: translateY(-2px);
    }

    .card-thumb-wrapper {
      position: relative;
      width: 100%;
      height: 130px;
      overflow: hidden;
      cursor: pointer;
    }

    .card img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      background: #111;
    }

    /* Hover Overlay with Action Buttons */
    .card-actions {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      opacity: 0;
      transition: opacity 0.2s ease-in-out;
    }

    .card:hover .card-actions { opacity: 1; }

    .action-btn {
      background: #252525;
      border: 1px solid #444;
      color: #fff;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 0.75rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      transition: background 0.15s, border-color 0.15s;
    }

    .action-btn:hover { background: #383838; border-color: #666; }
    .action-btn.active { background: #0056b3; border-color: #007bff; }
    .action-btn.delete:hover { background: #a31515; border-color: #d32f2f; }

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

    /* Modal Base */
    .modal-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.92);
      z-index: 100;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 16px;
      padding: 24px;
    }
    .modal-overlay.open { display: flex; }

    .modal-close {
      position: fixed;
      top: 18px;
      right: 24px;
      font-size: 2rem;
      color: #aaa;
      cursor: pointer;
      line-height: 1;
      user-select: none;
    }
    .modal-close:hover { color: #fff; }

    /* Standard Lightbox */
    #lb img {
      max-width: 95vw;
      max-height: 88vh;
      border-radius: 6px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.6);
    }

    /* Solution Modal */
    .ocr-container {
      background: #181818;
      border: 1px solid #333;
      border-radius: 8px;
      width: 90%;
      max-width: 950px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .ocr-header {
      padding: 14px 18px;
      border-bottom: 1px solid #2a2a2a;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.9rem;
      font-weight: 600;
    }

    .ocr-version-select {
      background: #222;
      color: #fff;
      border: 1px solid #444;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 0.8rem;
    }

    .ocr-body { display: flex; flex: 1; min-height: 0; }

    .ocr-preview {
      width: 45%;
      background: #000;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 12px;
      border-right: 1px solid #2a2a2a;
    }

    .ocr-preview img {
      max-width: 100%;
      max-height: 60vh;
      object-fit: contain;
    }

    .ocr-result {
      width: 55%;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #141414;
    }

    .ocr-result textarea {
      flex: 1;
      width: 100%;
      min-height: 200px;
      background: #0a0a0a;
      border: 1px solid #2a2a2a;
      border-radius: 6px;
      color: #00ff66;
      font-family: monospace;
      padding: 12px;
      resize: none;
      font-size: 0.85rem;
    }

    /* Editor Modal */
    .editor-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 14px;
      background: #181818;
      padding: 20px;
      border-radius: 8px;
      border: 1px solid #333;
      max-width: 95vw;
      max-height: 90vh;
    }

    .toolbar {
      display: flex;
      gap: 10px;
      width: 100%;
      justify-content: center;
      align-items: center;
      border-bottom: 1px solid #2a2a2a;
      padding-bottom: 12px;
    }

    .canvas-wrapper {
      position: relative;
      overflow: auto;
      max-width: 85vw;
      max-height: 65vh;
      background: #000;
      border: 1px solid #333;
    }

    #edit-canvas { display: block; cursor: crosshair; }
  </style>
</head>
<body>

<header>
  <h1>Screenshots</h1>
  <span>{{ total }} screenshot{% if total != 1 %}s{% endif %} across {{ days|length }} day{% if days|length != 1 %}s{% endif %}</span>
</header>

{% if days %}
  {% for date, files in days %}
  <div class="day-group" id="group-{{ date }}">
    <div class="day-label">{{ date }}</div>
    <div class="grid">
      {% for f in files %}
      <div class="card" id="card-{{ date }}-{{ loop.index }}">
        <div class="card-thumb-wrapper" onclick="openLb('/img/{{ date }}/{{ f }}','{{ f }}')">
          <img src="/thumb/{{ date }}/{{ f }}" alt="{{ f }}" loading="lazy" />
          <div class="card-actions" onclick="event.stopPropagation();">
            <button class="action-btn" onclick="openSolution('{{ date }}', '{{ f }}')">⚡ Solution</button>
            <button class="action-btn" onclick="openEditor('{{ date }}', '{{ f }}')">✏️ Edit</button>
            <button class="action-btn delete" onclick="deleteImage('{{ date }}', '{{ f }}', 'card-{{ date }}-{{ loop.index }}')">🗑️</button>
          </div>
        </div>
        <div class="card-meta">{{ f | replace('screenshot-','') | replace('.png','') }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
  {% endfor %}
{% else %}
  <p class="empty">No screenshots yet. Trigger the daemon by pressing the hotkey sequence.</p>
{% endif %}

<!-- Lightbox Modal -->
<div id="lb" class="modal-overlay">
  <span class="modal-close" onclick="closeModal('lb')">&#x2715;</span>
  <img id="lb-img" src="" alt="" />
  <div id="lb-name" style="font-size:0.78rem; color:#666;"></div>
</div>

<!-- Solution/OCR Modal -->
<div id="ocr-modal" class="modal-overlay">
  <span class="modal-close" onclick="closeModal('ocr-modal')">&#x2715;</span>
  <div class="ocr-container">
    <div class="ocr-header">
      <div style="display:flex; align-items:center; gap:12px;">
        <span>OCR Solution</span>
        <select id="ocr-version-select" class="ocr-version-select" onchange="switchOcrVersion()"></select>
      </div>
      <button class="action-btn" onclick="copyOcrText()">📋 Copy Text</button>
    </div>
    <div class="ocr-body">
      <div class="ocr-preview">
        <img id="ocr-img" src="" alt="OCR Target" />
      </div>
      <div class="ocr-result">
        <div id="ocr-status" style="font-size:0.8rem; color:#888;">Processing Image...</div>
        <textarea id="ocr-output" readonly placeholder="Extracting text..."></textarea>
      </div>
    </div>
  </div>
</div>

<!-- Canvas Editor Modal -->
<div id="edit-modal" class="modal-overlay">
  <span class="modal-close" onclick="closeModal('edit-modal')">&#x2715;</span>
  <div class="editor-container">
    <div class="toolbar">
      <button id="mode-draw" class="action-btn active" onclick="setMode('draw')">✏️ Draw</button>
      <button id="mode-crop" class="action-btn" onclick="setMode('crop')">✂️ Crop Area</button>
      <button class="action-btn" onclick="applyCrop()">Apply Crop</button>
      <button class="action-btn" onclick="resetEditor()">↺ Reset Image</button>
    </div>
    <div class="canvas-wrapper">
      <canvas id="edit-canvas"></canvas>
    </div>
    <div style="display:flex; gap:12px;">
      <button class="action-btn" onclick="saveImage(false)">💾 Save</button>
      <button class="action-btn" onclick="saveImage(true)">➕ Save As New Version</button>
      <button class="action-btn delete" onclick="closeModal('edit-modal')">Cancel</button>
    </div>
  </div>
</div>

<script>
  function closeModal(id) { document.getElementById(id).classList.remove('open'); }

  function openLb(src, name) {
    document.getElementById('lb-img').src = src;
    document.getElementById('lb-name').textContent = name;
    document.getElementById('lb').classList.add('open');
  }

  // --- Solution (OCR) Functionality ---
  let currentOcrDate = '', currentOcrFile = '';

  async function openSolution(date, filename) {
    currentOcrDate = date;
    currentOcrFile = filename;
    const modal = document.getElementById('ocr-modal');
    const select = document.getElementById('ocr-version-select');
    
    modal.classList.add('open');
    select.innerHTML = '<option>Loading versions...</option>';

    // Fetch related versions of the image
    try {
      const res = await fetch(`/api/versions/${date}/${filename}`);
      const data = await res.json();
      select.innerHTML = '';
      if (data.versions && data.versions.length > 0) {
        data.versions.forEach(v => {
          const opt = document.createElement('option');
          opt.value = v;
          opt.textContent = v;
          if (v === filename) opt.selected = true;
          select.appendChild(opt);
        });
        select.style.display = 'inline-block';
      } else {
        select.style.display = 'none';
      }
    } catch(e) {
      select.style.display = 'none';
    }

    runOcr(date, filename);
  }

  function switchOcrVersion() {
    const selectedFile = document.getElementById('ocr-version-select').value;
    runOcr(currentOcrDate, selectedFile);
  }

  async function runOcr(date, filename) {
    const imgEl = document.getElementById('ocr-img');
    const outputEl = document.getElementById('ocr-output');
    const statusEl = document.getElementById('ocr-status');

    imgEl.src = `/img/${date}/${filename}`;
    outputEl.value = '';
    statusEl.textContent = 'Extracting text via OCR...';

    try {
      const res = await fetch('/api/ocr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, filename })
      });
      const data = await res.json();
      if (data.success) {
        outputEl.value = data.text || 'No text detected in image.';
        statusEl.textContent = 'Extraction Complete';
      } else {
        outputEl.value = '';
        statusEl.textContent = 'Error: ' + (data.error || 'Failed to process OCR.');
      }
    } catch (err) {
      statusEl.textContent = 'Network error running OCR.';
    }
  }

  function copyOcrText() {
    const text = document.getElementById('ocr-output').value;
    if (text) {
      navigator.clipboard.writeText(text);
      alert('Copied to clipboard!');
    }
  }

  // --- Delete Functionality ---
  async function deleteImage(date, filename, cardId) {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
      const res = await fetch(`/api/delete/${date}/${filename}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        document.getElementById(cardId).remove();
      } else {
        alert('Failed to delete image: ' + data.error);
      }
    } catch (err) {
      alert('Error connecting to backend.');
    }
  }

  // --- Canvas Editor with Drawing & Cropping ---
  let canvas, ctx, originalImage = null;
  let currentMode = 'draw'; // 'draw' | 'crop'
  let isDragging = false;
  let cropStart = { x: 0, y: 0 }, cropEnd = { x: 0, y: 0 };
  let currentEditDate = '', currentEditFile = '';

  function openEditor(date, filename) {
    currentEditDate = date;
    currentEditFile = filename;
    const modal = document.getElementById('edit-modal');
    canvas = document.getElementById('edit-canvas');
    ctx = canvas.getContext('2d');

    originalImage = new Image();
    originalImage.crossOrigin = 'anonymous';
    originalImage.onload = () => {
      resetEditor();
      modal.classList.add('open');
    };
    originalImage.src = `/img/${date}/${filename}`;

    setupCanvasEvents();
  }

  function resetEditor() {
    canvas.width = originalImage.width;
    canvas.height = originalImage.height;
    ctx.drawImage(originalImage, 0, 0);
    setMode('draw');
  }

  function setMode(mode) {
    currentMode = mode;
    document.getElementById('mode-draw').classList.toggle('active', mode === 'draw');
    document.getElementById('mode-crop').classList.toggle('active', mode === 'crop');
  }

  function getCanvasCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY
    };
  }

  let savedCanvasState = null;

  function setupCanvasEvents() {
    canvas.onmousedown = (e) => {
      isDragging = true;
      const pos = getCanvasCoords(e);
      if (currentMode === 'draw') {
        ctx.beginPath();
        ctx.moveTo(pos.x, pos.y);
      } else if (currentMode === 'crop') {
        cropStart = pos;
        cropEnd = pos;
        savedCanvasState = ctx.getImageData(0, 0, canvas.width, canvas.height);
      }
    };

    canvas.onmousemove = (e) => {
      if (!isDragging) return;
      const pos = getCanvasCoords(e);

      if (currentMode === 'draw') {
        ctx.lineTo(pos.x, pos.y);
        ctx.strokeStyle = '#ff0055';
        ctx.lineWidth = 4;
        ctx.stroke();
      } else if (currentMode === 'crop') {
        cropEnd = pos;
        ctx.putImageData(savedCanvasState, 0, 0);
        ctx.strokeStyle = '#007bff';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 6]);
        ctx.strokeRect(cropStart.x, cropStart.y, cropEnd.x - cropStart.x, cropEnd.y - cropStart.y);
        ctx.setLineDash([]);
      }
    };

    canvas.onmouseup = () => { isDragging = false; };
  }

  function applyCrop() {
    if (currentMode !== 'crop') return;
    const x = Math.min(cropStart.x, cropEnd.x);
    const y = Math.min(cropStart.y, cropEnd.y);
    const w = Math.abs(cropEnd.x - cropStart.x);
    const h = Math.abs(cropEnd.y - cropStart.y);

    if (w < 10 || h < 10) {
      alert('Please select a valid area to crop.');
      return;
    }

    const croppedData = ctx.getImageData(x, y, w, h);
    canvas.width = w;
    canvas.height = h;
    ctx.putImageData(croppedData, 0, 0);
    setMode('draw');
  }

  async function saveImage(saveAsNew) {
    const dataUrl = canvas.toDataURL('image/png');
    try {
      const res = await fetch('/api/save-edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: currentEditDate,
          filename: currentEditFile,
          image: dataUrl,
          save_as_new: saveAsNew
        })
      });
      const data = await res.json();
      if (data.success) {
        alert(saveAsNew ? `Saved as new version: ${data.filename}` : 'Saved successfully!');
        location.reload();
      } else {
        alert('Error saving image: ' + data.error);
      }
    } catch (e) {
      alert('Error connecting to backend server.');
    }
  }

  // Backdrop / ESC Key Handler
  document.querySelectorAll('.modal-overlay').forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.remove('open');
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
    }
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
    html, body {
      margin: 0; padding: 0; background: transparent !important;
      width: 100%; height: 100%; overflow-y: auto !important;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      user-select: none; -webkit-app-region: drag;
    }
    .app { width: 100%; min-height: 100vh; padding: 24px; display: flex; flex-direction: column; gap: 20px; }
    header { padding-bottom: 16px; border-bottom: 1px solid #2a2a2a; }
    header h1 { font-size: 1.4rem; font-weight: 600; color: #ffffff; margin-bottom: 5px; }
    header p { font-size: 0.85rem; color: #FFF; }
    .workspace { flex: 1; display: flex; flex-direction: column; gap: 20px; min-height: 0; }
    .panel {
      background: rgba(0,0,0,0.2); border: 1px solid #2a2a2a; border-radius: 12px;
      display: flex; flex-direction: column; min-height: 0;
      -webkit-app-region: no-drag !important; pointer-events: auto !important;
      overflow-y: auto !important;
    }
    .input-panel { min-height: 180px; height: 300px; max-height: 70vh; }
    .panel-header {
      min-height: 48px; padding: 12px 16px; border-bottom: 1px solid #2a2a2a;
      display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-shrink: 0;
    }
    .panel-title { font-size: 0.78rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: #FFF; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #444; transition: background 0.3s; flex-shrink: 0; }
    .status-dot.connected { background: #4caf50; }
    .status-dot.error { background: #f44336; }
    .collapse-button {
      border: 1px solid #333; background: #222; color: #aaa; width: 30px; height: 30px;
      border-radius: 6px; cursor: pointer; font-size: 1rem; line-height: 1; transition: background 0.15s, color 0.15s;
    }
    .collapse-button:hover { background: #2a2a2a; color: #fff; }
    .input-wrapper { flex: 1; min-height: 0; display: flex; }
    textarea {
      width: 100%; height: 100%; resize: vertical; border: none; outline: none;
      background: transparent; color: #f0f0f0; padding: 18px; font-family: inherit;
      font-size: 1rem; line-height: 1.6;
    }
    textarea::placeholder { color: #555; }
    .resize-handle { height: 10px; cursor: ns-resize; background: transparent; flex-shrink: 0; position: relative; }
    .resize-handle::after {
      content: ""; width: 40px; height: 4px; border-radius: 10px; background: #3a3a3a;
      position: absolute; left: 50%; top: 3px; transform: translateX(-50%);
    }
    .preview-panel { flex: 1; min-height: 250px; }
    .preview {
      flex: 1; min-height: 0; padding: 22px; overflow-y: auto; font-size: 1rem;
      line-height: 1.7; color: #f0f0f0; white-space: pre-wrap; word-break: break-word;
    }
    .placeholder { color: #555; }
    .input-panel.collapsed { height: 48px !important; min-height: 48px; }
    .input-panel.collapsed .input-wrapper, .input-panel.collapsed .resize-handle { display: none; }
    .input-panel.collapsed .collapse-button { transform: rotate(180deg); }
    .footer { text-align: right; font-size: 0.75rem; color: #555; flex-shrink: 0; }
    #overlay-card {
      width: 100%; height: 100%; box-sizing: border-box; background: rgba(20, 20, 30, 0.65);
      backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px; padding: 16px; color: white; display: flex; flex-direction: column;
      justify-content: space-between;
    }
  </style>
</head>
<body>
<div id="overlay-card">
  <main class="app">
    <header>
      <h1>Live Typing</h1>
      <p>Type in the editor below — the preview syncs to every connected device.</p>
    </header>
    <section class="workspace">
      <div class="panel input-panel" id="input-panel">
        <div class="panel-header">
          <span class="panel-title">Type Here</span>
          <button class="collapse-button" id="collapse-button" type="button" title="Collapse input" aria-label="Collapse input">&#9650;</button>
        </div>
        <div class="input-wrapper">
          <textarea id="typing-input" placeholder="Start typing here..." autofocus></textarea>
        </div>
        <div class="resize-handle" id="resize-handle" title="Drag to resize"></div>
      </div>
      <div class="panel preview-panel">
        <div class="panel-header">
          <span class="panel-title">Live Preview</span>
          <span class="status-dot" id="status-dot" title="SSE connection status"></span>
        </div>
        <div id="typing-preview" class="preview placeholder">Your typed text will appear here...</div>
      </div>
    </section>
    <div class="footer"><span id="character-count">0</span> characters</div>
  </main>
</div>
  <script>
    const input = document.getElementById('typing-input');
    const preview = document.getElementById('typing-preview');
    const charCount = document.getElementById('character-count');
    const inputPanel = document.getElementById('input-panel');
    const collapseButton = document.getElementById('collapse-button');
    const resizeHandle = document.getElementById('resize-handle');
    const statusDot = document.getElementById('status-dot');

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
        try {
          const value = JSON.parse(e.data);
          setPreview(value);
          if (document.activeElement !== input) input.value = value;
        } catch (_) {}
      });
      es.addEventListener('open', function () { statusDot.className = 'status-dot connected'; });
      es.addEventListener('error', function () {
        statusDot.className = 'status-dot error';
        es.close();
        setTimeout(connectSSE, 2000);
      });
    }
    connectSSE();

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

    collapseButton.addEventListener('click', function () {
      inputPanel.classList.toggle('collapsed');
      const collapsed = inputPanel.classList.contains('collapsed');
      collapseButton.innerHTML = collapsed ? '&#9660;' : '&#9650;';
    });

    let isResizing = false, startY = 0, startHeight = 0;
    resizeHandle.addEventListener('mousedown', function (e) {
      if (inputPanel.classList.contains('collapsed')) return;
      isResizing = true; startY = e.clientY; startHeight = inputPanel.getBoundingClientRect().height;
      document.body.style.cursor = 'ns-resize'; document.body.style.userSelect = 'none';
    });
    document.addEventListener('mousemove', function (e) {
      if (!isResizing) return;
      const h = Math.max(120, Math.min(startHeight + e.clientY - startY, window.innerHeight * 0.75));
      inputPanel.style.height = h + 'px';
    });
    document.addEventListener('mouseup', function () {
      if (!isResizing) return;
      isResizing = false; document.body.style.cursor = ''; document.body.style.userSelect = '';
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
    candidate = (SHOTS_DIR / date / filename).resolve()
    if not str(candidate).startswith(str(SHOTS_DIR.resolve())):
        abort(403)
    if not candidate.exists():
        abort(404)
    return candidate

def get_incremental_filename(directory: Path, base_filename: str) -> str:
    """Generate incremental file name (e.g. screenshot_v1.png, screenshot_v2.png)."""
    name_stem = Path(base_filename).stem
    # Strip existing version suffixes like _v1, _v2 if present
    base_stem = re.sub(r'_v\d+$', '', name_stem)
    
    version = 1
    while True:
        new_name = f"{base_stem}_v{version}.png"
        if not (directory / new_name).exists():
            return new_name
        version += 1

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
    global _typing_text
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    with _typing_lock:
        _typing_text = text
    _broadcast(text)
    return "", 204

@app.route("/typings/stream")
def typings_stream():
    q: queue.Queue = queue.Queue(maxsize=64)
    with _typing_lock:
        initial = _typing_text
        _typing_listeners.append(q)

    def generate():
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
    path = safe_path(date, filename)
    return send_file(path, mimetype="image/png")

@app.route("/thumb/<date>/<filename>")
def thumbnail(date: str, filename: str):
    path = safe_path(date, filename)
    try:
        if Image:
            with Image.open(path) as img:
                img.thumbnail((440, 280))
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                buf.seek(0)
                return send_file(buf, mimetype="image/png")
    except Exception:
        pass
    return send_file(path, mimetype="image/png")

# ── Action APIs ──────────────────────────────────────────────────────────────

@app.route("/api/delete/<date>/<filename>", methods=["DELETE"])
def api_delete(date: str, filename: str):
    try:
        path = safe_path(date, filename)
        path.unlink()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/versions/<date>/<filename>")
def api_versions(date: str, filename: str):
    """List all related image version files for a given screenshot."""
    day_dir = (SHOTS_DIR / date).resolve()
    if not day_dir.exists():
        return jsonify({"versions": []})
    
    base_stem = re.sub(r'_v\d+$', '', Path(filename).stem)
    versions = sorted([
        f.name for f in day_dir.iterdir()
        if f.suffix == ".png" and (f.stem == base_stem or f.stem.startswith(base_stem + "_v"))
    ])
    return jsonify({"versions": versions})

@app.route("/api/ocr", methods=["POST"])
def api_ocr():
    data = request.get_json() or {}
    date = data.get("date")
    filename = data.get("filename")

    if not date or not filename:
        return jsonify({"success": False, "error": "Missing params"}), 400

    path = safe_path(date, filename)

    try:
        # Load image with PIL and convert to RGB numpy array for clean channel handling
        with Image.open(path) as img:
            img_rgb = img.convert("RGB")
            img_np = np.array(img_rgb)

        # detail=0 returns a clean list of strings directly: ['Line 1', 'Line 2', ...]
        # paragraph=True groups nearby lines together into natural paragraphs
        results = reader.readtext(img_np, detail=0, paragraph=False)

        extracted_text = "\n".join(results).strip()

        return jsonify({
            "success": True,
            "text": extracted_text if extracted_text else "No text detected in image."
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"OCR Error: {str(e)}"}), 500

@app.route("/api/save-edit", methods=["POST"])
def api_save_edit():
    data = request.get_json() or {}
    date = data.get("date")
    filename = data.get("filename")
    image_data = data.get("image")
    save_as_new = data.get("save_as_new", False)

    if not date or not filename or not image_data:
        return jsonify({"success": False, "error": "Invalid request parameters"}), 400

    day_dir = (SHOTS_DIR / date).resolve()
    
    if save_as_new:
        save_filename = get_incremental_filename(day_dir, filename)
        target_path = day_dir / save_filename
    else:
        save_filename = filename
        target_path = safe_path(date, filename)

    try:
        header, encoded = image_data.split(",", 1)
        file_bytes = base64.b64decode(encoded)
        with open(target_path, "wb") as f:
            f.write(file_bytes)
        return jsonify({"success": True, "filename": save_filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── Entry point ───────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"

def main():
    parser = argparse.ArgumentParser(description="Screenshot viewer server")
    parser.add_argument("--port", type=int, default=3000, help="Port (default: 3000)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    args = parser.parse_args()

    local_ip = get_local_ip()

    print()
    print("  Screenshot viewer with Crop, Incremental Versioning & OCR")
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