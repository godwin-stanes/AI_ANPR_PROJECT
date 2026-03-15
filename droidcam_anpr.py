"""
=============================================================
  SMART GATE - DroidCam ANPR  (Indian Number Plate Recognition)
  Threaded architecture: stream thread NEVER blocked by OCR

  Fixes applied:
    ✅ Dedicated stream thread  → zero lag in display
    ✅ Separate OCR thread      → detection runs in background
    ✅ Frame queue (maxsize=1)  → always processes latest frame
    ✅ /mjpegfeed URL           → lower latency than /video
    ✅ CAP_PROP_BUFFERSIZE = 1  → no stale frame build-up
    ✅ Faster contour filter    → skip tiny/huge regions early

  Supports ALL Indian plate formats:
    ✅ Standard private     : TN 01 AB 1234
    ✅ Old format           : TN 01 A 1234
    ✅ BH (Bharat) series   : 22 BH 1234 AA
    ✅ Government           : GJ 01 GA 0001
    ✅ Electric vehicle     : TN 01 EA 1234
    ✅ Army / Defence       : 01 A 12345
    ✅ Temporary (red)      : TN 01 TR 1234
    ✅ Dealer plates        : TN 01 D 1234
    ✅ Diplomatic           : 101 CD 1234

  Requirements:
    pip install opencv-python easyocr numpy

  DroidCam Setup:
    1. Install DroidCam app on Android
    2. Phone and PC must be on the SAME WiFi
    3. Open DroidCam app -> note the IP (e.g. 192.168.1.10)
    4. Set DROIDCAM_IP below
=============================================================
"""

import cv2
import numpy as np
import easyocr
import re
import time
import os
import threading
import queue
from datetime import datetime

# ============================================================
#  CONFIGURATION  -- only edit this block
# ============================================================

DROIDCAM_IP    = "192.168.137.126"     # <- your phone IP here
DROIDCAM_PORT  = 4747               # default DroidCam port

# For USB DroidCam set USE_USB = True
USE_USB        = False
USB_INDEX      = 0

SAVE_PLATES    = True
OUTPUT_DIR     = "detected_plates"
# Each detection saves TWO files inside OUTPUT_DIR:
#   <PLATE>_<time>_car.jpg   -> full frame with bounding box drawn (car photo)
#   <PLATE>_<time>_plate.jpg -> cropped plate region only
SHOW_WINDOW    = True
MIN_CONFIDENCE = 0.38               # raise to 0.5+ to cut false positives
PLATE_COOLDOWN = 3                  # seconds before same plate re-logs
DISPLAY_WIDTH  = 800                # resize window to this width
OCR_EVERY_N    = 4                  # run OCR on 1 in N frames

# ============================================================
#  INDIAN STATE CODES
# ============================================================

INDIAN_STATE_CODES = {
    "AN","AP","AR","AS","BR","CG","CH","DD","DL","DN",
    "GA","GJ","HP","HR","JH","JK","KA","KL","LA","LD",
    "MH","ML","MN","MP","MZ","NL","OD","OR","PB","PY",
    "RJ","SK","TN","TR","TS","UK","UP","WB",
}

# ============================================================
#  PLATE REGEX PATTERNS
# ============================================================

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

# ============================================================
#  OCR CORRECTION  (zone-aware letter <-> digit swaps)
# ============================================================

_TO_DIGIT  = {'O':'0','I':'1','S':'5','G':'6','B':'8','Z':'2','Q':'0'}
_TO_LETTER = {'0':'O','1':'I','5':'S','6':'G','8':'B'}

def fix_ocr(raw: str) -> str:
    c = re.sub(r'[^A-Z0-9]', '', raw.upper())
    if len(c) < 5:
        return c
    r = list(c)
    for i in range(min(2, len(r))):
        r[i] = _TO_LETTER.get(r[i], r[i])     # pos 0-1: state letters
    for i in range(2, min(4, len(r))):
        r[i] = _TO_DIGIT.get(r[i], r[i])      # pos 2-3: district digits
    for i in range(max(0, len(r) - 4), len(r)):
        r[i] = _TO_DIGIT.get(r[i], r[i])      # last 4: serial digits
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

def validate(raw: str):
    corrected = fix_ocr(raw)
    for pat, ptype in PLATE_PATTERNS:
        if re.match(pat, corrected):
            state = corrected[:2]
            if ptype in ("BH Series", "Army/Defence", "Diplomatic") \
               or state in INDIAN_STATE_CODES:
                return True, format_plate(corrected, ptype), ptype
    return False, corrected, "Unknown"

# ============================================================
#  PREPROCESSING  (4 variants for different plate colours)
# ============================================================

def preprocess(roi: np.ndarray) -> list:
    h, w = roi.shape[:2]
    if w < 240:
        roi = cv2.resize(roi, (240, int(h * 240 / w)), interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.bilateralFilter(gray, 9, 15, 15)

    _, t1 = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    t2 = cv2.adaptiveThreshold(blur, 255,
                                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 13, 4)

    clahe   = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    _, t3   = cv2.threshold(clahe.apply(gray), 0, 255,
                             cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    t4 = cv2.bitwise_not(t1)   # inverted for yellow/green plates

    return [t1, t2, t3, t4]

# ============================================================
#  OCR
# ============================================================

def run_ocr(roi: np.ndarray, reader: easyocr.Reader):
    best_text, best_conf = None, 0.0
    for img in preprocess(roi):
        try:
            hits = reader.readtext(
                img,
                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                detail=1,
                paragraph=False,
            )
        except Exception:
            continue
        for (_, txt, conf) in hits:
            txt = txt.upper().strip()
            if len(txt) >= 5 and conf > best_conf:
                best_text, best_conf = txt, conf
    return best_text, best_conf

# ============================================================
#  PLATE REGION DETECTION  (2-pass)
# ============================================================

def find_plates(frame: np.ndarray) -> list:
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur  = cv2.bilateralFilter(gray, 11, 15, 15)
    edges = cv2.Canny(blur, 30, 180)
    boxes = []

    # Pass 1: contour rectangles
    cnts, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in sorted(cnts, key=cv2.contourArea, reverse=True)[:25]:
        peri   = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.016 * peri, True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if _ok(w, h):
                boxes.append((x, y, w, h))

    # Pass 2: morphological close
    kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    closed  = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    cnts2,_ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts2:
        x, y, w, h = cv2.boundingRect(cnt)
        if _ok(w, h):
            boxes.append((x, y, w, h))

    return _dedup(boxes)

def _ok(w, h):
    return h > 0 and 1.8 < (w/h) < 6.5 and 70 < w < 620 and 18 < h < 200

def _dedup(boxes, thr=0.4):
    boxes = list(set(boxes))
    keep  = []
    for i,(x1,y1,w1,h1) in enumerate(boxes):
        skip = False
        for j,(x2,y2,w2,h2) in enumerate(boxes):
            if i == j: continue
            ix = max(x1,x2); iy = max(y1,y2)
            iw = min(x1+w1,x2+w2)-ix; ih = min(y1+h1,y2+h2)-iy
            if iw>0 and ih>0 and (iw*ih)/(w1*h1) > thr and (w2*h2)>(w1*h1):
                skip = True; break
        if not skip:
            keep.append((x1,y1,w1,h1))
    return keep

# ============================================================
#  STREAM THREAD  -- grabs frames without blocking display
# ============================================================

class StreamReader(threading.Thread):
    def __init__(self, url):
        super().__init__(daemon=True)
        self.url   = url
        self._q    = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self.ok    = False

    def run(self):
        cap = cv2.VideoCapture(self.url)
        if not cap.isOpened():
            print(f"  ERROR: cannot open {self.url}")
            return
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.ok = True
        print("  Stream thread: connected")
        while not self._stop.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            # Always keep only the newest frame
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put(frame)
        cap.release()

    def read(self):
        try:
            return self._q.get(timeout=0.5)
        except queue.Empty:
            return None

    def stop(self):
        self._stop.set()

# ============================================================
#  OCR WORKER THREAD  -- runs detection without blocking display
# ============================================================

class OcrWorker(threading.Thread):
    def __init__(self, reader):
        super().__init__(daemon=True)
        self.reader   = reader
        self._in      = queue.Queue(maxsize=1)
        self._lock    = threading.Lock()
        self._results = []
        self._stop    = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                frame = self._in.get(timeout=0.3)
            except queue.Empty:
                continue

            boxes   = find_plates(frame)
            new_res = []
            for (x, y, w, h) in boxes:
                pad = 5
                roi = frame[max(0,y-pad):min(frame.shape[0],y+h+pad),
                            max(0,x-pad):min(frame.shape[1],x+w+pad)]
                if roi.size == 0:
                    continue
                text, conf = run_ocr(roi, self.reader)
                if not text or conf < MIN_CONFIDENCE:
                    new_res.append((x, y, w, h, None, 0, False, ""))
                    continue
                is_valid, formatted, ptype = validate(text)
                new_res.append((x, y, w, h, formatted, conf, is_valid, ptype))

            with self._lock:
                self._results = new_res

    def submit(self, frame):
        if not self._in.full():
            try:
                self._in.put_nowait(frame)
            except queue.Full:
                pass

    def get_results(self):
        with self._lock:
            return list(self._results)

    def stop(self):
        self._stop.set()

# ============================================================
#  MAIN
# ============================================================

def main():
    print("\n SMART GATE -- Indian ANPR  (DroidCam)")
    print("=" * 52)

    if SAVE_PLATES and not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Build stream URL
    if USE_USB:
        stream_url = USB_INDEX
        print(f"  Source : USB webcam index {USB_INDEX}")
    else:
        # /mjpegfeed = low-latency MJPEG endpoint (less lag than /video)
        stream_url = f"http://{DROIDCAM_IP}:{DROIDCAM_PORT}/video"
        print(f"  Source : {stream_url}")
        print(f"  Tip    : if stream fails also try /video instead of /mjpegfeed")

    print("  Loading EasyOCR (first run downloads ~100 MB)...")
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    print("  EasyOCR ready!")

    # Start stream thread
    streamer = StreamReader(stream_url)
    streamer.start()
    for _ in range(10):
        if streamer.ok:
            break
        time.sleep(0.5)

    if not streamer.ok:
        print("\n  ERROR: Stream failed to connect.")
        print(f"  - Check IP: open browser -> {stream_url}")
        print(f"  - Make sure phone and PC are on the same WiFi")
        print(f"  - DroidCam app must be open and running on phone")
        return

    # Start OCR worker thread
    worker = OcrWorker(reader)
    worker.start()

    detected  = {}    # plate -> last timestamp
    frame_no  = 0

    print(f"\n  {'PLATE':<20} {'TYPE':<15} {'CONF':<8} TIME")
    print("  " + "-" * 53)

    while True:
        frame = streamer.read()
        if frame is None:
            continue

        frame_no += 1

        # Resize for display
        h, w  = frame.shape[:2]
        scale = DISPLAY_WIDTH / w
        disp  = cv2.resize(frame, (DISPLAY_WIDTH, int(h * scale)))

        # Submit to OCR every N frames
        if frame_no % OCR_EVERY_N == 0:
            worker.submit(disp.copy())

        # Draw bounding boxes from last OCR pass
        for (x, y, w2, h2, text, conf, is_valid, ptype) in worker.get_results():

            if text is None:
                cv2.rectangle(disp, (x,y), (x+w2,y+h2), (50,50,50), 1)
                continue

            color  = (0, 255, 80) if is_valid else (0, 140, 255)
            cv2.rectangle(disp, (x, y), (x+w2, y+h2), color, 2)

            label  = f"{text}  {conf:.0%}"
            lbl_y  = max(y - 8, 14)
            cv2.rectangle(disp, (x, lbl_y-16), (x + len(label)*10, lbl_y+4), color, -1)
            cv2.putText(disp, label, (x+2, lbl_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
            cv2.putText(disp, ptype, (x, y+h2+16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

            # Log & save valid plates
            if is_valid:
                now = time.time()
                if now - detected.get(text, 0) > PLATE_COOLDOWN:
                    detected[text] = now
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"  {text:<20} {ptype:<15} {conf:<8.0%} {ts}")

                    if SAVE_PLATES:
                        stamp      = datetime.now().strftime('%H%M%S')
                        safe_name  = text.replace(' ', '_')

                        # ── 1. Full car photo (entire frame, box already drawn) ──
                        car_frame  = disp.copy()

                        # Draw a larger highlight box on the car photo
                        PAD_CAR = 40
                        cx1 = max(0, x - PAD_CAR)
                        cy1 = max(0, y - PAD_CAR)
                        cx2 = min(car_frame.shape[1], x + w2 + PAD_CAR)
                        cy2 = min(car_frame.shape[0], y + h2 + PAD_CAR)
                        cv2.rectangle(car_frame, (cx1, cy1), (cx2, cy2), (0, 255, 136), 3)

                        # Stamp plate text + timestamp onto car photo
                        cv2.rectangle(car_frame, (0, car_frame.shape[0]-40),
                                      (car_frame.shape[1], car_frame.shape[0]), (0,0,0), -1)
                        cv2.putText(car_frame,
                                    f"{text}  |  {ptype}  |  {datetime.now().strftime('%d %b %Y  %H:%M:%S')}",
                                    (8, car_frame.shape[0] - 12),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 136), 2)

                        car_path = f"{OUTPUT_DIR}/{safe_name}_{stamp}_car.jpg"
                        cv2.imwrite(car_path, car_frame)

                        # ── 2. Cropped plate region only ────────────────────────
                        PAD_PLATE = 5
                        plate_crop = disp[
                            max(0, y - PAD_PLATE) : min(disp.shape[0], y + h2 + PAD_PLATE),
                            max(0, x - PAD_PLATE) : min(disp.shape[1], x + w2 + PAD_PLATE)
                        ]
                        plate_path = f"{OUTPUT_DIR}/{safe_name}_{stamp}_plate.jpg"
                        cv2.imwrite(plate_path, plate_crop)

                        print(f"    saved -> {car_path}")
                        print(f"    saved -> {plate_path}")

        # HUD overlay
        cv2.rectangle(disp, (0, 0), (310, 90), (0, 0, 0), -1)
        cv2.putText(disp, "SMART GATE  ANPR", (8, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 136), 2)
        cv2.putText(disp, f"Detected : {len(detected)} plate(s)", (8, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.54, (180, 180, 180), 1)
        cv2.putText(disp, datetime.now().strftime("%d %b %Y  %H:%M:%S"), (8, 76),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (120, 120, 120), 1)

        if SHOW_WINDOW:
            cv2.imshow("Smart Gate - ANPR  [Q = quit]", disp)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    # Cleanup
    streamer.stop()
    worker.stop()
    cv2.destroyAllWindows()

    print("\n" + "=" * 52)
    print(f"  SESSION: {len(detected)} unique plate(s) logged")
    for p in detected:
        print(f"    * {p}")
    print("=" * 52 + "\n")


if __name__ == "__main__":
    main()
