# Technical Requirements Document (TRD)

## 1. System Architecture
The application follows a modular, state-driven architecture built entirely in Python. It bridges low-level hardware interactions (Bluetooth LE) with a reactive frontend web interface.

### Core Stack
- **Frontend & State**: Streamlit (`app.py`)
- **Bluetooth Engine**: Bleak (`scanner.py`)
- **Image Rendering**: Pillow & NumPy (`image_processing.py`)
- **Canvas Interaction**: `streamlit-drawable-canvas` (React component wrapper)
- **Storage**: Standard library `csv`, `json`, and `dataclasses`.

## 2. Component Design & Data Flow

### 2.1 The Application State Machine (`app.py`)
The UI relies heavily on Streamlit's `st.session_state` to manage a continuous, un-interrupted workflow. The capture lifecycle follows a strict state machine dictated by the `capture_state` variable:
1. `idle`: The canvas accepts clicks to move the physical "True Position" cursor (Red box).
2. `awaiting_app_click`: Triggered after the BLE scan completes. The main UI controls are disabled, and canvas clicks are hijacked to set the "App-Reported Position".
3. `awaiting_beacon_info`: Triggered after the app position is clicked. A dynamic form appears to collect physical beacon metadata (Major, Minor, ID).
4. *Finalization*: `_save_measurement()` runs, scrubs any existing data for the cell (overwrite protection), appends to memory, and rewrites the disk files. State returns to `idle`.

### 2.2 Bluetooth Engine (`scanner.py`)
- Uses `BleakScanner` with `scanning_mode="active"`. Active scanning forces the host OS to send Scan Requests, prompting beacons to return Scan Responses containing Local Names.
- Intercepts all advertising packets and accumulates RSSI values per MAC address over a fixed async sleep window.
- **Eddystone Resolution**: Specifically inspects `advertisement.service_data` and `advertisement.service_uuids` for the Eddystone UUID (`0000feaa-0000-1000-8000-00805f9b34fb`). If found, it forces the device name to `Eddystone™`.
- Extracts LTV (Length-Type-Value) payloads (Manufacturer & Service Data) and serializes them to hex strings for downstream analysis.

### 2.3 High-Performance Rendering (`image_processing.py`)
Because floor plan images can be 4K+ resolution, image manipulation is heavily optimized:
- **Color Stripping**: Uses vectorized `NumPy` array math to calculate Euclidean distances of RGB pixels against a target color, instantly rewriting matching pixels to transparency.
- **Grid Composition**: The grid (boxes, lines, and axis numbering) is drawn exactly at the image's original resolution using `ImageDraw`.
- **Zoom Optimization**: To prevent massive CPU lag when scaling, `Image.NEAREST` is used instead of `Image.LANCZOS`. This reduces render times from >10s to <50ms and keeps architectural lines perfectly sharp.

### 2.4 Data Persistence (`session_store.py`)
Data is dual-written to guarantee both human readability and scientific reproducibility:
1. **CSV (Aggregates)**: Stores the Mean, Median, and Variance of the RSSI readings alongside the sample count and user-provided metadata. Designed for instant Pandas/Excel importing.
2. **JSON (Raw DB)**: Stores the exact array of instantaneous RSSI values (e.g., `[-70, -71, -70, -68]`) captured during the time window, ensuring zero data loss for post-processing.
- **Idempotency**: The save functions are designed so that the `Undo` and `Overwrite` UI actions can simply pass the modified memory array to completely overwrite the files on disk, ensuring state parity.
