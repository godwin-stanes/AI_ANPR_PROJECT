# 🔌 SMART GATE SYSTEM - COMPLETE HARDWARE WIRING GUIDE

## 📋 HARDWARE COMPONENTS REQUIRED

### **ESP32-CAM Module**
- ESP32-CAM development board
- USB cable (USB-A to Micro USB)
- 5V USB power adapter or 12V external power supply

### **Servo Motor & Gate Control**
- 1x SG90 Servo Motor (9g) or larger (MG996R for heavier gates)
- 1x Relay Module (4-Channel 5V)
- 1x Jumper wires (set of 40)

### **LED Status Indicators**
- 4x LEDs:
  - Green (Access Granted)
  - Red (Access Blocked)
  - Orange (Alert/Caution)
  - Yellow (Unknown Vehicle)
- 4x 220Ω Resistors (current limiting)

### **Power Supply**
- 12V Power Supply (2A minimum)
- 5V Step-down converter or power bank
- Capacitor 1000µF (for servo power stability)

### **Additional Components**
- Breadboard (830-point)
- Jumper wires (male-to-male, male-to-female)
- USB cable for programming

---

## 🔋 POWER DISTRIBUTION DIAGRAM

```
Power Supply (12V)
     │
     ├──→ 5V Step-down Converter
     │           │
     │           ├──→ ESP32-CAM (5V)
     │           ├──→ LEDs Circuit (5V)
     │           └──→ Relay Module (5V)
     │
     └──→ Servo Motor (12V / 5V depending on servo type)
```

---

## 📌 ESP32-CAM PINOUT REFERENCE

```
ESP32-CAM Pin Configuration:

Front Side:
┌─────────────────────────────────────┐
│  U0T   U0R   GND   VCC   GND   3V3  │
│  (TX)  (RX)                          │
└─────────────────────────────────────┘

Left Side (Camera):           Right Side (GPIO):
│ CS   MOSI  MISO  SCLK       │ GND   5V
│ SDA   SCL                     │ GPIO4  (SERVO)
│ (Camera I2C)                  │ GPIO32 (LED GREEN)
                                │ GPIO33 (LED RED)
Back Side:                       │ GPIO25 (LED ORANGE)
┌─────────────────────────────────────┐
│  GND GND RXD TXD 5V GND 3V3         │
└─────────────────────────────────────┘
```

---

## 🔌 CONNECTION DETAILS

### **1. SERVO MOTOR CONNECTIONS**

**SG90 Servo Motor Pinout:**
```
Brown   = GND (Ground)
Red     = VCC (5V)
Orange  = Signal (GPIO4)
```

**Connections:**
```
Servo Brown  ───────→ GND
Servo Red    ───────→ 5V (through step-down if 12V servo)
Servo Orange ───────→ GPIO4 (with 220Ω resistor)
```

**Circuit Diagram:**
```
         +5V (from step-down)
          │
          ├───────────────┐
          │              ├─────→ Servo VCC (Red)
    1000µF Capacitor      │
          │               │
         GND  ────────────┘
          │
          └───────────────────→ Servo GND (Brown)

       GPIO4 (ESP32)
          │
        [220Ω]
          │
          └─────────────────→ Servo Signal (Orange)
```

---

### **2. LED STATUS INDICATORS**

**LED Configuration (Common Cathode):**

```
GPIO32 (GREEN LED)
    │
   [220Ω]
    │
   LED Anode
    │
   LED Cathode
    │
   GND

GPIO33 (RED LED)
    │
   [220Ω]
    │
   LED Anode
    │
   LED Cathode
    │
   GND

GPIO25 (ORANGE LED)
    │
   [220Ω]
    │
   LED Anode
    │
   LED Cathode
    │
   GND

GPIO26 (YELLOW LED)
    │
   [220Ω]
    │
   LED Anode
    │
   LED Cathode
    │
   GND
```

**Breadboard Layout for LEDs:**
```
GPIO32 ─┬─ [220Ω] ─┬─ Green LED Anode
        │          │
        │          └─ (Cathode) ─ GND

GPIO33 ─┬─ [220Ω] ─┬─ Red LED Anode
        │          │
        │          └─ (Cathode) ─ GND

GPIO25 ─┬─ [220Ω] ─┬─ Orange LED Anode
        │          │
        │          └─ (Cathode) ─ GND

GPIO26 ─┬─ [220Ω] ─┬─ Yellow LED Anode
        │          │
        │          └─ (Cathode) ─ GND
```

---

### **3. RELAY MODULE CONNECTIONS** (Optional - for gate motor)

**4-Channel Relay Module Pinout:**
```
GND  ─ Ground
VCC  ─ 5V
IN1  ─ GPIO27 (Relay 1 - Gate Motor)
IN2  ─ GPIO12 (Relay 2 - Unused)
IN3  ─ GPIO13 (Relay 3 - Unused)
IN4  ─ GPIO15 (Relay 4 - Unused)
COM  ─ Common
NO   ─ Normally Open
NC   ─ Normally Closed
```

**Relay Connection (for DC motor):**
```
Relay Module:
    GND ─────────→ ESP32 GND
    VCC ─────────→ 5V
    IN1 ─────────→ GPIO27

Relay Switching (AC/DC Motor):
    COM ────────→ +12V (from power supply)
    NO  ────────→ Gate Motor (+)
    Gate Motor (-) ──→ GND
```

---

## 🎯 COMPLETE WIRING TABLE

| Component | ESP32 Pin | Color | Connection | Purpose |
|-----------|-----------|-------|-----------|---------|
| Servo Motor | GPIO4 | Orange | Signal | Gate Control |
| Servo Motor | GND | Brown | Ground | Gate Control |
| Servo Motor | 5V | Red | Power | Gate Control |
| LED Green | GPIO32 | Green | Signal | Access Granted |
| LED Red | GPIO33 | Red | Signal | Access Blocked |
| LED Orange | GPIO25 | Orange | Signal | Alert |
| LED Yellow | GPIO26 | Yellow | Signal | Unknown |
| Relay IN1 | GPIO27 | Purple | Signal | Gate Motor |
| Relay VCC | 5V | Red | Power | Relay Power |
| Relay GND | GND | Black | Ground | Relay Ground |

---

## 🛠️ STEP-BY-STEP WIRING INSTRUCTIONS

### **Step 1: Power Distribution**
1. Connect 12V power supply positive to step-down converter input
2. Connect 12V power supply negative (GND) to step-down converter
3. Connect step-down converter output (5V) to breadboard positive rail
4. Connect step-down converter GND to breadboard negative rail

### **Step 2: ESP32-CAM Power**
1. Connect breadboard +5V to ESP32-CAM VCC pin
2. Connect breadboard GND to ESP32-CAM GND pin
3. Add 1000µF capacitor across power rails for stabilization

### **Step 3: Servo Motor**
1. Connect servo GND (brown wire) to breadboard GND
2. Connect servo 5V (red wire) to breadboard +5V (with capacitor)
3. Connect servo Signal (orange wire) to GPIO4 through 220Ω resistor

### **Step 4: LED Indicators**
For each LED:
1. Connect GPIO pin through 220Ω resistor to LED anode (longer leg)
2. Connect LED cathode (shorter leg) to GND
3. Repeat for all 4 LEDs (GPIO32, 33, 25, 26)

### **Step 5: Relay Module** (Optional)
1. Connect Relay VCC to breadboard +5V
2. Connect Relay GND to breadboard GND
3. Connect Relay IN1 to GPIO27
4. Connect Relay COM to gate motor power
5. Connect Relay NO to gate motor load

### **Step 6: USB Connection**
1. Connect USB cable to ESP32-CAM micro USB port
2. Connect USB cable to PC for programming
3. Or use external 5V power instead of USB

---

## 🔋 POWER CONSUMPTION ESTIMATES

| Component | Voltage | Current | Power |
|-----------|---------|---------|-------|
| ESP32-CAM | 5V | 200mA | 1W |
| Servo Motor | 5V | 500mA (no load) | 2.5W |
| Servo Motor | 5V | 1A (under load) | 5W |
| LED (per) | 5V | 20mA | 0.1W |
| 4x LEDs | 5V | 80mA | 0.4W |
| Relay Module | 5V | 100mA | 0.5W |
| Gate Motor | 12V | 2-5A | 24-60W |
| **Total System** | 5V + 12V | - | **~35-70W** |

**Recommended Power Supply:** 12V/3A = 36W minimum

---

## ⚠️ IMPORTANT SAFETY NOTES

1. **Always use a step-down converter** - Don't connect 12V directly to ESP32
2. **Add capacitors** - Stabilize servo power to prevent resets
3. **Use resistors** - Limit LED current to prevent burnout
4. **Relay isolation** - Keep high-voltage motor circuit separate
5. **Ground all circuits** - Common ground for 5V and 12V systems
6. **USB power** - Only use for programming, not continuous operation
7. **Wire gauge** - Use at least 22AWG for power distribution

---

## 🧪 TESTING CHECKLIST

- [ ] Power supply connected and stable (multimeter check)
- [ ] ESP32-CAM boots up (Serial monitor at 115200 baud)
- [ ] WiFi connects successfully
- [ ] All 4 LEDs light up during test
- [ ] Servo motor moves smoothly (0→90→0 degrees)
- [ ] Camera image captures
- [ ] Server receives image from ESP32

---

## 🚨 TROUBLESHOOTING

### **ESP32 not powering on**
- Check 5V power supply connection
- Verify USB cable is connected properly
- Try different USB cable
- Check power supply voltage with multimeter

### **LEDs not lighting**
- Verify GPIO pins in code match actual connections
- Check LED polarity (longer leg = positive)
- Test LED independently with battery
- Check resistor values (220Ω)

### **Servo not moving**
- Check signal wire connection to GPIO4
- Verify servo power (5V stable)
- Add capacitor for power stabilization
- Test servo with separate servo tester

### **WiFi not connecting**
- Check SSID and password in code
- Verify WiFi router is on same network
- Check WiFi signal strength
- Restart ESP32

### **Image not sending to server**
- Check server IP address is correct
- Verify network connectivity
- Check server is running (port 5000)
- Look at ESP32 serial output for errors

---

## 📐 BREADBOARD LAYOUT EXAMPLE

```
                    ╔══════════════════════╗
                    ║   ESP32-CAM Board    ║
                    ║                      ║
                    ║  GND   VCC   GPIO4   ║
                    ║   │     │      │     ║
                    ╚═══╪═════╪══════╪═════╝
                        │     │      │
                    ┌───┼─────┼──────┼────┐
                    │   │     │      │    │
              GND ──┴───┘     │      │    │
              ┌──────────────┬┴───┐  │    │
              │              │   │  │    │
    [Capacitor]            [220Ω] │    │
              │         Green LED  │    │
          +5V─┴──────────────────────┼────┼───→ Servo +5V
              │                      │    │
              │                      └────┼───→ Servo Signal
              │                           │
         GPIO32─────[220Ω]─────Green LED ──→ GND
         GPIO33─────[220Ω]─────Red LED ────→ GND
         GPIO25─────[220Ω]─────Orange LED ─→ GND
         GPIO26─────[220Ω]─────Yellow LED ─→ GND
```

---

## 🎯 FINAL VERIFICATION

Before running the system:

1. **Voltage Check:**
   - 5V at breadboard: 4.9V - 5.1V ✓
   - 12V at power supply: 11.8V - 12.2V ✓

2. **Connection Check:**
   - All GNDs connected together ✓
   - All power rails properly connected ✓
   - No loose wires or short circuits ✓

3. **Component Test:**
   - LEDs light individually ✓
   - Servo moves smoothly ✓
   - ESP32 responds to commands ✓

4. **Software Check:**
   - Arduino sketch compiles ✓
   - Serial monitor shows setup messages ✓
   - WiFi connects ✓

---

## 📸 CAMERA CONNECTION (Automatic on AI-Thinker Board)

Camera pins are pre-soldered on ESP32-CAM:
- Data pins: D0-D7
- Clock: XCLK
- Sync: VSYNC, HREF
- I2C: SDA (GPIO26), SCL (GPIO25)

**No manual wiring needed for camera!**

---

## ✅ YOU'RE READY!

Once all connections are verified, you can:
1. Upload Arduino code to ESP32-CAM
2. Update WiFi SSID & password
3. Update server IP address
4. Power on the system
5. Watch it work! 🚀

---

**Happy Building! 🔧✨**
