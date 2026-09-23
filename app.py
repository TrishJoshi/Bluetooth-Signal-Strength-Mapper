"""
BLE Measurement Campaign Tool — Streamlit App.

Run with:
    streamlit run app.py

Layout:
- Sidebar: all configuration (grid, scan, continuous mode, phone sensor).
- Main area: floor plan canvas, navigation buttons, capture button, results table.
"""

from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from image_processing import (
    cell_from_click,
    composite_grid,
    compute_grid_spacing_px,
    strip_color_range,
)
from models import GridCell, Measurement
from phone_sensor import PhoneSensorClient
from scanner import scan_ble_devices
from session_store import measurements_to_csv_bytes, measurements_to_json_bytes

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BLE Measurement Campaign",
    layout="wide",
    page_icon="📡",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults: dict = {
        "measurements": [],
        "selected_cell": GridCell(0, 0),
        "floor_plan_image": None,          # Processed PIL Image (with grid).
        "raw_floor_plan": None,            # Original uploaded PIL Image.
        "stripped_floor_plan": None,       # Color-stripped PIL Image.
        "continuous_running": False,
        "phone_client": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

_init_session_state()

# ---------------------------------------------------------------------------
# Sidebar: configuration
# ---------------------------------------------------------------------------

st.sidebar.title("⚙️ Configuration")

# --- Floor Plan Upload ---
st.sidebar.header("Floor Plan")
uploaded_file = st.sidebar.file_uploader(
    "Upload floor plan image", type=["jpg", "jpeg", "png"]
)
if uploaded_file and st.session_state.raw_floor_plan is None:
    st.session_state.raw_floor_plan = Image.open(uploaded_file).convert("RGB")
    st.session_state.stripped_floor_plan = st.session_state.raw_floor_plan.copy()

# --- Image Processing ---
st.sidebar.header("Image Processing")
strip_color_hex = st.sidebar.color_picker("Strip color", value="#FFFFFF")
strip_tolerance = st.sidebar.slider("Color tolerance", 0, 150, 30)
if st.sidebar.button("Apply color strip") and st.session_state.raw_floor_plan:
    r = int(strip_color_hex[1:3], 16)
    g = int(strip_color_hex[3:5], 16)
    b = int(strip_color_hex[5:7], 16)
    st.session_state.stripped_floor_plan = strip_color_range(
        st.session_state.raw_floor_plan, (r, g, b), strip_tolerance
    )

if st.sidebar.button("Reset image"):
    if st.session_state.raw_floor_plan:
        st.session_state.stripped_floor_plan = st.session_state.raw_floor_plan.copy()

# --- Grid Configuration ---
st.sidebar.header("Grid Settings")
pixels_per_meter = st.sidebar.slider(
    "Pixels per meter (scale)", min_value=10, max_value=300, value=60,
    help="Adjust until the grid matches real-world scale on the floor plan."
)
cell_size_meters = st.sidebar.select_slider(
    "Cell size (meters)", options=[0.25, 0.5, 1.0, 2.0], value=1.0
)
grid_spacing_px = compute_grid_spacing_px(pixels_per_meter, cell_size_meters)

# --- Scan Settings ---
st.sidebar.header("Scan Settings")
scan_duration = st.sidebar.slider(
    "Scan duration (seconds)", min_value=1, max_value=10, value=3
)
mac_filter_text = st.sidebar.text_area(
    "MAC address filter (one prefix per line, leave blank for all)",
    placeholder="E2:C5:6D\nD0:23:56",
    height=80,
)
mac_filter = [line.strip() for line in mac_filter_text.splitlines() if line.strip()]

# --- App-Reported Grid ---
st.sidebar.header("App Reported Position")
st.sidebar.caption("Enter the grid cell that the Aalto Space app reports.")
app_row = st.sidebar.number_input("App reported row", min_value=0, value=0, step=1)
app_col = st.sidebar.number_input("App reported col", min_value=0, value=0, step=1)

# --- Continuous Mode ---
st.sidebar.header("Continuous Mode")
continuous_direction = st.sidebar.selectbox(
    "Scan direction", ["E", "W", "N", "S"],
    format_func=lambda d: {"E": "→ East", "W": "← West", "N": "↑ North", "S": "↓ South"}[d],
)
continuous_interval = st.sidebar.slider(
    "Interval between captures (seconds)", min_value=1, max_value=60, value=5
)

# --- Phone Sensor ---
st.sidebar.header("Phone Sensor (ADB)")
if st.sidebar.button("Connect to phone"):
    client = PhoneSensorClient()
    if client.connect():
        st.session_state.phone_client = client
        st.sidebar.success("Connected to phone on port 5000.")
    else:
        st.sidebar.error("Connection refused. Is `adb forward tcp:5000 tcp:5000` running?")

if st.session_state.phone_client and st.session_state.phone_client.is_connected:
    if st.sidebar.button("Disconnect phone"):
        st.session_state.phone_client.disconnect()
        st.session_state.phone_client = None
    st.sidebar.success("📱 Phone connected")
else:
    st.sidebar.info("📵 Phone not connected")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.title("📡 BLE Measurement Campaign")

if st.session_state.stripped_floor_plan is None:
    st.info("👈 Upload a floor plan image in the sidebar to get started.")
    st.stop()

# ---------------------------------------------------------------------------
# Cached background image — only recompute when inputs change.
#
# The canvas component re-mounts (causing flicker) whenever its `key` changes
# OR when a new image object is passed on every rerun. We avoid both by:
#   1. Storing the rendered background in session state, tagged with a cache key
#      made from the actual inputs that affect the visual result.
#   2. Using a stable canvas key that only changes when the grid layout changes
#      (grid_spacing_px), NOT on every Python rerun.
# ---------------------------------------------------------------------------

selected = st.session_state.selected_cell
_bg_cache_key = (
    id(st.session_state.stripped_floor_plan),  # changes only when image is replaced
    grid_spacing_px,
    selected.row,
    selected.col,
)

if st.session_state.get("_bg_cache_key") != _bg_cache_key:
    canvas_bg = composite_grid(
        st.session_state.stripped_floor_plan,
        grid_spacing_px=grid_spacing_px,
        selected_cell=(selected.row, selected.col),
    )
    st.session_state["_bg_cache_key"] = _bg_cache_key
    st.session_state["_canvas_bg"] = canvas_bg
else:
    canvas_bg = st.session_state["_canvas_bg"]

img_width, img_height = canvas_bg.size

# Stable canvas key: only changes when grid spacing changes (layout change),
# not when the selected cell or other transient state changes.
_canvas_key = f"canvas_{grid_spacing_px}"

col_canvas, col_controls = st.columns([3, 1])

with col_canvas:
    st.subheader("Floor Plan")
    canvas_result = st_canvas(
        background_image=canvas_bg,
        height=img_height,
        width=img_width,
        drawing_mode="point",
        point_display_radius=0,   # Invisible point — we only care about coordinates.
        stroke_color="rgba(0,0,0,0)",
        fill_color="rgba(0,0,0,0)",
        key=_canvas_key,
    )
    # Map the last canvas click to a grid cell.
    if canvas_result.json_data:
        objects = canvas_result.json_data.get("objects", [])
        if objects:
            last = objects[-1]
            row, col = cell_from_click(last["left"], last["top"], grid_spacing_px)
            new_cell = GridCell(row, col)
            if new_cell != st.session_state.selected_cell:
                st.session_state.selected_cell = new_cell
                st.rerun()

with col_controls:
    st.subheader("Navigation")
    _cell_label = f"Row {selected.row}, Col {selected.col}"
    st.metric("Selected cell", _cell_label)

    # 3×3 directional button pad.
    pad_cols = st.columns(3)
    with pad_cols[1]:
        if st.button("▲", use_container_width=True):
            st.session_state.selected_cell = selected.moved("N")
            st.rerun()
    nav_cols = st.columns(3)
    with nav_cols[0]:
        if st.button("◀", use_container_width=True):
            st.session_state.selected_cell = selected.moved("W")
            st.rerun()
    with nav_cols[1]:
        st.button("●", disabled=True, use_container_width=True)
    with nav_cols[2]:
        if st.button("▶", use_container_width=True):
            st.session_state.selected_cell = selected.moved("E")
            st.rerun()
    down_cols = st.columns(3)
    with down_cols[1]:
        if st.button("▼", use_container_width=True):
            st.session_state.selected_cell = selected.moved("S")
            st.rerun()

    st.divider()

    # --- Capture ---
    st.subheader("Capture")
    capture_clicked = st.button("📡 Capture Snapshot", type="primary", use_container_width=True)
    if capture_clicked:
        with st.spinner(f"Scanning BLE for {scan_duration}s…"):
            scan_results = asyncio.run(
                scan_ble_devices(scan_duration, mac_filter or None)
            )
        measurement = Measurement(
            timestamp=datetime.now(),
            true_grid=GridCell(selected.row, selected.col),
            app_reported_grid=GridCell(int(app_row), int(app_col)),
            scan_results=scan_results,
            scan_duration_seconds=scan_duration,
        )
        st.session_state.measurements.append(measurement)
        device_count = len(scan_results)
        st.success(f"Captured {device_count} device(s) at {measurement.true_grid}.")

    st.divider()

    # --- Continuous Mode ---
    st.subheader("Continuous Mode")
    if not st.session_state.continuous_running:
        if st.button("▶ Start", use_container_width=True):
            st.session_state.continuous_running = True
            st.rerun()
    else:
        if st.button("⏹ Stop", type="secondary", use_container_width=True):
            st.session_state.continuous_running = False
            st.rerun()

    if st.session_state.continuous_running:
        max_rows = img_height // grid_spacing_px
        max_cols = img_width // grid_spacing_px
        next_cell = st.session_state.selected_cell.moved(continuous_direction)

        if not next_cell.is_valid(max_rows, max_cols):
            st.warning("Reached grid boundary — stopping.")
            st.session_state.continuous_running = False
            st.rerun()

        st.info(f"Next: {next_cell} in {continuous_interval}s…")
        with st.spinner(f"Scanning BLE for {scan_duration}s…"):
            scan_results = asyncio.run(
                scan_ble_devices(scan_duration, mac_filter or None)
            )
        measurement = Measurement(
            timestamp=datetime.now(),
            true_grid=GridCell(selected.row, selected.col),
            app_reported_grid=GridCell(int(app_row), int(app_col)),
            scan_results=scan_results,
            scan_duration_seconds=scan_duration,
        )
        st.session_state.measurements.append(measurement)
        time.sleep(max(0.0, continuous_interval - scan_duration))
        st.session_state.selected_cell = next_cell
        st.rerun()

# ---------------------------------------------------------------------------
# Results table & export
# ---------------------------------------------------------------------------

st.divider()
st.subheader(f"Measurements ({len(st.session_state.measurements)} captured)")

if st.session_state.measurements:
    # Build a flat DataFrame for display.
    rows = []
    for m in st.session_state.measurements:
        for r in m.scan_results:
            rows.append({
                "Timestamp": m.timestamp.strftime("%H:%M:%S"),
                "True (row,col)": str(m.true_grid),
                "App (row,col)": str(m.app_reported_grid),
                "MAC": r.mac_address,
                "Device": r.device_name,
                "RSSI mean (dBm)": r.rssi_mean,
                "RSSI median": r.rssi_median,
                "RSSI variance": r.rssi_variance,
                "Samples": r.sample_count,
            })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    export_cols = st.columns(2)
    metadata = {
        "pixels_per_meter": pixels_per_meter,
        "cell_size_meters": cell_size_meters,
        "scan_duration_seconds": scan_duration,
        "mac_filter": mac_filter,
    }
    with export_cols[0]:
        st.download_button(
            "⬇ Download CSV",
            data=measurements_to_csv_bytes(st.session_state.measurements),
            file_name=f"ble_measurements_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with export_cols[1]:
        st.download_button(
            "⬇ Download JSON",
            data=measurements_to_json_bytes(st.session_state.measurements, metadata),
            file_name=f"ble_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )

    if st.button("🗑 Clear all measurements"):
        st.session_state.measurements = []
        st.rerun()
else:
    st.info("No measurements yet. Select a grid cell and click 'Capture Snapshot'.")
