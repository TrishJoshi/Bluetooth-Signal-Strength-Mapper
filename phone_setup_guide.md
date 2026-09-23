# Phone BLE Streaming — Setup Guide

This guide explains how to set up your Android phone to stream BLE advertisement
data to the laptop over a USB cable using ADB port forwarding.

> **Key discovery:** `termux-api` has **no native BLE scan command**. Android does
> not expose Bluetooth through BlueZ or D-Bus (which Linux tools like `bleak` require).
> Android uses its own Bluetooth stack accessible only through Android SDK APIs.
> This means a native Android app is required to do the actual BLE scanning.
> The Python stub in `phone_sensor.py` implements the client side of the protocol.

---

## Option A: Mock Testing (No Phone Required)

For development and testing you can run a local mock server that generates fake BLE data:

```python
from phone_sensor import MockPhoneSensorServer, PhoneSensorClient

server = MockPhoneSensorServer(port=5000)
server.start()

client = PhoneSensorClient()
client.connect()

while True:
    packet = client.read_packet(timeout=1.0)
    if packet:
        print(packet)
```

---

## Option B: Real Phone via Termux (Mock Data Over ADB)

This option uses Termux to run a Python mock server on the phone. The data is
**simulated**, but the full USB tunnel pipeline is real — useful for validating
the connection before building a native Android scanner app.

### Step 1: Install Termux from F-Droid

> ⚠️ **Do NOT install Termux from Google Play.** The Play Store version has been
> broken since 2020 due to Android SDK restrictions.

1. Install [F-Droid](https://f-droid.org/) on your phone.
2. From F-Droid, install:
   - **Termux** (`com.termux`)
   - **Termux:API** (`com.termux.api`) — needed for sensors, not BLE.

### Step 2: Configure Android Permissions

1. **Settings → Apps → Termux → Permissions**: Grant **Location**, **Nearby Devices**.
2. **Settings → Apps → Termux → Battery**: Set to **Unrestricted** (prevents Android
   killing the server when the screen turns off).
3. Turn on **Location** in Android quick settings (required for any wireless scan).

### Step 3: Enable USB Debugging

1. **Settings → About Phone** → tap **Build Number** 7 times.
2. **Settings → Developer Options** → enable **USB Debugging**.
3. Connect phone to laptop via USB.
4. Accept the *"Allow USB debugging?"* prompt on the phone screen.

### Step 4: Verify ADB on Laptop

```bash
adb devices
# Expected:
# List of devices attached
# 1234567890ABCDEF    device
```

If it shows `unauthorized`, look at your phone and accept the pop-up.

### Step 5: Copy and Run the Mock Server in Termux

Open Termux on the phone, then run:

```bash
pkg update && pkg install python -y

# Create the mock server script
cat > ble_server.py << 'EOF'
import socket, json, time, random

DEVICES = [
    {"mac_address": "E2:C5:6D:B5:43:21", "device_name": "Steerpath Beacon A"},
    {"mac_address": "E2:C5:6D:B5:43:22", "device_name": "Steerpath Beacon B"},
    {"mac_address": "E2:C5:6D:B5:43:23", "device_name": "Steerpath Beacon C"},
]

def mock_packet():
    dev = random.choice(DEVICES)
    return {"mac_address": dev["mac_address"], "device_name": dev["device_name"],
            "rssi": random.randint(-90, -40), "tx_power": -59, "timestamp": time.time()}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 5000))
server.listen(1)
print("Listening on port 5000...")
while True:
    conn, addr = server.accept()
    print(f"Client connected: {addr}")
    try:
        while True:
            conn.sendall((json.dumps(mock_packet()) + "\n").encode())
            time.sleep(0.5)
    except (BrokenPipeError, ConnectionResetError):
        print("Client disconnected.")
    finally:
        conn.close()
EOF

python ble_server.py
```

### Step 6: Forward the Port on the Laptop

```bash
adb forward tcp:5000 tcp:5000

# Verify:
adb forward --list
# Output: <device-id>  tcp:5000  tcp:5000
```

### Step 7: Connect in the App

Click **"Connect to phone"** in the app sidebar. You should see "Connected" and the
phone sidebar status will show 📱.

---

## Option C: Real BLE Scanning (Native Android App)

For real BLE data you need a small native Android app that:
1. Uses `android.bluetooth.le.BluetoothLeScanner` to scan for advertisements.
2. Runs a `ServerSocket(5000)` and streams JSON packets over it.

The protocol the app must use matches `phone_sensor.py`:

```
{"mac_address": "AA:BB:CC:DD:EE:FF", "device_name": "Name", "rssi": -72, "timestamp": 1234567890.0}\n
```

Recommended approach: Use **nRF Connect for Mobile** (free, Nordic Semiconductor)
which can log BLE scan results, or ask us to scaffold a minimal Kotlin bridge app in
a future iteration.

---

## ADB Forward vs Reverse — Quick Reference

| Command | Who is the server? | Use case |
|---|---|---|
| `adb forward tcp:5000 tcp:5000` | **Phone** | Laptop connects to phone's server |
| `adb reverse tcp:5000 tcp:5000` | **Laptop** | Phone connects to laptop's server |

We use `adb forward` because the phone (Termux) runs the TCP server.

### Useful ADB commands

```bash
adb forward --list          # Show active forwarding rules
adb forward --remove-all    # Remove all rules
adb devices                 # List connected devices
```
