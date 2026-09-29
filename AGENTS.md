# Agent Instructions & Project Memory
*This file contains long-running directives, architectural constraints, and UX philosophies established during development. Agents working on this repository should adhere to these rules.*

## 1. UI & UX Philosophy (Streamlit)
- **Keep it Light & Core-Focused**: Avoid over-engineering the UI with complex tabs or disjointed menus. Focus on inline, state-driven workflows.
- **State Machine Workflows**: Use `st.session_state` to transition the user through multi-step processes on the same screen (e.g., the manual capture workflow: Scan -> Click App Location -> Enter Beacon Info). Do not force the user to open new tabs or hidden sidebars for core operational steps.
- **Direct Spatial Interaction**: If the user needs to input a location (True physical position or App-reported position), it MUST be done by clicking directly on the canvas map or using keyboard arrow keys. Do not use dropdowns or text inputs for coordinate selection.
- **Advanced Sliders Only**: Do not use standard `st.slider` calls for critical parameters. Always use the custom `_advanced_slider` helper (in `app.py`) which pairs the slider with a precise text-input box and a popover configuration menu to adjust bounds dynamically.

## 2. Hardware & Bluetooth Rules
- **Active Scanning**: `BleakScanner` must always run with `scanning_mode="active"` to bypass OS caching and fetch local device names effectively.
- **Eddystone Handling**: Phone apps inherently recognize Eddystone beacons by their UUID, not their broadcast name. The scanner logic must explicitly check for `0000feaa-0000-1000-8000-00805f9b34fb` and label the device `Eddystone™` automatically.
- **Raw Payloads**: Always extract and store the full hex values of `manufacturer_data` and `service_data` for downstream analysis.

## 3. Data Integrity & Persistence
- **Dual-Storage Requirement**: Data must always be persisted in two formats simultaneously:
  1. **CSV**: For clean aggregate data (Mean, Median, Variance, Sample Count).
  2. **JSON**: For deep raw data (Arrays containing every instantaneous RSSI ping).
- **Overwrite Protection**: Never allow duplicate measurements for the exact same grid cell without warning the user. If the user proceeds, actively scrub the old data from memory and rewrite the CSV/JSON files entirely to prevent corruption or phantom duplicates.
- **Destructive Actions**: Functions like `Undo` or `Clear` must fully cascade down to the disk files (rewriting them empty or removing the popped element). Modifying only `st.session_state` is insufficient.

## 4. Performance Constraints
- **Image Resizing**: Never use `Image.LANCZOS` or expensive convolutional filters for scaling large floor plans in real-time. Use `Image.NEAREST`—it is orders of magnitude faster and keeps architectural/grid lines perfectly crisp and blocky.
- **Canvas Remounting**: Do not pass rapidly changing variables (like cursor selection) into the `key` argument of `st_canvas`. The key should only change when the fundamental grid layout (cell size) changes to prevent the React component from flashing/remounting.

## 5. Behaviour
For each change you do update the following documents:
README.md - Has set up Instructions. If they change, update this file.
FEATURES.md - Has a list of features present in the app. *WHAT* the app does. Keep this updated.
TRD.md - Has technical implemenatation details. *HOW* the app does it. Keep this also updated with each feature change or bugfix.
