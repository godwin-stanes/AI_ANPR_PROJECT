from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import cv2
import numpy as np
import easyocr
import os
import time
import gc
import csv
from datetime import datetime
from io import StringIO, BytesIO
import json
import urllib.request
import requests as req_lib

app = Flask(__name__, static_folder='static')
CORS(app)

# ============================================
# ESP32-CAM Configuration
# ============================================
ESP32_CAM_IP = "192.168.1.8"
ESP32_CAM_STREAM_URL = f"http://{ESP32_CAM_IP}/stream"
ESP32_CAM_SNAPSHOT_URL = f"http://{ESP32_CAM_IP}/snapshot"

os.makedirs('static/uploads', exist_ok=True)

print("\n🚗 Loading OCR...")
reader = easyocr.Reader(['en'], gpu=False)
print("✓ Ready!\n")

# CSV Files
WHITELIST_FILE = "whitelist.csv"
BLACKLIST_FILE = "blacklist.csv"
LOG_FILE = "vehicle_log.csv"
SETTINGS_FILE = "settings.json"

# Default settings
DEFAULT_SETTINGS = {
    "sensitivity": 80,
    "gate_duration": 5,
    "auto_log": True,
    "notifications": True
}

# Global state
camera_active = False
detection_result = "WAITING"
detected_plate = ""
detection_sensitivity = 80
frame_buffer = []

# Initialize CSV files
def init_csv_files():
    if not os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['plate', 'owner', 'added_date'])
            writer.writeheader()
    
    if not os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['plate', 'reason', 'added_date'])
            writer.writeheader()
    
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'plate', 'status', 'timestamp', 'image_file', 'confidence'])
            writer.writeheader()
    
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)

init_csv_files()

# CSV Operations
def read_csv(filename):
    try:
        with open(filename, 'r', newline='') as f:
            return list(csv.DictReader(f))
    except:
        return []

def write_csv(filename, rows, fieldnames):
    try:
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return True
    except:
        return False

def append_csv(filename, row, fieldnames):
    try:
        rows = read_csv(filename)
        rows.append(row)
        return write_csv(filename, rows, fieldnames)
    except:
        return False

# Settings
def get_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except:
        return DEFAULT_SETTINGS

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except:
        return False

# Routes
@app.route("/")
def index():
    return send_file("index.html")

# ============================================
# ESP32-CAM Live Stream Proxy
# ============================================
@app.route("/cam_stream")
def cam_stream():
    """Proxies the live MJPEG stream from ESP32-CAM to the frontend"""
    def generate():
        try:
            r = req_lib.get(ESP32_CAM_STREAM_URL, stream=True, timeout=10)
            for chunk in r.iter_content(chunk_size=1024):
                yield chunk
        except Exception as e:
            print(f"❌ CAM stream error: {e}")
            yield b''
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/cam_snapshot")
def cam_snapshot():
    """Gets a single snapshot from ESP32-CAM"""
    try:
        r = req_lib.get(ESP32_CAM_SNAPSHOT_URL, timeout=5)
        return Response(r.content, mimetype='image/jpeg')
    except Exception as e:
        print(f"❌ Snapshot error: {e}")
        return jsonify({"error": "CAM offline"}), 503

@app.route("/cam_status")
def cam_status():
    """Check if ESP32-CAM is reachable"""
    try:
        r = req_lib.get(f"http://{ESP32_CAM_IP}/health", timeout=3)
        data = r.json()
        return jsonify({"online": True, "ip": ESP32_CAM_IP, "cam_data": data}), 200
    except:
        return jsonify({"online": False, "ip": ESP32_CAM_IP}), 200

@app.route("/stream")
def stream():
    global frame_buffer, camera_active
    
    if not camera_active:
        return "Not active", 503
    
    def generate():
        while camera_active and frame_buffer:
            frame = frame_buffer[-1]
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n'
                   + buffer.tobytes() + b'\r\n')
            time.sleep(0.05)
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route("/ir_trigger", methods=["POST"])
def ir_trigger():
    global camera_active, detection_result, detected_plate, frame_buffer
    camera_active = True
    detection_result = "PROCESSING"
    detected_plate = ""
    print("\n🚨 IR TRIGGERED! Pulling image from ESP32-CAM...")

    try:
        # Pull image directly from ESP32-CAM
        r = req_lib.get(ESP32_CAM_SNAPSHOT_URL, timeout=10)
        img_bytes = r.content
        print(f"  ✓ Got image from CAM: {len(img_bytes)} bytes")

        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is not None:
            frame_buffer.clear()
            frame_buffer.append(img)

        # Preprocess image for better OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        img_for_ocr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        # Now run OCR on the image
        results = reader.readtext(img_for_ocr) if img is not None else []
        if not results:
            results = reader.readtext(img)  # fallback to original

        if not results or img is None:
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"status": "ok", "result": "DENIED", "reason": "no plate detected"}), 200

        text = " ".join([r[1] for r in results]).upper()
        plate = "".join([c for c in text if c.isalnum()])

        if len(plate) < 5:
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"status": "ok", "result": "DENIED", "reason": "plate too short"}), 200

        print(f"  ✓ Detected plate: {plate}")
        detected_plate = plate

        whitelist = read_csv(WHITELIST_FILE)
        blacklist = read_csv(BLACKLIST_FILE)
        plate_upper = plate.upper()
        is_whitelisted = any(w['plate'].upper() == plate_upper for w in whitelist)
        is_blacklisted = any(b['plate'].upper() == plate_upper for b in blacklist)

        if is_blacklisted:
            status = "BLACKLIST"
            result = "DENY"
        elif is_whitelisted:
            status = "WHITELIST"
            result = "ALLOW"
        else:
            status = "UNKNOWN"
            result = "DENY"

        detection_result = "ALLOWED" if result == "ALLOW" else "DENIED"

        filename = f"{int(time.time())}_{plate}.jpg"
        cv2.imwrite(f"static/uploads/{filename}", img)

        confidence = float(np.mean([r[2] for r in results if len(r) > 2]))
        log_entry = {
            'id': len(read_csv(LOG_FILE)) + 1,
            'plate': plate,
            'status': status,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'image_file': filename,
            'confidence': f"{confidence:.2f}"
        }
        append_csv(LOG_FILE, log_entry, ['id', 'plate', 'status', 'timestamp', 'image_file', 'confidence'])

        camera_active = False
        gc.collect()

        print(f"  ✓ Result: {result} | Plate: {plate} | Status: {status}")
        return jsonify({"status": "ok", "result": result, "plate": plate}), 200

    except Exception as e:
        print(f"  ❌ Error pulling from CAM: {e}")
        camera_active = False
        detection_result = "DENIED"
        return jsonify({"status": "ok", "result": "DENIED", "reason": str(e)}), 200

@app.route("/capture", methods=["POST"])
def capture():
    global camera_active, detection_result, detected_plate, frame_buffer, detection_sensitivity
    
    try:
        if not camera_active:
            return jsonify({"result": "WAITING"}), 200
        
        img_bytes = request.data
        if not img_bytes:
            camera_active = False
            return jsonify({"result": "DENIED"}), 400
        
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            try:
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(img_bytes))
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except:
                camera_active = False
                return jsonify({"result": "DENIED"}), 200
        
        frame_buffer.clear()
        frame_buffer.append(img)
        
        print("  📸 Processing image...")
        
        results = reader.readtext(img)
        
        if not results:
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"result": "DENIED"}), 200
        
        text = " ".join([r[1] for r in results]).upper()
        plate = "".join([c for c in text if c.isalnum()])
        
        if len(plate) < 5:
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"result": "DENIED"}), 200
        
        print(f"  ✓ Detected: {plate}")
        detected_plate = plate
        
        # Check lists
        whitelist = read_csv(WHITELIST_FILE)
        blacklist = read_csv(BLACKLIST_FILE)
        
        plate_upper = plate.upper()
        is_whitelisted = any(w['plate'].upper() == plate_upper for w in whitelist)
        is_blacklisted = any(b['plate'].upper() == plate_upper for b in blacklist)
        
        if is_blacklisted:
            status = "BLACKLIST"
            result = "DENIED"
        elif is_whitelisted:
            status = "WHITELIST"
            result = "ALLOWED"
        else:
            status = "UNKNOWN"
            result = "DENIED"
        
        detection_result = "ALLOWED" if result == "ALLOWED" else "DENIED"
        
        # Save image
        filename = f"{int(time.time())}_{plate}.jpg"
        cv2.imwrite(f"static/uploads/{filename}", img)
        
        # Log to CSV
        confidence = np.mean([r[2] for r in results if len(r) > 2])
        log_entry = {
            'id': len(read_csv(LOG_FILE)) + 1,
            'plate': plate,
            'status': status,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'image_file': filename,
            'confidence': f"{confidence:.2f}"
        }
        append_csv(LOG_FILE, log_entry, ['id', 'plate', 'status', 'timestamp', 'image_file', 'confidence'])
        
        camera_active = False
        gc.collect()
        
        return jsonify({
            "result": "ALLOW" if result == "ALLOWED" else "DENY",
            "plate": plate,
            "image": filename,
            "status": status
        }), 200
    
    except Exception as e:
        print(f"  Error: {e}")
        camera_active = False
        return jsonify({"result": "DENIED"}), 500

@app.route("/result", methods=["GET"])
def result():
    result_text = "ALLOW" if detection_result == "ALLOWED" else "DENY"
    return jsonify({"result": result_text, "plate": detected_plate}), 200

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "camera_active": camera_active,
        "detection_result": detection_result,
        "detected_plate": detected_plate
    }), 200

@app.route("/upload", methods=["POST"])
def upload():
    try:
        if "image" not in request.files:
            return jsonify({"result": "NOT_DETECTED"}), 200
        
        file = request.files["image"]
        img_bytes = file.read()
        
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            from PIL import Image
            import io
            pil_img = Image.open(io.BytesIO(img_bytes))
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        if img is None:
            return jsonify({"result": "NOT_DETECTED"}), 200
        
        results = reader.readtext(img)
        
        if not results:
            return jsonify({"result": "NOT_DETECTED"}), 200
        
        text = " ".join([r[1] for r in results]).upper()
        plate = "".join([c for c in text if c.isalnum()])
        
        if len(plate) < 5:
            return jsonify({"result": "NOT_DETECTED"}), 200
        
        filename = f"{int(time.time())}_{plate}.jpg"
        cv2.imwrite(f"static/uploads/{filename}", img)
        
        gc.collect()
        
        return jsonify({
            "result": "DETECTED",
            "plate": plate,
            "image": filename
        }), 200
    
    except:
        return jsonify({"result": "NOT_DETECTED"}), 200

# Whitelist Routes
@app.route("/whitelist", methods=["GET"])
def get_whitelist():
    return jsonify(read_csv(WHITELIST_FILE)), 200

@app.route("/whitelist/add", methods=["POST"])
def add_whitelist():
    data = request.get_json() or {}
    plate = data.get("plate", "").upper().replace(" ", "")
    owner = data.get("owner", "")
    
    if not plate or len(plate) < 4:
        return jsonify({"error": "Invalid plate"}), 400
    
    rows = read_csv(WHITELIST_FILE)
    if any(r['plate'].upper() == plate for r in rows):
        return jsonify({"status": "exists"}), 400
    
    entry = {
        'plate': plate,
        'owner': owner,
        'added_date': datetime.now().strftime("%Y-%m-%d")
    }
    append_csv(WHITELIST_FILE, entry, ['plate', 'owner', 'added_date'])
    
    return jsonify({"status": "added", "plate": plate}), 200

@app.route("/whitelist/remove", methods=["POST"])
def remove_whitelist():
    data = request.get_json() or {}
    plate = data.get("plate", "").upper()
    
    rows = read_csv(WHITELIST_FILE)
    rows = [r for r in rows if r['plate'].upper() != plate]
    write_csv(WHITELIST_FILE, rows, ['plate', 'owner', 'added_date'])
    
    return jsonify({"status": "removed"}), 200

# Blacklist Routes
@app.route("/blacklist", methods=["GET"])
def get_blacklist():
    return jsonify(read_csv(BLACKLIST_FILE)), 200

@app.route("/blacklist/add", methods=["POST"])
def add_blacklist():
    data = request.get_json() or {}
    plate = data.get("plate", "").upper().replace(" ", "")
    reason = data.get("reason", "")
    
    if not plate or len(plate) < 4:
        return jsonify({"error": "Invalid plate"}), 400
    
    rows = read_csv(BLACKLIST_FILE)
    if any(r['plate'].upper() == plate for r in rows):
        return jsonify({"status": "exists"}), 400
    
    entry = {
        'plate': plate,
        'reason': reason,
        'added_date': datetime.now().strftime("%Y-%m-%d")
    }
    append_csv(BLACKLIST_FILE, entry, ['plate', 'reason', 'added_date'])
    
    return jsonify({"status": "added"}), 200

@app.route("/blacklist/remove", methods=["POST"])
def remove_blacklist():
    data = request.get_json() or {}
    plate = data.get("plate", "").upper()
    
    rows = read_csv(BLACKLIST_FILE)
    rows = [r for r in rows if r['plate'].upper() != plate]
    write_csv(BLACKLIST_FILE, rows, ['plate', 'reason', 'added_date'])
    
    return jsonify({"status": "removed"}), 200

# Log Routes
@app.route("/log", methods=["GET"])
def get_log():
    limit = request.args.get("limit", 100, type=int)
    rows = read_csv(LOG_FILE)
    rows.reverse()
    return jsonify(rows[:limit]), 200

@app.route("/log/clear", methods=["POST"])
def clear_log():
    write_csv(LOG_FILE, [], ['id', 'plate', 'status', 'timestamp', 'image_file', 'confidence'])
    return jsonify({"status": "cleared"}), 200

# Export Routes
@app.route("/export/csv", methods=["GET"])
def export_csv():
    rows = read_csv(LOG_FILE)
    
    output = StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=detection_log.csv"}
    ), 200

@app.route("/export/json", methods=["GET"])
def export_json():
    rows = read_csv(LOG_FILE)
    
    return jsonify({
        "export_date": datetime.now().isoformat(),
        "total_detections": len(rows),
        "data": rows
    }), 200

@app.route("/export/pdf", methods=["GET"])
def export_pdf():
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        
        rows = read_csv(LOG_FILE)
        
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=letter)
        elements = []
        
        styles = getSampleStyleSheet()
        title = Paragraph("Smart Gate System - Detection Report", styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 0.3))
        
        summary = f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>Total Detections: {len(rows)}"
        summary_para = Paragraph(summary, styles['Normal'])
        elements.append(summary_para)
        elements.append(Spacer(1, 0.3))
        
        if rows:
            data = [['Plate', 'Status', 'Timestamp', 'Confidence']]
            for row in rows[-20:]:
                data.append([
                    row.get('plate', '--'),
                    row.get('status', '--'),
                    row.get('timestamp', '--'),
                    row.get('confidence', '--')
                ])
            
            table = Table(data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(table)
        
        doc.build(elements)
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="detection_report.pdf"
        ), 200
    except:
        return jsonify({"error": "PDF generation failed"}), 500

# Settings Routes
@app.route("/settings", methods=["GET"])
def get_settings_route():
    return jsonify(get_settings()), 200

@app.route("/settings", methods=["POST"])
def update_settings():
    global detection_sensitivity
    data = request.get_json() or {}
    
    settings = get_settings()
    settings.update(data)
    
    if 'sensitivity' in data:
        detection_sensitivity = int(data['sensitivity'])
    
    save_settings(settings)
    return jsonify({"status": "saved"}), 200

# Stats Routes
@app.route("/stats", methods=["GET"])
def get_stats():
    rows = read_csv(LOG_FILE)
    total = len(rows)
    
    return jsonify({
        "total": total,
        "whitelist": sum(1 for r in rows if r.get('status') == 'WHITELIST'),
        "blacklist": sum(1 for r in rows if r.get('status') == 'BLACKLIST'),
        "unknown": sum(1 for r in rows if r.get('status') == 'UNKNOWN'),
        "sensitivity": detection_sensitivity
    }), 200

if __name__ == "__main__":
    print("🌐 http://localhost:5000")
    print("✓ All features enabled\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)