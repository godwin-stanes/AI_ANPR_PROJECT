from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import cv2
import numpy as np
import easyocr
import os
import time
import gc

app = Flask(__name__, static_folder='static')
CORS(app)

os.makedirs('static/uploads', exist_ok=True)

print("\n🚗 Loading OCR...")
reader = easyocr.Reader(['en'], gpu=False)
print("✓ Ready!\n")

# Global state
camera_active = False
detection_result = "WAITING"
detected_plate = ""
latest_image = None
frame_buffer = []

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/stream")
def stream():
    """Live camera stream"""
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
    """IR triggered"""
    global camera_active, detection_result, detected_plate
    
    camera_active = True
    detection_result = "PROCESSING"
    detected_plate = ""
    
    print("\n🚨 IR TRIGGERED!")
    return jsonify({"status": "ok"}), 200

@app.route("/capture", methods=["POST"])
def capture():
    """Get image from ESP32-CAM"""
    global camera_active, detection_result, detected_plate, latest_image, frame_buffer
    
    try:
        if not camera_active:
            return jsonify({"result": "WAITING"}), 200
        
        img_bytes = request.data
        if not img_bytes:
            camera_active = False
            return jsonify({"result": "DENIED"}), 400
        
        # Decode image
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
        
        if img is None:
            camera_active = False
            return jsonify({"result": "DENIED"}), 200
        
        # Store frame
        frame_buffer.clear()  # Clear old frames
        frame_buffer.append(img)
        latest_image = img
        
        print("  📸 Processing image...")
        
        # OCR
        results = reader.readtext(img)
        
        if not results:
            print("  ❌ No plate")
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"result": "DENIED"}), 200
        
        # Extract text
        text = " ".join([r[1] for r in results]).upper()
        plate = "".join([c for c in text if c.isalnum()])
        
        if len(plate) < 5:
            print("  ❌ Invalid plate")
            detection_result = "NO_PLATE"
            camera_active = False
            return jsonify({"result": "DENIED"}), 200
        
        print(f"  ✓ Detected: {plate}")
        detected_plate = plate
        
        # Save
        filename = f"{int(time.time())}_{plate}.jpg"
        cv2.imwrite(f"static/uploads/{filename}", img)
        
        detection_result = "ALLOWED"
        camera_active = False
        
        # Clean memory
        gc.collect()
        
        return jsonify({
            "result": "ALLOW",
            "plate": plate,
            "image": filename
        }), 200
    
    except Exception as e:
        print(f"  Error: {e}")
        camera_active = False
        detection_result = "ERROR"
        gc.collect()
        return jsonify({"result": "DENIED"}), 500

@app.route("/result", methods=["GET"])
def result():
    """Get result for Arduino"""
    result_text = "ALLOW" if detection_result == "ALLOWED" else "DENY"
    return jsonify({"result": result_text, "plate": detected_plate}), 200

@app.route("/status", methods=["GET"])
def status():
    """Status"""
    return jsonify({
        "camera_active": camera_active,
        "detection_result": detection_result,
        "detected_plate": detected_plate
    }), 200

@app.route("/upload", methods=["POST"])
def upload():
    """Web upload"""
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
        
        print(f"✓ Upload: {plate}")
        
        gc.collect()
        
        return jsonify({
            "result": "DETECTED",
            "plate": plate,
            "image": filename
        }), 200
    
    except:
        return jsonify({"result": "NOT_DETECTED"}), 200

@app.route("/log", methods=["GET"])
def log():
    return jsonify([])

@app.route("/stats", methods=["GET"])
def stats():
    return jsonify({"total": 0, "whitelist": 0, "blacklist": 0, "unknown": 0})

@app.route("/whitelist", methods=["GET"])
def whitelist():
    return jsonify([])

@app.route("/blacklist", methods=["GET"])
def blacklist():
    return jsonify([])

if __name__ == "__main__":
    print("🌐 http://localhost:5000")
    print("✓ CLEAN mode - Memory optimized\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
