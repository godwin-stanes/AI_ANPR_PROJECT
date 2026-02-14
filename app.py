from flask import Flask, render_template, request
import cv2
import easyocr
import os
import re
import csv
from datetime import datetime

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
LOG_FILE = "vehicle_log.csv"
WHITELIST_FILE = "whitelist.csv"
BLACKLIST_FILE = "blacklist.csv"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

reader = easyocr.Reader(['en'])

# -----------------------------
# CLEAN OCR TEXT
# -----------------------------
def clean_text(text):
    text = text.upper()
    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("O", "0")
    text = text.replace("I", "1")
    return text

# -----------------------------
# EXTRACT PLATE NUMBER
# -----------------------------
def extract_plate(text_list):
    combined_text = "".join(text_list)
    combined_text = clean_text(combined_text)

    plate_pattern = r'[0-9]{2}[A-Z]{1,3}[0-9]{4}'
    match = re.search(plate_pattern, combined_text)

    if match:
        return match.group()
    else:
        return "No Valid Plate Found"

# -----------------------------
# READ CSV FILE SAFELY
# -----------------------------
def read_plate_list(filename):
    plates = []

    if os.path.exists(filename):
        with open(filename, mode='r') as file:
            reader_csv = csv.reader(file)
            next(reader_csv, None)  # skip header

            for row in reader_csv:
                if row:
                    plate = row[0].strip().upper()
                    plates.append(plate)

    return plates

# -----------------------------
# CHECK ACCESS STATUS
# -----------------------------
def check_access(plate):
    whitelist = read_plate_list(WHITELIST_FILE)
    blacklist = read_plate_list(BLACKLIST_FILE)

    if plate in blacklist:
        return "DENIED"
    elif plate in whitelist:
        return "GRANTED"
    else:
        return "UNKNOWN"

# -----------------------------
# SAVE VEHICLE LOG
# -----------------------------
def save_log(plate, image_name, status):
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(["Plate Number", "Date", "Time", "Image", "Status"])

        now = datetime.now()
        date = now.strftime("%d-%m-%Y")
        time = now.strftime("%H:%M:%S")

        writer.writerow([plate, date, time, image_name, status])

# -----------------------------
# MAIN ROUTE
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    plate_number = ""
    image_path = ""
    access_status = ""

    if request.method == "POST":
        if "image" not in request.files:
            return render_template("index.html")

        file = request.files["image"]

        if file.filename != "":
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)
            image_path = filepath

            img = cv2.imread(filepath)
            result = reader.readtext(img)

            detected_texts = [detection[1] for detection in result]
            plate_number = extract_plate(detected_texts)

            if plate_number != "No Valid Plate Found":
                access_status = check_access(plate_number)
                save_log(plate_number, file.filename, access_status)

    return render_template("index.html",
                           plate_number=plate_number,
                           image_path=image_path,
                           access_status=access_status)

# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)
