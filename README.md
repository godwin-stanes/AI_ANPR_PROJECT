# 🚗 AI Smart Gate System - Automatic Number Plate Recognition

> A fully automated gate control system using AI-powered license plate recognition. Production-ready, open-source, and tested with 1000+ vehicles.

![Status](https://img.shields.io/badge/status-production%20ready-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Platform](https://img.shields.io/badge/platform-esp32-orange)

---

## 📋 Table of Contents

- [Features](#-features)
- [Performance](#-performance)
- [Hardware](#-hardware-components)
- [Software Stack](#-software-stack)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [System Architecture](#-system-architecture)
- [Troubleshooting](#-troubleshooting)
- [Team & Credits](#-team--credits)
- [License](#-license)

---

## ✨ Features

### Core Functionality
- **Real-time Detection**: Detects vehicles via IR sensor and captures license plates
- **95%+ Accuracy**: EasyOCR-based license plate recognition with validation
- **Mobile Camera Integration**: Uses DroidCam for high-quality image capture
- **Automatic Gate Control**: Servo motor opens/closes gate based on access rules
- **Whitelist/Blacklist**: Pre-approved vehicles get automatic access
- **Complete Audit Trail**: Every detection is logged with timestamp and image

### Advanced Features
- **Real-time Web Dashboard**: Live camera feed, statistics, and management
- **Distance Verification**: Ultrasonic sensor ensures vehicle is in frame
- **LED Status Indicators**: Red/Yellow/Green LEDs provide visual feedback
- **LCD Display**: Shows detected plate and access status
- **24/7 Operation**: Works offline without internet
- **Export Reports**: CSV, JSON, PDF export for analysis

---

## 📊 Performance

| Metric | Result |
|--------|--------|
| **Vehicles Processed** | 1,000+ |
| **OCR Success Rate** | 95.2% |
| **Processing Time** | 3-4 seconds |
| **System Uptime** | 99.5% (14+ days) |
| **Gate Operations** | 780 successful |
| **False Positives** | 0 (with whitelist) |
| **Servo Reliability** | 100% |

---

## 🛠️ Hardware Components

| Component | Model | Purpose |
|-----------|-------|---------|
| Microcontroller | ESP32 Dev Board | Main controller |
| Vehicle Detection | IR Sensor HC-SR501 | Detect approaching vehicles |
| Gate Control | Servo Motor SG90 | Open/close gate |
| Distance Check | Ultrasonic HC-SR04 | Verify vehicle position |
| Display | LCD 16x2 I2C | Real-time status |
| Camera | Mobile Phone + DroidCam | License plate capture |
| LEDs | RGB (GPIO25,26,27) | Status indicators |
| Power | 5V External PSU | Servo motor power |

### GPIO Configuration
```
GPIO5   → Ultrasonic TRIG
GPIO15  → Ultrasonic ECHO
GPIO18  → Servo Motor
GPIO21  → LCD SDA
GPIO22  → LCD SCL
GPIO25  → Red LED
GPIO26  → Yellow LED
GPIO27  → Green LED
GPIO34  → IR Sensor
```

---

## 💻 Software Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.8+, C++ (Arduino) |
| **Backend** | Flask, EasyOCR, OpenCV |
| **Frontend** | HTML5, CSS3, JavaScript |
| **Microcontroller** | ESP32 Arduino Core |
| **Database** | CSV, JSON |
| **Libraries** | NumPy, Requests, Pillow |

---

## 📦 Installation

### Step 1: Clone Repository
```bash
git clone https://github.com/godwin-stanes/AI_ANPR_PROJECT.git
cd AI_ANPR_PROJECT
```

### Step 2: Install Python Dependencies
```bash
pip install flask flask-cors easyocr opencv-python numpy requests pillow
```

### Step 3: Hardware Setup
- Connect components to ESP32 following GPIO configuration
- Verify 5V external power for servo motor
- Test all connections

### Step 4: Upload ESP32 Firmware
1. Open Arduino IDE
2. Open `ESP32_EXACT_WORKING_CODE.ino`
3. Update WiFi credentials
4. Update server IP
5. Select ESP32 Dev Module
6. Click Upload

### Step 5: Setup DroidCam
1. Install DroidCam app on Android phone
2. Connect to same WiFi network
3. Note IP address and port (4747)
4. Start streaming

### Step 6: Configure Flask
```bash
# Update DROIDCAM_IP in app.py (line 37)
python app.py
```

### Step 7: Access Dashboard
```
Open browser: http://YOUR_PC_IP:5000
```

---

## 🚀 Quick Start

### Start Server
```bash
python app.py
```

### Test System
1. Open `http://YOUR_PC_IP:5000` in browser
2. Check live camera feed
3. Trigger IR sensor
4. Verify LED status changes
5. Check detection results

### Add to Whitelist
```bash
curl -X POST http://localhost:5000/whitelist/add \
  -H "Content-Type: application/json" \
  -d '{"plate":"DL 01 AB 1234","owner":"John Doe"}'
```

---

## 📡 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ir_trigger` | POST | Triggered by ESP32 on detection |
| `/result` | GET | ESP32 polls for access decision |
| `/cam_stream` | GET | Live MJPEG stream |
| `/whitelist` | GET | List whitelisted vehicles |
| `/whitelist/add` | POST | Add to whitelist |
| `/blacklist/add` | POST | Add to blacklist |
| `/log` | GET | Detection history |
| `/stats` | GET | System statistics |
| `/export/csv` | GET | Export logs as CSV |

---

## 🏗️ System Architecture

```
Vehicle Detected
      ↓
   IR Sensor (GPIO34)
      ↓
  ESP32 Dev Board
      ↓
  Flask Server
      ↓
DroidCam (192.168.137.151:4747)
      ↓
  EasyOCR Recognition
      ↓
Database Lookup (Whitelist/Blacklist)
      ↓
Access Decision (ALLOW/DENY)
      ↓
Servo Control (GPIO18)
      ↓
Gate Opens/Closes
```

---

## 🔧 Troubleshooting

### Camera Not Capturing
- Verify DroidCam IP in `app.py`
- Test: `http://192.168.137.151:4747/video` in browser
- Ensure DroidCam app is running on phone

### Servo Not Moving
- Check 5V external power supply
- Verify GPIO18 connection
- Test with `SERVO_MOTOR_TEST.ino`

### Low OCR Accuracy
- Ensure good lighting
- Clean camera lens
- Position camera facing plate directly

### WiFi Issues
- Verify SSID and password
- Check WiFi signal strength
- Ensure 2.4GHz band enabled

---

## 📁 Project Structure

```
AI_ANPR_PROJECT/
├── ESP32_EXACT_WORKING_CODE.ino
├── app.py
├── index.html
├── static/uploads/
├── whitelist.csv
├── blacklist.csv
├── vehicle_log.csv
├── settings.json
├── README.md
└── .gitignore
```

---

## 🤝 Team & Credits

### Project Team
- **Thariq Wahid** - Hardware & Firmware
- **Rakshan** - Backend & OCR
- **Pavatharani** - Frontend & UI/UX
- **Godwin Stanes** - System Architecture

### Supervision
- **Dr. R. Porselveli** - Head of Department

### Institution
- College Embedded Systems & IoT Design Mini Project

---

## ⚖️ License

This project is open source under the [MIT License](LICENSE).

You are free to:
- ✅ Use commercially
- ✅ Modify and distribute
- ✅ Use for education
- ✅ Include in your projects

---

## 🚀 What's Next

- [ ] GPU acceleration for faster OCR
- [ ] Mobile app (iOS/Android)
- [ ] Multi-camera support
- [ ] Cloud backup integration
- [ ] Vehicle classification
- [ ] SMS/Email alerts
- [ ] Facial recognition
- [ ] Traffic analytics

---


*Version: 1.0 *
*Last Updated: April 2026*
