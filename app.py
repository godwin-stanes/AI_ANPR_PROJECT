"""
=============================================================
  SMART GATE - Flask Server
  Wires IR trigger → DroidCam capture → OCR → allow/deny

  Flow:
    ESP32 IR sensor fires
      → POST /ir_trigger
        → grab frame from DroidCam
        → run ANPR (plate detect + OCR)
        → check whitelist / blacklist
        → respond ALLOW or DENY
      → ESP32 polls GET /result
        → opens gate if ALLOW

  DroidCam replaces ESP32-CAM in this version.
  Set DROIDCAM_IP below to your phone's IP.
=============================================================
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import cv2
import numpy as np
import easyocr
import os, time, gc, csv, re, json, threading
from datetime import datetime
from io import StringIO, BytesIO

app = Flask(__name__, static_folder='static')
CORS(app)

# ============================================================
#  CONFIGURATION
# ============================================================

DROIDCAM_IP   = "192.168.137.126"   # ← your phone IP
DROIDCAM_PORT = 4747
# Flask tries /mjpegfeed first, falls back to /video
DROIDCAM_URLS = [
    f"http://{DROIDCAM_IP}:{DROIDCAM_PORT}/mjpegfeed",
    f"http://{DROIDCAM_IP}:{DROIDCAM_PORT}/video",
]

os.makedirs('static/uploads', exist_ok=True)

# ============================================================
#  CSV / SETTINGS FILES
# ============================================================

WHITELIST_FILE = "whitelist.csv"
BLACKLIST_FILE = "blacklist.csv"
LOG_FILE       = "vehicle_log.csv"
SETTINGS_FILE  = "settings.json"

DEFAULT_SETTINGS = {
    "sensitivity": 80,
    "gate_duration": 5,
    "auto_log": True,
    "notifications": True
}

def init_csv_files():
    if not os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=['plate','owner','added_date']).writeheader()
    if not os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=['plate','reason','added_date']).writeheader()
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='') as f:
            csv.DictWriter(f, fieldnames=['id','plate','status','timestamp','image_file','confidence']).writeheader()
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)

init_csv_files()

def read_csv(filename):
    try:
        with open(filename, 'r', newline='') as f:
            return list(csv.DictReader(f))
    except:
        return []

def write_csv(filename, rows, fieldnames):
    try:
        with open(filename, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader(); w.writerows(rows)
        return True
    except:
        return False

def append_csv(filename, row, fieldnames):
    rows = read_csv(filename)
    rows.append(row)
    return write_csv(filename, rows, fieldnames)

def get_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except:
        return DEFAULT_SETTINGS

def save_settings(s):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(s, f, indent=2)
        return True
    except:
        return False

# ============================================================
#  EASYOCR
# ============================================================

print("\n🚗 Loading EasyOCR...")
reader = easyocr.Reader(['en'], gpu=False, verbose=False)
print("✓ EasyOCR ready!\n")

# ============================================================
#  INDIAN PLATE UTILS  (same logic as droidcam_anpr.py)
# ============================================================

INDIAN_STATE_CODES = {
    "AN","AP","AR","AS","BR","CG","CH","DD","DL","DN",
    "GA","GJ","HP","HR","JH","JK","KA","KL","LA","LD",
    "MH","ML","MN","MP","MZ","NL","OD","OR","PB","PY",
    "RJ","SK","TN","TR","TS","UK","UP","WB",
}

PLATE_PATTERNS = [
    (r'^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$',    "Standard"),
    (r'^\d{2}BH\d{4}[A-Z]{2}$',             "BH Series"),
    (r'^[A-Z]{2}\d{2}E[A-Z]?\d{4}$',        "EV"),
    (r'^[A-Z]{2}\d{2}G[A-Z]\d{4}$',         "Government"),
    (r'^[A-Z]{2}\d{2}D\d{4}$',              "Dealer"),
    (r'^[A-Z]{2}\d{2}(TR|TEMP)\d{1,4}$',    "Temporary"),
    (r'^\d{3}CD\d{4}$',                     "Diplomatic"),
    (r'^\d{2}[A-Z]\d{4,5}$',               "Army/Defence"),
]

_TO_DIGIT  = {'O':'0','I':'1','S':'5','G':'6','B':'8','Z':'2','Q':'0'}
_TO_LETTER = {'0':'O','1':'I','5':'S','6':'G','8':'B'}

def fix_ocr(raw: str) -> str:
    c = re.sub(r'[^A-Z0-9]', '', raw.upper())
    if len(c) < 5:
        return c
    r = list(c)
    for i in range(min(2, len(r))):
        r[i] = _TO_LETTER.get(r[i], r[i])
    for i in range(2, min(4, len(r))):
        r[i] = _TO_DIGIT.get(r[i], r[i])
    for i in range(max(0, len(r)-4), len(r)):
        r[i] = _TO_DIGIT.get(r[i], r[i])
    return ''.join(r)

def format_plate(c: str, ptype: str) -> str:
    if ptype == "BH Series" and len(c) == 10:
        return f"{c[:2]} BH {c[4:8]} {c[8:]}"
    if ptype == "Diplomatic" and len(c) == 9:
        return f"{c[:3]} CD {c[5:]}"
    m = re.match(r'^([A-Z]{2})(\d{2})([A-Z]{1,2})(\d{4})$', c)
    if m:
        return f"{m[1]} {m[2]} {m[3]} {m[4]}"
    return c

def validate_plate(raw: str):
    """Returns (is_valid, formatted, plate_type)"""
    corrected = fix_ocr(raw)
    for pat, ptype in PLATE_PATTERNS:
        if re.match(pat, corrected):
            state = corrected[:2]
            if ptype in ("BH Series","Army/Defence","Diplomatic") \
               or state in INDIAN_STATE_CODES:
                return True, format_plate(corrected, ptype), ptype
    return False, corrected, "Unknown"

# ============================================================
#  PLATE PREPROCESSING  (4 variants)
# ============================================================

def preprocess_plate(roi: np.ndarray) -> list:
    h, w = roi.shape[:2]
    if w < 240:
        roi = cv2.resize(roi, (240, int(h*240/w)), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.bilateralFilter(gray, 9, 15, 15)
    _, t1 = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    t2 = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 13, 4)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    _, t3 = cv2.threshold(clahe.apply(gray), 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    return [t1, t2, t3, cv2.bitwise_not(t1)]

def ocr_plate(roi: np.ndarray):
    """Run OCR on all preprocessed variants, return best (text, conf)."""
    best_text, best_conf = None, 0.0
    for img in preprocess_plate(roi):
        try:
            hits = reader.readtext(img,
                                   allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                                   detail=1, paragraph=False)
        except Exception:
            continue
        for (_, txt, conf) in hits:
            txt = txt.upper().strip()
            if len(txt) >= 5 and conf > best_conf:
                best_text, best_conf = txt, conf
    return best_text, best_conf

# ============================================================
#  PLATE REGION DETECTION
# ============================================================

def find_plate_regions(frame: np.ndarray) -> list:
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur  = cv2.bilateralFilter(gray, 11, 15, 15)
    edges = cv2.Canny(blur, 30, 180)
    boxes = []

    cnts, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in sorted(cnts, key=cv2.contourArea, reverse=True)[:25]:
        peri   = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.016*peri, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if h > 0 and 1.8 < (w/h) < 6.5 and 70 < w < 620 and 18 < h < 200:
                boxes.append((x, y, w, h))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    cnts2, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts2:
        x, y, w, h = cv2.boundingRect(cnt)
        if h > 0 and 1.8 < (w/h) < 6.5 and 70 < w < 620 and 18 < h < 200:
            boxes.append((x, y, w, h))

    return boxes

# ============================================================
#  DROIDCAM — persistent background stream
#
#  Stays connected permanently. IR trigger just reads the
#  latest frame from memory — no connect/disconnect delay.
# ============================================================

class DroidCamStream(threading.Thread):
    """
    Runs as a daemon thread from server startup.
    Keeps one fresh frame available at all times.
    Auto-reconnects if the stream drops.
    """
    def __init__(self, urls: list):
        super().__init__(daemon=True)
        self.urls        = urls
        self._lock       = threading.Lock()
        self._frame      = None          # latest decoded frame
        self._connected  = False
        self._active_url = None

    def run(self):
        while True:
            connected = False
            for url in self.urls:
                print(f"  DroidCam: trying {url} ...")
                cap = cv2.VideoCapture(url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not cap.isOpened():
                    cap.release()
                    continue

                print(f"  DroidCam: connected → {url}")
                with self._lock:
                    self._connected  = True
                    self._active_url = url
                connected = True

                # ── Keep reading frames ──────────────────────
                consecutive_fails = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        consecutive_fails += 1
                        if consecutive_fails > 30:
                            # Stream dropped — break to reconnect
                            print("  DroidCam: stream lost, reconnecting...")
                            break
                        time.sleep(0.03)
                        continue
                    consecutive_fails = 0
                    # Overwrite stale frame — no queue, just latest
                    with self._lock:
                        self._frame = frame

                cap.release()
                with self._lock:
                    self._connected = False
                break   # retry from first URL

            if not connected:
                print("  DroidCam: all URLs failed, retrying in 5s...")
            time.sleep(5)   # wait before reconnect attempt

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def get_frame(self) -> np.ndarray | None:
        """Return a copy of the latest frame (thread-safe)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None


# Start stream at module load — stays alive for the whole server session
droidcam = DroidCamStream(DROIDCAM_URLS)
droidcam.start()
print("  DroidCam background stream started — waiting for connection...")
# Give it 8 seconds to connect before first request arrives
for _ in range(16):
    if droidcam.connected:
        break
    time.sleep(0.5)

# ============================================================
#  CORE ANPR FUNCTION
#  Called on every IR trigger
# ============================================================

def run_anpr_on_frame(img: np.ndarray):
    """
    Runs full ANPR pipeline on a single frame.
    Returns dict: { plate, plate_type, status, result, confidence, filename }
    """
    # ── Find plate regions ────────────────────────────────────
    regions = find_plate_regions(img)

    best_plate, best_type, best_conf = None, "Unknown", 0.0

    for (x, y, w, h) in regions:
        pad = 5
        roi = img[max(0,y-pad):min(img.shape[0],y+h+pad),
                  max(0,x-pad):min(img.shape[1],x+w+pad)]
        if roi.size == 0:
            continue
        text, conf = ocr_plate(roi)
        if not text:
            continue
        is_valid, formatted, ptype = validate_plate(text)
        if is_valid and conf > best_conf:
            best_plate, best_type, best_conf = formatted, ptype, conf

    # ── Fallback: raw EasyOCR on whole frame ─────────────────
    # (catches plates that didn't pass contour detection)
    if not best_plate:
        raw_hits = reader.readtext(img,
                                   allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ',
                                   detail=1, paragraph=False)
        for (_, txt, conf) in raw_hits:
            is_valid, formatted, ptype = validate_plate(txt)
            if is_valid and conf > best_conf:
                best_plate, best_type, best_conf = formatted, ptype, conf

    if not best_plate or best_conf < 0.30:
        return {"plate": None, "result": "DENY", "status": "NO_PLATE",
                "confidence": 0, "plate_type": "Unknown", "filename": None}

    # ── Whitelist / Blacklist check ───────────────────────────
    whitelist = read_csv(WHITELIST_FILE)
    blacklist = read_csv(BLACKLIST_FILE)
    clean     = best_plate.replace(" ", "").upper()

    is_blacklisted = any(r['plate'].replace(" ","").upper() == clean for r in blacklist)
    is_whitelisted = any(r['plate'].replace(" ","").upper() == clean for r in whitelist)

    if is_blacklisted:
        status, result = "BLACKLIST", "DENY"
    elif is_whitelisted:
        status, result = "WHITELIST", "ALLOW"
    else:
        status, result = "UNKNOWN", "DENY"

    # ── Save car photo with annotation ───────────────────────
    annotated  = img.copy()

    # Draw plate boxes
    for (x, y, w, h) in regions:
        cv2.rectangle(annotated, (x,y), (x+w,y+h),
                      (0,255,80) if result=="ALLOW" else (0,60,255), 2)

    # Bottom banner
    bh = 42
    cv2.rectangle(annotated, (0, annotated.shape[0]-bh),
                  (annotated.shape[1], annotated.shape[0]), (0,0,0), -1)
    banner_color = (0,255,80) if result=="ALLOW" else (0,80,255)
    cv2.putText(annotated,
                f"{best_plate}  |  {best_type}  |  {result}  |  "
                f"{datetime.now().strftime('%d %b %Y %H:%M:%S')}",
                (8, annotated.shape[0]-12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, banner_color, 2)

    filename = f"{int(time.time())}_{clean}.jpg"
    filepath = f"static/uploads/{filename}"
    cv2.imwrite(filepath, annotated)

    # ── Log entry ─────────────────────────────────────────────
    log_entry = {
        'id':         len(read_csv(LOG_FILE)) + 1,
        'plate':      best_plate,
        'status':     status,
        'timestamp':  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'image_file': filename,
        'confidence': f"{best_conf:.2f}",
    }
    append_csv(LOG_FILE, log_entry,
               ['id','plate','status','timestamp','image_file','confidence'])

    print(f"  ANPR  →  {best_plate:<18} {best_type:<14} {status:<10} "
          f"conf:{best_conf:.0%}  →  {result}")

    return {
        "plate":      best_plate,
        "plate_type": best_type,
        "status":     status,
        "result":     result,
        "confidence": round(best_conf, 2),
        "filename":   filename,
    }

# ============================================================
#  GLOBAL STATE
# ============================================================

detection_result  = "WAITING"   # WAITING / PROCESSING / ALLOWED / DENIED
detected_plate    = ""
detection_lock    = threading.Lock()

# ============================================================
#  ROUTES
# ============================================================

@app.route("/")
def index():
    return send_file("index.html")

# ──────────────────────────────────────────────────────────
#  IR TRIGGER  ← called by ESP32 dev board
#  This is the main entry point for the whole ANPR flow
# ──────────────────────────────────────────────────────────
@app.route("/ir_trigger", methods=["POST"])
def ir_trigger():
    global detection_result, detected_plate

    with detection_lock:
        detection_result = "PROCESSING"
        detected_plate   = ""

    print(f"\n{'='*52}")
    print(f"  IR TRIGGER received at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*52}")

    # ── Step 1: Get latest frame from persistent stream ──────
    # No connect/disconnect — frame is already in memory
    img = droidcam.get_frame()

    if img is None:
        with detection_lock:
            detection_result = "DENIED"
        print("  WARNING: DroidCam not ready yet (no frame in buffer)")
        return jsonify({"status": "ok", "result": "DENY",
                        "reason": "DroidCam not ready"}), 200

    # ── Step 2: Run ANPR ─────────────────────────────────────
    anpr = run_anpr_on_frame(img)

    with detection_lock:
        detected_plate   = anpr["plate"] or ""
        detection_result = "ALLOWED" if anpr["result"] == "ALLOW" else "DENIED"

    return jsonify({
        "status":     "ok",
        "result":     anpr["result"],        # "ALLOW" or "DENY"
        "plate":      anpr["plate"],
        "plate_type": anpr["plate_type"],
        "access":     anpr["status"],        # WHITELIST / BLACKLIST / UNKNOWN
        "confidence": anpr["confidence"],
        "image":      anpr["filename"],
    }), 200

# ──────────────────────────────────────────────────────────
#  RESULT  ← polled by ESP32 after trigger
# ──────────────────────────────────────────────────────────
@app.route("/result", methods=["GET"])
def result():
    with detection_lock:
        r = "ALLOW" if detection_result == "ALLOWED" else "DENY"
        p = detected_plate
    return jsonify({"result": r, "plate": p}), 200

@app.route("/status", methods=["GET"])
def status():
    with detection_lock:
        return jsonify({
            "detection_result": detection_result,
            "detected_plate":   detected_plate,
        }), 200

# ──────────────────────────────────────────────────────────
#  DROIDCAM LIVE STREAM PROXY  (for frontend preview)
# ──────────────────────────────────────────────────────────
@app.route("/cam_stream")
def cam_stream():
    """Serves a live MJPEG stream to the frontend using the persistent stream."""
    def generate():
        while True:
            frame = droidcam.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                continue
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(buf)).encode() + b'\r\n\r\n'
                   + buf.tobytes() + b'\r\n')
            time.sleep(0.05)   # ~20fps to frontend

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/cam_snapshot")
def cam_snapshot():
    """Returns the latest JPEG frame from the persistent stream."""
    img = droidcam.get_frame()
    if img is None:
        return jsonify({"error": "DroidCam not ready"}), 503
    ret, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), mimetype='image/jpeg')

@app.route("/cam_status")
def cam_status():
    return jsonify({
        "online":     droidcam.connected,
        "ip":         DROIDCAM_IP,
        "active_url": droidcam._active_url,
    }), 200

# ──────────────────────────────────────────────────────────
#  MANUAL UPLOAD (frontend drag-and-drop)
# ──────────────────────────────────────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    try:
        file      = request.files.get("image")
        img_bytes = file.read() if file else request.data
        nparr     = np.frombuffer(img_bytes, np.uint8)
        img       = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return jsonify({"result": "NOT_DETECTED"}), 200
        anpr = run_anpr_on_frame(img)
        if not anpr["plate"]:
            return jsonify({"result": "NOT_DETECTED"}), 200
        return jsonify({
            "result":     "DETECTED",
            "plate":      anpr["plate"],
            "plate_type": anpr["plate_type"],
            "image":      anpr["filename"],
            "access":     anpr["status"],
        }), 200
    except Exception as e:
        print(f"  upload error: {e}")
        return jsonify({"result": "NOT_DETECTED"}), 200

# ──────────────────────────────────────────────────────────
#  WHITELIST
# ──────────────────────────────────────────────────────────
@app.route("/whitelist", methods=["GET"])
def get_whitelist():
    return jsonify(read_csv(WHITELIST_FILE)), 200

@app.route("/whitelist/add", methods=["POST"])
def add_whitelist():
    data  = request.get_json() or {}
    plate = data.get("plate","").upper().replace(" ","")
    owner = data.get("owner","")
    if not plate or len(plate) < 4:
        return jsonify({"error": "Invalid plate"}), 400
    rows = read_csv(WHITELIST_FILE)
    if any(r['plate'].upper() == plate for r in rows):
        return jsonify({"status": "exists"}), 400
    append_csv(WHITELIST_FILE,
               {'plate':plate,'owner':owner,
                'added_date':datetime.now().strftime("%Y-%m-%d")},
               ['plate','owner','added_date'])
    return jsonify({"status": "added", "plate": plate}), 200

@app.route("/whitelist/remove", methods=["POST"])
def remove_whitelist():
    plate = (request.get_json() or {}).get("plate","").upper()
    rows  = [r for r in read_csv(WHITELIST_FILE) if r['plate'].upper() != plate]
    write_csv(WHITELIST_FILE, rows, ['plate','owner','added_date'])
    return jsonify({"status": "removed"}), 200

# ──────────────────────────────────────────────────────────
#  BLACKLIST
# ──────────────────────────────────────────────────────────
@app.route("/blacklist", methods=["GET"])
def get_blacklist():
    return jsonify(read_csv(BLACKLIST_FILE)), 200

@app.route("/blacklist/add", methods=["POST"])
def add_blacklist():
    data   = request.get_json() or {}
    plate  = data.get("plate","").upper().replace(" ","")
    reason = data.get("reason","")
    if not plate or len(plate) < 4:
        return jsonify({"error": "Invalid plate"}), 400
    rows = read_csv(BLACKLIST_FILE)
    if any(r['plate'].upper() == plate for r in rows):
        return jsonify({"status": "exists"}), 400
    append_csv(BLACKLIST_FILE,
               {'plate':plate,'reason':reason,
                'added_date':datetime.now().strftime("%Y-%m-%d")},
               ['plate','reason','added_date'])
    return jsonify({"status": "added"}), 200

@app.route("/blacklist/remove", methods=["POST"])
def remove_blacklist():
    plate = (request.get_json() or {}).get("plate","").upper()
    rows  = [r for r in read_csv(BLACKLIST_FILE) if r['plate'].upper() != plate]
    write_csv(BLACKLIST_FILE, rows, ['plate','reason','added_date'])
    return jsonify({"status": "removed"}), 200

# ──────────────────────────────────────────────────────────
#  LOG
# ──────────────────────────────────────────────────────────
@app.route("/log", methods=["GET"])
def get_log():
    limit = request.args.get("limit", 100, type=int)
    rows  = read_csv(LOG_FILE)
    rows.reverse()
    return jsonify(rows[:limit]), 200

@app.route("/log/clear", methods=["POST"])
def clear_log():
    write_csv(LOG_FILE, [], ['id','plate','status','timestamp','image_file','confidence'])
    return jsonify({"status": "cleared"}), 200

# ──────────────────────────────────────────────────────────
#  EXPORT
# ──────────────────────────────────────────────────────────
@app.route("/export/csv", methods=["GET"])
def export_csv():
    rows   = read_csv(LOG_FILE)
    output = StringIO()
    if rows:
        w = csv.DictWriter(output, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment;filename=detection_log.csv"}), 200

@app.route("/export/json", methods=["GET"])
def export_json():
    rows = read_csv(LOG_FILE)
    return jsonify({"export_date": datetime.now().isoformat(),
                    "total_detections": len(rows), "data": rows}), 200

@app.route("/export/pdf", methods=["GET"])
def export_pdf():
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        rows   = read_csv(LOG_FILE)
        output = BytesIO()
        doc    = SimpleDocTemplate(output, pagesize=letter)
        styles = getSampleStyleSheet()
        elems  = [
            Paragraph("Smart Gate System - Detection Report", styles['Title']),
            Spacer(1, 0.3),
            Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                      f"<br/>Total: {len(rows)}", styles['Normal']),
            Spacer(1, 0.3),
        ]
        if rows:
            data = [['Plate','Status','Timestamp','Confidence']]
            for r in rows[-20:]:
                data.append([r.get('plate','--'), r.get('status','--'),
                              r.get('timestamp','--'), r.get('confidence','--')])
            t = Table(data)
            t.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.grey),
                ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
                ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
                ('BOTTOMPADDING',(0,0),(-1,0),12),
                ('BACKGROUND',(0,1),(-1,-1),colors.beige),
                ('GRID',(0,0),(-1,-1),1,colors.black),
            ]))
            elems.append(t)
        doc.build(elems)
        output.seek(0)
        return send_file(output, mimetype="application/pdf",
                         as_attachment=True,
                         download_name="detection_report.pdf"), 200
    except Exception as e:
        return jsonify({"error": f"PDF failed: {e}"}), 500

# ──────────────────────────────────────────────────────────
#  SETTINGS & STATS
# ──────────────────────────────────────────────────────────
@app.route("/settings", methods=["GET"])
def get_settings_route():
    return jsonify(get_settings()), 200

@app.route("/settings", methods=["POST"])
def update_settings():
    data     = request.get_json() or {}
    settings = get_settings()
    settings.update(data)
    save_settings(settings)
    return jsonify({"status": "saved"}), 200

@app.route("/stats", methods=["GET"])
def get_stats():
    rows = read_csv(LOG_FILE)
    return jsonify({
        "total":     len(rows),
        "whitelist": sum(1 for r in rows if r.get('status') == 'WHITELIST'),
        "blacklist": sum(1 for r in rows if r.get('status') == 'BLACKLIST'),
        "unknown":   sum(1 for r in rows if r.get('status') == 'UNKNOWN'),
    }), 200

# ============================================================
if __name__ == "__main__":
    print(f"  DroidCam  : {DROIDCAM_URLS[0]}")
    print(f"  Flask API : http://0.0.0.0:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)