"""
╔══════════════════════════════════════════════════════════════╗
║     AI ANPR PROJECT — app.py                                 ║
║     github.com/godwin-stanes/AI_ANPR_PROJECT                 ║
╠══════════════════════════════════════════════════════════════╣
║  FOLDER STRUCTURE:                                           ║
║    proj1/                                                    ║
║    ├── app.py            ← this file                         ║
║    ├── index.html        ← dashboard (same folder)           ║
║    ├── whitelist.csv                                         ║
║    ├── blacklist.csv                                         ║
║    ├── vehicle_log.csv                                       ║
║    └── static/uploads/   ← auto-created                     ║
║                                                              ║
║  INSTALL:                                                    ║
║    pip install flask flask-cors opencv-python easyocr numpy  ║
║                                                              ║
║  RUN:   python app.py                                        ║
║  OPEN:  http://localhost:5000                                ║
╚══════════════════════════════════════════════════════════════╝
"""

# ── SSL fix for Windows Python 3.12+ ──────────────────────────
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import cv2
import numpy as np
import easyocr
import csv
import re
import os
import time
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# Flask app — no templates folder needed
# ══════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'))
CORS(app)

# ── Paths ─────────────────────────────────────────────────────
UPLOAD_FOLDER  = os.path.join(BASE_DIR, "static", "uploads")
WHITELIST_FILE = os.path.join(BASE_DIR, "whitelist.csv")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.csv")
LOG_FILE       = os.path.join(BASE_DIR, "vehicle_log.csv")
HTML_FILE      = os.path.join(BASE_DIR, "index.html")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Init CSV files ────────────────────────────────────────────
def init_csv(path, headers):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(headers)

init_csv(WHITELIST_FILE, ["plate", "owner", "added_date"])
init_csv(BLACKLIST_FILE, ["plate", "reason", "added_date"])
init_csv(LOG_FILE,       ["id", "plate", "status", "timestamp", "image", "source"])

# ── EasyOCR ───────────────────────────────────────────────────
print("\n" + "="*55)
print("  AI ANPR PROJECT STARTING...")
print("  Loading OCR model (first run ~200MB download)")
print("="*55)
reader = easyocr.Reader(['en'], gpu=False)
print("  ✓ OCR ready!\n")

# ══════════════════════════════════════════════════════════════
# CSV HELPERS
# ══════════════════════════════════════════════════════════════

def read_csv_plates(path):
    plates = set()
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                p = row.get("plate", "").strip().upper().replace(" ", "")
                if p:
                    plates.add(p)
    except Exception:
        pass
    return plates

def read_csv_rows(path):
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []

def append_csv_row(path, row_dict):
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row_dict.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row_dict)

def rewrite_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

# ══════════════════════════════════════════════════════════════
# IMAGE PROCESSING
# ══════════════════════════════════════════════════════════════

def detect_plate_region(img):
    try:
        gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur  = cv2.bilateralFilter(gray, 11, 17, 17)
        edges = cv2.Canny(blur, 30, 200)
        contours, _ = cv2.findContours(edges.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:30]
        for c in contours:
            peri   = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.018 * peri, True)
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(approx)
                if w > 0 and h > 0 and 1.5 < (w / float(h)) < 5.5 and w > 80:
                    return img[y:y+h, x:x+w]
    except Exception:
        pass
    return None

def clean_plate_text(results):
    if not results:
        return ""
    combined = " ".join([r[1] for r in results])
    cleaned  = re.sub(r'[^A-Z0-9 ]', '', combined.upper())
    pattern  = re.compile(r'[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{1,4}')
    match    = pattern.search(cleaned)
    if match:
        return re.sub(r'\s+', '', match.group())
    tokens = [t for t in cleaned.split() if len(t) >= 4]
    return max(tokens, key=len) if tokens else ""

def run_ocr(img):
    candidates = []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    variants = [
        gray,
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2),
        cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
    ]
    for v in variants:
        try:
            results = reader.readtext(v)
            plate   = clean_plate_text(results)
            if plate and len(plate) >= 5:
                candidates.append(plate)
        except Exception:
            continue

    if not candidates:
        return ""
    pat = re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$')
    for c in candidates:
        if pat.match(c):
            return c
    return candidates[0]

def check_lists(plate):
    """Returns: WHITELIST, BLACKLIST, or UNKNOWN"""
    if plate in read_csv_plates(BLACKLIST_FILE):
        return "BLACKLIST"
    if plate in read_csv_plates(WHITELIST_FILE):
        return "WHITELIST"
    return "UNKNOWN"

def log_detection(plate, status, image_filename="", source="esp32"):
    rows = read_csv_rows(LOG_FILE)
    entry = {
        "id":        len(rows) + 1,
        "plate":     plate,
        "status":    status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "image":     image_filename,
        "source":    source,
    }
    append_csv_row(LOG_FILE, entry)
    symbol = {"WHITELIST": "✓", "BLACKLIST": "✗", "UNKNOWN": "?"}
    print(f"  [{entry['timestamp']}]  {plate}  →  {symbol.get(status,'')} {status}")
    return entry

# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve index.html from the same folder as app.py"""
    if not os.path.exists(HTML_FILE):
        return (
            "<h2 style='font-family:monospace;color:red'>index.html not found!</h2>"
            f"<p style='font-family:monospace'>Place index.html in: <b>{BASE_DIR}</b></p>"
        ), 404
    return send_file(HTML_FILE)


@app.route("/static/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ── ESP32 detection ───────────────────────────────────────────
@app.route("/detect", methods=["POST"])
def detect():
    img_bytes = request.data
    if not img_bytes:
        return jsonify({"error": "NO_IMAGE"}), 400
    nparr = np.frombuffer(img_bytes, np.uint8)
    img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"error": "DECODE_ERROR"}), 400

    roi    = detect_plate_region(img)
    target = roi if roi is not None else img
    plate  = run_ocr(target)
    if not plate:
        return jsonify({"plate": "", "status": "NO_PLATE"}), 200

    status   = check_lists(plate)
    filename = f"{int(time.time())}_{plate}.jpg"
    cv2.imwrite(os.path.join(UPLOAD_FOLDER, filename), img)
    log_detection(plate, status, filename, "esp32")
    return jsonify({"plate": plate, "status": status}), 200


# ── Browser image upload test ─────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    if "image" not in request.files:
        return jsonify({"error": "No file"}), 400
    img_bytes = request.files["image"].read()
    nparr     = np.frombuffer(img_bytes, np.uint8)
    img       = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return jsonify({"error": "Cannot decode image"}), 400

    roi    = detect_plate_region(img)
    target = roi if roi is not None else img
    plate  = run_ocr(target)
    if not plate:
        return jsonify({"plate": "", "status": "NO_PLATE"}), 200

    status   = check_lists(plate)
    filename = f"{int(time.time())}_{plate}.jpg"
    cv2.imwrite(os.path.join(UPLOAD_FOLDER, filename), img)
    log_detection(plate, status, filename, "upload")
    return jsonify({"plate": plate, "status": status, "image": filename})


# ── OCR test with synthetic image ─────────────────────────────
@app.route("/test")
def test():
    img = np.ones((120, 480, 3), dtype=np.uint8) * 255
    cv2.rectangle(img, (2,2), (477,117), (20,20,20), 4)
    cv2.rectangle(img, (8,8), (471,35), (0,80,180), -1)
    cv2.putText(img, "IND", (200,28), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
    cv2.putText(img, "KL 07 CD 5678", (25,95), cv2.FONT_HERSHEY_DUPLEX, 1.8, (10,10,10), 3)
    plate  = run_ocr(img)
    status = check_lists(plate) if plate else "NO_PLATE"
    if plate:
        log_detection(plate, status, "", "test")
    return jsonify({"plate": plate or "NOT_DETECTED", "status": status})


# ── Log ───────────────────────────────────────────────────────
@app.route("/log")
def get_log():
    limit = request.args.get("limit", 100, type=int)
    rows  = read_csv_rows(LOG_FILE)
    rows.reverse()
    return jsonify(rows[:limit])


# ── Stats ─────────────────────────────────────────────────────
@app.route("/stats")
def get_stats():
    rows = read_csv_rows(LOG_FILE)
    total = len(rows)
    return jsonify({
        "total":     total,
        "whitelist": sum(1 for r in rows if r.get("status") == "WHITELIST"),
        "blacklist": sum(1 for r in rows if r.get("status") == "BLACKLIST"),
        "unknown":   sum(1 for r in rows if r.get("status") == "UNKNOWN"),
        "last_seen": rows[-1]["timestamp"] if rows else None,
    })


# ── Whitelist ─────────────────────────────────────────────────
@app.route("/whitelist")
def get_whitelist():
    return jsonify(read_csv_rows(WHITELIST_FILE))

@app.route("/whitelist/add", methods=["POST"])
def add_whitelist():
    data  = request.get_json(force=True) or {}
    plate = data.get("plate", "").upper().replace(" ", "")
    owner = data.get("owner", "")
    if not plate:
        return jsonify({"error": "No plate"}), 400
    if plate in read_csv_plates(WHITELIST_FILE):
        return jsonify({"status": "already_exists", "plate": plate})
    append_csv_row(WHITELIST_FILE, {
        "plate": plate, "owner": owner,
        "added_date": datetime.now().strftime("%Y-%m-%d")
    })
    return jsonify({"status": "added", "plate": plate})

@app.route("/whitelist/remove", methods=["POST"])
def remove_whitelist():
    data  = request.get_json(force=True) or {}
    plate = data.get("plate", "").upper().replace(" ", "")
    rows  = [r for r in read_csv_rows(WHITELIST_FILE) if r.get("plate") != plate]
    rewrite_csv(WHITELIST_FILE, ["plate", "owner", "added_date"], rows)
    return jsonify({"status": "removed", "plate": plate})


# ── Blacklist ─────────────────────────────────────────────────
@app.route("/blacklist")
def get_blacklist():
    return jsonify(read_csv_rows(BLACKLIST_FILE))

@app.route("/blacklist/add", methods=["POST"])
def add_blacklist():
    data   = request.get_json(force=True) or {}
    plate  = data.get("plate", "").upper().replace(" ", "")
    reason = data.get("reason", "")
    if not plate:
        return jsonify({"error": "No plate"}), 400
    if plate in read_csv_plates(BLACKLIST_FILE):
        return jsonify({"status": "already_exists", "plate": plate})
    append_csv_row(BLACKLIST_FILE, {
        "plate": plate, "reason": reason,
        "added_date": datetime.now().strftime("%Y-%m-%d")
    })
    return jsonify({"status": "added", "plate": plate})

@app.route("/blacklist/remove", methods=["POST"])
def remove_blacklist():
    data  = request.get_json(force=True) or {}
    plate = data.get("plate", "").upper().replace(" ", "")
    rows  = [r for r in read_csv_rows(BLACKLIST_FILE) if r.get("plate") != plate]
    rewrite_csv(BLACKLIST_FILE, ["plate", "reason", "added_date"], rows)
    return jsonify({"status": "removed", "plate": plate})


# ── Clear log ─────────────────────────────────────────────────
@app.route("/clear", methods=["POST"])
def clear_log():
    rewrite_csv(LOG_FILE, ["id", "plate", "status", "timestamp", "image", "source"], [])
    return jsonify({"status": "ok"})


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"  App      →  http://0.0.0.0:5000")
    print(f"  Dashboard→  http://localhost:5000")
    print(f"  Test OCR →  http://localhost:5000/test\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
