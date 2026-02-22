import os
import csv
import cv2
import easyocr
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
LOG_FILE = "vehicle_logs.csv"
WHITELIST_FILE = "whitelist.txt"
BLACKLIST_FILE = "blacklist.txt"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize OCR reader
reader = easyocr.Reader(['en'])

# ---------------------------------------------------
# Load Whitelist
# ---------------------------------------------------
def load_whitelist():
    if not os.path.exists(WHITELIST_FILE):
        return []
    with open(WHITELIST_FILE, "r") as f:
        return [line.strip().upper() for line in f.readlines()]

# ---------------------------------------------------
# Load Blacklist
# ---------------------------------------------------
def load_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        return []
    with open(BLACKLIST_FILE, "r") as f:
        return [line.strip().upper() for line in f.readlines()]

# ---------------------------------------------------
# Save Log
# ---------------------------------------------------
def save_log(plate, status, image_name):
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(["Plate Number", "Date", "Time", "Status", "Image"])

        now = datetime.now()
        writer.writerow([
            plate,
            now.strftime("%d-%m-%Y"),
            now.strftime("%H:%M:%S"),
            status,
            image_name
        ])

# ---------------------------------------------------
# Plate Detection Function
# ---------------------------------------------------
def detect_plate(image_path):
    try:
        img = cv2.imread(image_path)

        if img is None:
            return "NO IMAGE"

        # Image Preprocessing (Improves ESP32 Accuracy)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        results = reader.readtext(thresh)

        for (bbox, text, prob) in results:
            plate = text.strip().upper().replace(" ", "")
            if len(plate) >= 6:
                return plate

        return "NO PLATE FOUND"

    except Exception as e:
        print("Detection Error:", e)
        return "PROCESSING ERROR"

# ---------------------------------------------------
# Home Page
# ---------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------------------------------------------
# Browser Upload Route
# ---------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    if "image" not in request.files:
        return render_template("result.html",
                               plate="NO IMAGE",
                               status="ERROR")

    image = request.files["image"]
    filepath = os.path.join(UPLOAD_FOLDER, image.filename)
    image.save(filepath)

    plate = detect_plate(filepath)

    whitelist = load_whitelist()
    blacklist = load_blacklist()

    if plate in blacklist:
        status = "BLOCKED"
    elif plate in whitelist:
        status = "GRANTED"
    else:
        status = "UNKNOWN"

    save_log(plate, status, image.filename)

    return render_template("result.html",
                           plate=plate,
                           status=status)

# ---------------------------------------------------
# ESP32 Upload API
# ---------------------------------------------------
@app.route("/esp32_upload", methods=["POST"])
def esp32_upload():
    if "image" not in request.files:
        return jsonify({"status": "ERROR", "plate": "NO IMAGE"})

    image = request.files["image"]
    filepath = os.path.join(UPLOAD_FOLDER, image.filename)
    image.save(filepath)

    plate = detect_plate(filepath)

    whitelist = load_whitelist()
    blacklist = load_blacklist()

    if plate in blacklist:
        status = "BLOCKED"
    elif plate in whitelist:
        status = "GRANTED"
    else:
        status = "UNKNOWN"

    save_log(plate, status, image.filename)

    return jsonify({
        "status": status,
        "plate": plate
    })

# ---------------------------------------------------
# View Logs
# ---------------------------------------------------
@app.route("/logs")
def view_logs():
    logs = []

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='r') as file:
            reader_csv = csv.reader(file)
            next(reader_csv, None)
            for row in reader_csv:
                logs.append(row)

    return render_template("logs.html", logs=logs)

# ---------------------------------------------------
# Run Server
# ---------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)