"""Reviewer UI: local Flask server for OCR pipeline review tasks.

Two modes (both via the browser at http://127.0.0.1:5050):
  - Escalated pages: draw layout zone annotations over raw page images,
    save as JSON for pipeline override so those pages stop being skipped.
  - (future) Word review: resolve disputed OCR readings from the WCT queue.

Annotation JSON is saved to:
  reports/layout-annotations/<vol>/<page_num>.json

The pipeline checks for this file in wct_builder.py before running
detect_columns(), so annotating a page is enough to unblock it.

Usage:
    py -3 build/tools/ocr_pipeline/reviewer_server.py [--port 5050]

Then open http://127.0.0.1:5050 in a browser.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ESCALATED_DIR = _REPO_ROOT / "reports" / "escalated-pages"
_ANNOTATION_DIR = _REPO_ROOT / "reports" / "layout-annotations"
_IMAGE_ROOT = _REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_escalated_pages() -> list[dict]:
    """Return sorted list of page info dicts from escalated-pages dir."""
    pages = []
    if not _ESCALATED_DIR.exists():
        return pages
    for p in sorted(_ESCALATED_DIR.glob("*.png")):
        stem = p.stem  # e.g. "vol_01_page_0060"
        idx = stem.find("_page_")
        if idx == -1:
            continue
        vol = stem[:idx]           # "vol_01"
        page_num = "page_" + stem[idx + 6:]  # "page_0060"
        ann_path = _ANNOTATION_DIR / vol / f"{page_num}.json"
        img_path = _IMAGE_ROOT / vol / f"{page_num}.jpg"
        pages.append({
            "vol": vol,
            "page_num": page_num,
            "page_id": f"{vol}/{page_num}",
            "annotated": ann_path.exists(),
            "image_exists": img_path.exists(),
        })
    return pages


def _check_path(resolved: Path, base: Path) -> None:
    """Abort 400 if resolved path escapes base — guards against path traversal."""
    try:
        resolved.relative_to(base)
    except ValueError:
        abort(400, "Invalid path parameters")


def _annotation_path(vol: str, page_num: str) -> Path:
    resolved = (_ANNOTATION_DIR / vol / f"{page_num}.json").resolve()
    _check_path(resolved, _ANNOTATION_DIR.resolve())
    return resolved


def _image_path(vol: str, page_num: str) -> Path:
    resolved = (_IMAGE_ROOT / vol / f"{page_num}.jpg").resolve()
    _check_path(resolved, _IMAGE_ROOT.resolve())
    return resolved


def _comparison_path(vol: str, page_num: str) -> Path:
    resolved = (_ESCALATED_DIR / f"{vol}_{page_num}.png").resolve()
    _check_path(resolved, _ESCALATED_DIR.resolve())
    return resolved


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_HOME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OCD Reviewer</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #1a1a2e; color: #eee; }
  h1 { padding: 16px 24px; margin: 0; background: #16213e; font-size: 1.2rem; letter-spacing: 1px; }
  .subtitle { padding: 0 24px 12px; font-size: 0.85rem; color: #aaa; background: #16213e; }
  .stats { padding: 12px 24px; background: #0f3460; font-size: 0.9rem; }
  table { width: 100%; border-collapse: collapse; margin: 0; }
  th { padding: 10px 16px; text-align: left; background: #16213e; font-size: 0.8rem;
       text-transform: uppercase; letter-spacing: 1px; color: #aaa; }
  td { padding: 10px 16px; border-bottom: 1px solid #222; vertical-align: middle; }
  tr:hover td { background: #1e2a40; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; }
  .badge-done { background: #1a4a2e; color: #4caf50; }
  .badge-pending { background: #3a2a1a; color: #ff9800; }
  .badge-no-image { background: #3a1a1a; color: #f44336; }
  a.btn { display: inline-block; padding: 4px 12px; border-radius: 4px; text-decoration: none;
          font-size: 0.8rem; margin-right: 4px; }
  a.btn-primary { background: #0f3460; color: #e0e0e0; }
  a.btn-primary:hover { background: #1a4a80; }
  a.btn-secondary { background: #2a2a2a; color: #ccc; }
  a.btn-secondary:hover { background: #3a3a3a; }
  .page-id { font-family: monospace; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>OCD Reviewer -- Escalated Pages</h1>
<div class="subtitle">Pages skipped by the layout detection step. Draw zone annotations to unblock them.</div>
<div class="stats">
  {{ annotated }} / {{ total }} annotated
  &nbsp;&nbsp;|&nbsp;&nbsp;
  {{ total - annotated }} remaining
</div>
<table>
  <thead>
    <tr>
      <th>Page</th>
      <th>Status</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
    {% for p in pages %}
    <tr>
      <td class="page-id">{{ p.page_id }}</td>
      <td>
        {% if not p.image_exists %}
          <span class="badge badge-no-image">no image</span>
        {% elif p.annotated %}
          <span class="badge badge-done">annotated</span>
        {% else %}
          <span class="badge badge-pending">pending</span>
        {% endif %}
      </td>
      <td>
        <a class="btn btn-primary" href="{{ url_for('annotate', vol=p.vol, page_num=p.page_num) }}">
          Annotate
        </a>
        {% if p.image_exists %}
        <a class="btn btn-secondary"
           href="{{ url_for('comparison', vol=p.vol, page_num=p.page_num) }}"
           target="_blank">
          Comparison
        </a>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</body>
</html>"""


_ANNOTATE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Annotate {{ page_id }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee;
         display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  header { display: flex; align-items: center; gap: 12px; padding: 8px 16px;
           background: #16213e; flex-shrink: 0; }
  header h1 { font-size: 1rem; font-family: monospace; }
  .main { display: flex; flex: 1; overflow: hidden; }
  .canvas-wrap { flex: 1; overflow: auto; padding: 12px; background: #111; }
  #image-container { position: relative; display: inline-block; }
  #page-image { display: block; max-width: 800px; }
  #canvas { position: absolute; top: 0; left: 0; cursor: crosshair; }
  .panel { width: 280px; flex-shrink: 0; background: #16213e; overflow-y: auto;
           display: flex; flex-direction: column; }
  .panel-section { padding: 12px; border-bottom: 1px solid #2a2a40; }
  .panel-section h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px;
                      color: #aaa; margin-bottom: 8px; }
  .zone-item { padding: 6px 8px; border-radius: 4px; margin-bottom: 4px;
               cursor: pointer; font-family: monospace; font-size: 0.8rem;
               border: 2px solid transparent; }
  .zone-item:hover { background: #1e2a40; }
  .zone-item.selected { border-color: #ffd700; }
  .zone-swatch { display: inline-block; width: 10px; height: 10px;
                 border-radius: 2px; margin-right: 4px; vertical-align: middle; }
  select, input[type=number] {
    width: 100%; padding: 4px 8px; background: #0f3460; color: #eee;
    border: 1px solid #2a4a6a; border-radius: 4px; margin-top: 4px;
    font-size: 0.9rem;
  }
  label { font-size: 0.8rem; color: #aaa; display: block; margin-top: 8px; }
  button { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer;
           font-size: 0.85rem; margin-top: 6px; margin-right: 4px; }
  .btn-draw { background: #0f3460; color: #eee; }
  .btn-draw.active { background: #00aaff; color: #000; }
  .btn-delete { background: #4a1a1a; color: #f44336; }
  .btn-save { background: #1a4a2e; color: #4caf50; font-weight: bold;
              width: 100%; margin-top: 0; }
  .btn-back { background: #2a2a2a; color: #ccc; text-decoration: none;
              padding: 5px 12px; border-radius: 4px; font-size: 0.85rem; }
  .status { font-size: 0.8rem; padding: 8px; border-radius: 4px; margin-top: 8px;
            display: none; }
  .status.ok { background: #1a4a2e; color: #4caf50; display: block; }
  .status.err { background: #4a1a1a; color: #f44336; display: block; }
  .hint { font-size: 0.75rem; color: #666; margin-top: 4px; }
</style>
</head>
<body>
<header>
  <a class="btn-back" href="{{ url_for('index') }}">&larr; Back</a>
  <h1>{{ page_id }}</h1>
  <a href="{{ url_for('comparison', vol=vol, page_num=page_num) }}"
     target="_blank" style="font-size:0.8rem; color:#aaa;">View comparison &rarr;</a>
</header>
<div class="main">
  <!-- Image + canvas -->
  <div class="canvas-wrap">
    <div id="image-container">
      <img id="page-image" src="{{ url_for('serve_image', vol=vol, page_num=page_num) }}"
           alt="{{ page_id }}">
      <canvas id="canvas"></canvas>
    </div>
  </div>
  <!-- Side panel -->
  <div class="panel">
    <div class="panel-section">
      <h2>Zones</h2>
      <div id="zone-list"></div>
      <button class="btn-draw" id="draw-btn" onclick="toggleDraw()">Draw zone</button>
      <p class="hint">Click and drag on the image to draw a zone.</p>
    </div>
    <div class="panel-section" id="zone-editor" style="display:none;">
      <h2>Selected zone</h2>
      <label>Role
        <select id="sel-role" onchange="updateSelectedZone()">
          <option value="body">body</option>
          <option value="heading">heading</option>
          <option value="headword">headword</option>
          <option value="header">header</option>
          <option value="full_width">full_width</option>
          <option value="ignore">ignore</option>
        </select>
      </label>
      <label>Column count
        <select id="sel-cols" onchange="updateSelectedZone()">
          <option value="1">1</option>
          <option value="2" selected>2</option>
          <option value="3">3</option>
        </select>
      </label>
      <label>Reading order
        <input type="number" id="inp-order" min="0" onchange="updateSelectedZone()">
      </label>
      <button class="btn-delete" onclick="deleteSelectedZone()">Delete zone</button>
    </div>
    <div class="panel-section" style="flex:1;">
      <button class="btn-save" onclick="saveAnnotation()">Save annotation</button>
      <div id="save-status" class="status"></div>
    </div>
  </div>
</div>

<script>
// --- Page data injected from server ---
const NATIVE_W = {{ native_w }};
const NATIVE_H = {{ native_h }};
const VOL = {{ vol | tojson }};
const PAGE_NUM = {{ page_num | tojson }};
const INITIAL = {{ initial | tojson }};

// Role -> display color
const ROLE_COLORS = {
  body:       '#2980b9',
  heading:    '#e67e22',
  headword:   '#c0392b',
  header:     '#9b59b6',
  full_width: '#27ae60',
  ignore:     '#7f8c8d',
};
</script>

{% raw %}
<script>
let zones = [];
let selectedIdx = -1;
let drawMode = false;
let drawing = false;
let dragStart = {x: 0, y: 0};

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const img = document.getElementById('page-image');
const drawBtn = document.getElementById('draw-btn');

// --- Scale helpers ---
function getScale() {
  // Returns native pixels per CSS pixel
  return canvas.width ? NATIVE_W / canvas.width : 1;
}

function toCss(nativePx) { return nativePx / getScale(); }
function toNative(cssPx)  { return Math.round(cssPx * getScale()); }

// --- Canvas sizing ---
function resizeCanvas() {
  if (!img.naturalWidth) return;
  const cw = img.offsetWidth;
  const ch = img.offsetHeight;
  if (canvas.width !== cw || canvas.height !== ch) {
    canvas.width = cw;
    canvas.height = ch;
    canvas.style.width  = cw + 'px';
    canvas.style.height = ch + 'px';
  }
  redraw();
}

img.onload = function () {
  resizeCanvas();
  loadInitial();
};
if (img.complete && img.naturalWidth) {
  resizeCanvas();
  loadInitial();
}
window.addEventListener('resize', resizeCanvas);

// --- Load initial annotation ---
function loadInitial() {
  if (INITIAL && INITIAL.zones && INITIAL.zones.length) {
    zones = INITIAL.zones.map((z, i) => Object.assign({}, z));
    renderZoneList();
    redraw();
  }
}

// --- Draw mode toggle ---
function toggleDraw() {
  drawMode = !drawMode;
  drawBtn.textContent = drawMode ? 'Cancel draw' : 'Draw zone';
  drawBtn.classList.toggle('active', drawMode);
  canvas.style.cursor = drawMode ? 'crosshair' : 'default';
}

// --- Mouse events for drawing ---
canvas.addEventListener('mousedown', function(e) {
  if (drawMode) {
    drawing = true;
    dragStart = {x: e.offsetX, y: e.offsetY};
    return;
  }
  // Selection click
  const scale = getScale();
  const nx = e.offsetX * scale;
  const ny = e.offsetY * scale;
  let hit = -1;
  for (let i = zones.length - 1; i >= 0; i--) {
    const b = zones[i].bbox_native;
    if (nx >= b.x && nx <= b.x + b.w && ny >= b.y && ny <= b.y + b.h) {
      hit = i;
      break;
    }
  }
  selectZone(hit);
});

canvas.addEventListener('mousemove', function(e) {
  if (!drawing) return;
  redraw();
  const x0 = Math.min(dragStart.x, e.offsetX);
  const y0 = Math.min(dragStart.y, e.offsetY);
  const w0 = Math.abs(e.offsetX - dragStart.x);
  const h0 = Math.abs(e.offsetY - dragStart.y);
  ctx.strokeStyle = '#00aaff';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 3]);
  ctx.strokeRect(x0, y0, w0, h0);
  ctx.setLineDash([]);
});

canvas.addEventListener('mouseup', function(e) {
  if (!drawing) return;
  drawing = false;
  const x0 = Math.min(dragStart.x, e.offsetX);
  const y0 = Math.min(dragStart.y, e.offsetY);
  const w0 = Math.abs(e.offsetX - dragStart.x);
  const h0 = Math.abs(e.offsetY - dragStart.y);
  if (w0 < 5 || h0 < 5) { redraw(); return; }  // too small

  const scale = getScale();
  zones.push({
    zone_id: 'z' + (zones.length + 1),
    role: 'body',
    column_count: 2,
    reading_order: zones.length,
    bbox_native: {
      x: Math.round(x0 * scale),
      y: Math.round(y0 * scale),
      w: Math.round(w0 * scale),
      h: Math.round(h0 * scale),
    }
  });
  // Exit draw mode after each zone
  drawMode = false;
  drawBtn.textContent = 'Draw zone';
  drawBtn.classList.remove('active');
  canvas.style.cursor = 'default';

  selectZone(zones.length - 1);
  renderZoneList();
  redraw();
});

// --- Redraw ---
function redraw() {
  if (!canvas.width) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const scale = getScale();
  zones.forEach(function(z, i) {
    const b = z.bbox_native;
    const cx = b.x / scale;
    const cy = b.y / scale;
    const cw = b.w / scale;
    const ch = b.h / scale;
    const col = ROLE_COLORS[z.role] || '#888';

    ctx.fillStyle = col + '33';
    ctx.fillRect(cx, cy, cw, ch);

    ctx.strokeStyle = (i === selectedIdx) ? '#ffd700' : col;
    ctx.lineWidth   = (i === selectedIdx) ? 3 : 2;
    ctx.strokeRect(cx, cy, cw, ch);

    ctx.fillStyle = col;
    ctx.font = 'bold 12px monospace';
    ctx.fillText(
      z.zone_id + ' ' + z.role + ' ' + z.column_count + 'col',
      cx + 4, cy + 15
    );
  });
}

// --- Zone list ---
function renderZoneList() {
  const el = document.getElementById('zone-list');
  if (!zones.length) {
    el.innerHTML = '<p style="font-size:0.8rem;color:#666;">No zones yet.</p>';
    return;
  }
  el.innerHTML = zones.map(function(z, i) {
    const col = ROLE_COLORS[z.role] || '#888';
    const sel = (i === selectedIdx) ? ' selected' : '';
    return '<div class="zone-item' + sel + '" onclick="selectZone(' + i + ')">'
      + '<span class="zone-swatch" style="background:' + col + '"></span>'
      + z.zone_id + ' &mdash; ' + z.role + ' (' + z.column_count + ' col)'
      + '</div>';
  }).join('');
}

// --- Selection ---
function selectZone(idx) {
  selectedIdx = idx;
  renderZoneList();
  redraw();
  const editor = document.getElementById('zone-editor');
  if (idx < 0 || idx >= zones.length) {
    editor.style.display = 'none';
    return;
  }
  editor.style.display = 'block';
  const z = zones[idx];
  document.getElementById('sel-role').value  = z.role;
  document.getElementById('sel-cols').value  = String(z.column_count);
  document.getElementById('inp-order').value = String(z.reading_order);
}

function updateSelectedZone() {
  if (selectedIdx < 0 || selectedIdx >= zones.length) return;
  const z = zones[selectedIdx];
  z.role          = document.getElementById('sel-role').value;
  z.column_count  = parseInt(document.getElementById('sel-cols').value, 10);
  z.reading_order = parseInt(document.getElementById('inp-order').value, 10);
  renderZoneList();
  redraw();
}

function deleteSelectedZone() {
  if (selectedIdx < 0 || selectedIdx >= zones.length) return;
  zones.splice(selectedIdx, 1);
  // Reassign zone IDs
  zones.forEach(function(z, i) { z.zone_id = 'z' + (i + 1); });
  selectZone(-1);
  renderZoneList();
  redraw();
}

// --- Save ---
function saveAnnotation() {
  const statusEl = document.getElementById('save-status');
  statusEl.className = 'status';
  statusEl.textContent = '';

  const payload = {
    page_id: VOL + '/' + PAGE_NUM,
    vol: VOL,
    page_num: PAGE_NUM,
    source: 'manual',
    image_native_w: NATIVE_W,
    image_native_h: NATIVE_H,
    zones: zones,
  };

  fetch('/api/annotations/' + VOL + '/' + PAGE_NUM, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (data.ok) {
      statusEl.className = 'status ok';
      statusEl.textContent = 'Saved (' + zones.length + ' zone' + (zones.length === 1 ? '' : 's') + ')';
    } else {
      statusEl.className = 'status err';
      statusEl.textContent = 'Error: ' + (data.error || 'unknown');
    }
  })
  .catch(function(err) {
    statusEl.className = 'status err';
    statusEl.textContent = 'Network error: ' + err.message;
  });
}
</script>
{% endraw %}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    pages = _scan_escalated_pages()
    annotated = sum(1 for p in pages if p["annotated"])
    return render_template_string(
        _HOME_TEMPLATE,
        pages=pages,
        total=len(pages),
        annotated=annotated,
    )


@app.route("/annotate/<vol>/<page_num>")
def annotate(vol: str, page_num: str):
    img_path = _image_path(vol, page_num)
    if not img_path.exists():
        abort(404, f"Image not found: {img_path}")

    # Read native dimensions via PIL
    try:
        from PIL import Image as PILImage
        with PILImage.open(img_path) as im:
            native_w, native_h = im.size
    except ImportError:
        # PIL absent — fall back to SH default; actual dimensions may differ
        native_w, native_h = 5034, 6959
    except Exception as exc:
        abort(500, f"Could not read image dimensions: {exc}")

    # Load existing annotation if present
    ann_path = _annotation_path(vol, page_num)
    initial = {}
    if ann_path.exists():
        try:
            initial = json.loads(ann_path.read_text(encoding="utf-8"))
        except Exception:
            initial = {}

    return render_template_string(
        _ANNOTATE_TEMPLATE,
        page_id=f"{vol}/{page_num}",
        vol=vol,
        page_num=page_num,
        native_w=native_w,
        native_h=native_h,
        initial=initial,
    )


@app.route("/image/<vol>/<page_num>")
def serve_image(vol: str, page_num: str):
    img_path = _image_path(vol, page_num)
    if not img_path.exists():
        abort(404)
    return send_file(img_path, mimetype="image/jpeg")


@app.route("/comparison/<vol>/<page_num>")
def comparison(vol: str, page_num: str):
    comp_path = _comparison_path(vol, page_num)
    if not comp_path.exists():
        abort(404, f"Comparison image not found: {comp_path}")
    return send_file(comp_path, mimetype="image/png")


@app.get("/api/annotations/<vol>/<page_num>")
def get_annotation(vol: str, page_num: str):
    ann_path = _annotation_path(vol, page_num)
    if not ann_path.exists():
        return jsonify({"ok": True, "exists": False, "data": None})
    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        return jsonify({"ok": True, "exists": True, "data": data})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/api/annotations/<vol>/<page_num>")
def save_annotation(vol: str, page_num: str):
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "No JSON payload"}), 400
    if not isinstance(payload.get("zones"), list):
        return jsonify({"ok": False, "error": "zones must be a list"}), 400
    try:
        ann_path = _annotation_path(vol, page_num)
        _write_atomic(ann_path, payload)
        return jsonify({"ok": True, "path": str(ann_path.relative_to(_REPO_ROOT))})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="OCD reviewer UI")
    parser.add_argument("--port", type=int, default=5050, help="Port to listen on")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    print(f"Reviewer UI starting at http://{args.host}:{args.port}")
    print(f"Annotation output: {_ANNOTATION_DIR}")
    print("Press Ctrl+C to stop.")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
