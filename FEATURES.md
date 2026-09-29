# BLE Measurement Tool — Features

This document outlines the core capabilities and workflows of the BLE Measurement web application.

## 1. Project & Campaign Management
- **Campaign Persistence**: All sessions are saved into isolated folders under `campaigns/<campaign-name>/`.
- **Auto-Saving**: Measurements are instantly written to disk (CSV and JSON) upon capture.
- **Resume Capability**: You can leave the app and resume any previous campaign exactly where you left off, with all previous data loaded and mapped.

## 2. Map & Grid Interface
- **Floor Plan Processing**: Upload any image of a floor plan.
- **Color Stripping**: A built-in image processor lets you select a hex color (and tolerance) to strip background colors from the map, leaving only the architectural lines.
- **Dynamic Measurement Grid**: Superimposes a perfectly scaled grid over the map.
  - Configurable cell size (e.g., 1.0m, 0.5m).
  - Configurable scale (Pixels per meter).
- **Axis Numbering**: The X-axis (columns) and Y-axis (rows) are clearly numbered along the top and left edges for easy spatial orientation.
- **Visual Color Coding**:
  - **Transparent**: Unmeasured cell.
  - **Blue**: BLE data measured (No App-reported position).
  - **Green**: Full measurement (BLE data + App-reported position).
  - **Red Box**: Your current "True" physical cursor.
  - **Gold Box**: The last recorded "App-reported" cursor.
- **Keyboard Navigation**: Move your selection cursor rapidly around the map using arrow keys.
- **Advanced Sliders**: Sliders feature paired text-input boxes for precise numerical entry, and a popover "Range" setting to dynamically adjust their minimum and maximum limits.

## 3. Data Capture Workflows
### Manual Capture
1. **True Position**: Click the map to set your physical location.
2. **Scan**: Triggers a fast, asynchronous BLE scan (configurable duration).
3. **App Position Prompt**: The UI locks and asks you to click the map to log where your navigation App *thinks* you are.
4. **Overhead Beacon Check**: A form appears asking if there is a physical beacon installed overhead. If Yes, you can log its ID, Major (dec), and Minor (dec).
5. **Overwrite Protection**: If you attempt to capture data on a cell that already has a measurement, a warning asks if you want to overwrite it (cleaning up the old data).

### Continuous Auto-Capture
- Ideal for walking in a straight line.
- Set an interval (e.g., 10 seconds), a direction (N/S/E/W), and click Start.
- The app will automatically scan, save, and advance your position by one cell endlessly until it hits a wall or you press Stop.

## 4. Bluetooth Engine (`bleak`)
- **Active Scanning**: Forces the OS to ping nearby devices to actively fetch their local names (bypassing OS passive caching).
- **Eddystone Identification**: Automatically identifies and labels beacons broadcasting the Eddystone™ service UUID (`0xFEAA`), even if they don't broadcast a text name.
- **Payload Extraction**: Pulls deep LTV (Length-Type-Value) advertising data, including Manufacturer Data and Service Data, converted cleanly to hex strings for raw analysis.

## 5. Data Analytics & Export
- **Aggregates (CSV)**: For clean spreadsheet analysis, the CSV stores standard metadata and calculated statistics per device:
  - Total Sample count (number of instantaneous pings).
  - Mean RSSI.
  - Median RSSI.
  - Variance of RSSI.
- **Raw Data (JSON)**: For deep data science, the JSON export includes an `rssi_readings` array containing *every single instantaneous ping* received during the time window.
- **Undo / Clear**: 
  - An **Undo** button lets you instantly pop the last measurement off the stack and delete it from your files.
  - A **Clear Measurements** button totally scrubs the campaign clean.

---
*Note: This document is kept up to date alongside the codebase.*
