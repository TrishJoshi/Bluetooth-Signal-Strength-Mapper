# Steerpath Bluetooth Beacons at Aalto University

## Overview
Aalto University utilizes Steerpath as the core technology for its indoor navigation and wayfinding solution, integrated into the "Aalto Space" campus application. It covers approximately 200,000 m² across about 18 buildings.

## Technical Details
*   **Positioning Technology:** Uses Bluetooth Low Energy (BLE) beacons for real-time indoor positioning on mobile devices.
*   **Accuracy:** Stated typical accuracy is 2–5 meters in office and university environments.
*   **Beacon Infrastructure:**
    *   **Placement:** Recommended ceiling mounting (center of rooms/corridors), roughly every 8 meters.
    *   **Height:** 2.5–5 meters from ground level.
    *   **Hardware:** Waterproof, long battery life (up to 4 years).
*   **Software System:**
    *   **Maps:** Vector-based maps for clarity at any zoom level.
    *   **Integration:** REST APIs connect with external systems like room booking.
    *   **Features:** Automatic floor detection and seamless navigation between buildings.
    *   **Setup:** Promoted as "calibration-free," placing beacons according to a pre-defined installation map without complex technical measurements.

## Hypothesis Validation
Your hypothesis regarding the "jumping" location and potential dead spots aligns with potential issues in such BLE setups:
1.  **Irregular Power / Dead Spots:** If beacons are placed every 8 meters, any physical obstruction, low battery, or offline beacon can easily create dead spots. Signal strength (RSSI) fluctuates significantly based on physical environment, leading to location jumps.
2.  **Algorithmic Shortfalls ("Sticking"):** Many indoor positioning algorithms use smoothing filters (like Kalman filters) or hysteresis to prevent jitter. If the algorithm relies heavily on the strongest signal, it might "stick" to a beacon until a significantly stronger signal is found, causing a delayed "jump" to the new location instead of smooth movement.

The measurement campaign you are planning will be very useful in mapping these RSSI variations and identifying actual dead spots or areas where the beacon density does not meet the 8-meter recommendation.
