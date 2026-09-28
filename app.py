"""
BLE Measurement Campaign Tool — Streamlit App.

Run with:
    source venv/bin/activate && streamlit run app.py
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from campaign import Campaign, create_campaign, list_campaigns, save_floor_plan, update_settings
from image_processing import (
    cell_from_click,
    composite_grid,
    compute_grid_spacing_px,
    strip_color_range,
)
from models import GridCell, Measurement
from phone_sensor import PhoneSensorClient
from scanner import scan_ble_devices
from session_store import (
    append_measurement_csv,
    load_measurements_from_csv,
    measurements_to_csv_bytes,
    measurements_to_json_bytes,
    save_session_json,
)

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call.
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BLE Measurement Campaign",
    layout="wide",
    page_icon=":material/sensors:",
)

# ---------------------------------------------------------------------------
# CCv2 Arrow-key listener — registered once at module load.
#
# Listens for arrow-key presses on the parent window and fires a trigger
# with the cardinal direction (N/S/E/W) back to Python.
# ---------------------------------------------------------------------------

_ARROW_KEY_JS = """
export default function(component) {
  const { setTriggerValue } = component

  const KEY_DIR = {
    ArrowUp:    'N',
    ArrowDown:  'S',
    ArrowLeft:  'W',
    ArrowRight: 'E',
  }

  function onKeyDown(e) {
    const dir = KEY_DIR[e.key]
    if (dir) {
      e.preventDefault()
      setTriggerValue('direction', dir)
    }
  }

  window.addEventListener('keydown', onKeyDown)
  return () => window.removeEventListener('keydown', onKeyDown)
}
"""

_ARROW_KEY_COMPONENT = st.components.v2.component(
    "ble_arrow_key_listener",
    html="<div style='height:0;overflow:hidden;position:absolute'></div>",
    js=_ARROW_KEY_JS,
)

# ---------------------------------------------------------------------------
# Session state — centralised, explicit defaults.
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults: dict = {
        "active_campaign": None,         # Campaign | None
        "raw_floor_plan": None,          # PIL Image — original upload
        "stripped_floor_plan": None,     # PIL Image — after colour strip
        "measurements": [],              # list[Measurement]
        "selected_cell": GridCell(0, 0), # Ground-truth position
        "app_reported_cell": GridCell(0, 0),
        "click_mode": "true",            # "true" | "app"
        "continuous_running": False,
        "continuous_settings": {},       # snapshot of config when started
        "continuous_next_scan_at": 0.0,  # Unix timestamp
        "phone_client": None,
        "grid_max_rows": 100,
        "grid_max_cols": 100,
        "_bg_cache_key": None,
        "_canvas_bg": None,
    }
    for key, val in defaults.items():
        st.session_state.setdefault(key, val)


_init_session_state()


# ---------------------------------------------------------------------------
# Continuous mode — @st.fragment auto-refreshes every second independently
# of the rest of the app, driving the scan countdown and capture loop.
# ---------------------------------------------------------------------------

@st.fragment(run_every=1)
def _continuous_fragment() -> None:
    if not st.session_state.continuous_running:
        return

    cfg: dict = st.session_state.continuous_settings
    now = time.time()
    next_at: float = st.session_state.continuous_next_scan_at
    interval: int = cfg.get("interval", 5)
    remaining = max(0.0, next_at - now)

    # Countdown display.
    c_prog, c_metric = st.columns([5, 1])
    with c_prog:
        progress = 1.0 - (remaining / interval) if remaining > 0 else 1.0
        label = (
            f"Scanning at {st.session_state.selected_cell}…"
            if remaining <= 0
            else f"Moving to {st.session_state.selected_cell.moved(cfg.get('direction', 'E'))} in {remaining:.0f}s"
        )
        st.progress(min(progress, 1.0), text=label)
    with c_metric:
        if remaining > 0:
            st.metric("Countdown", f"{remaining:.0f}s", label_visibility="collapsed")
        else:
            st.metric("Countdown", "Now!", label_visibility="collapsed")

    if remaining > 0:
        return  # Still in the wait phase; fragment will tick again in ~1s.

    # --- Scan phase ---
    selected = st.session_state.selected_cell
    direction: str = cfg.get("direction", "E")
    scan_dur: int = cfg.get("scan_duration", 3)
    mac_filter = cfg.get("mac_filter") or None
    app_reported: GridCell = st.session_state.app_reported_cell
    campaign: Campaign | None = st.session_state.active_campaign

    with st.spinner(f"Scanning {scan_dur}s at {selected}…"):
        scan_results = asyncio.run(scan_ble_devices(scan_dur, mac_filter))

    measurement = Measurement(
        timestamp=datetime.now(),
        true_grid=GridCell(selected.row, selected.col),
        app_reported_grid=GridCell(app_reported.row, app_reported.col),
        scan_results=scan_results,
        scan_duration_seconds=float(scan_dur),
    )
    st.session_state.measurements.append(measurement)

    if campaign:
        append_measurement_csv(campaign.measurements_csv_path, measurement)
        _autosave_json(campaign)

    # Advance to the next cell.
    next_cell = selected.moved(direction)
    max_r = st.session_state.grid_max_rows
    max_c = st.session_state.grid_max_cols

    if not next_cell.is_valid(max_r, max_c):
        st.session_state.continuous_running = False
        st.session_state.continuous_next_scan_at = 0.0
        st.warning(":material/check_circle: Grid boundary reached — continuous mode stopped.")
        st.rerun(scope="app")
    else:
        st.session_state.selected_cell = next_cell
        st.session_state.continuous_next_scan_at = time.time() + interval
        st.rerun(scope="app")  # Full rerun so the canvas shows the new selected cell.


# ---------------------------------------------------------------------------
# Landing screen
# ---------------------------------------------------------------------------

def _show_landing_screen() -> None:
    st.title(":material/sensors: BLE Measurement Campaign")
    st.caption(
        "Measure Bluetooth signal strength across a floor plan grid to investigate "
        "Steerpath beacon coverage and location accuracy."
    )
    st.divider()

    tab_new, tab_resume = st.tabs([":material/add: New campaign", ":material/folder_open: Resume campaign"])

    with tab_new:
        with st.form("new_campaign_form", border=False):
            name = st.text_input("Campaign name", placeholder="Ground floor — Building CS")
            uploaded = st.file_uploader("Floor plan image", type=["jpg", "jpeg", "png"])
            if st.form_submit_button(":material/play_arrow: Create & start", type="primary"):
                if not name.strip():
                    st.error("Please enter a campaign name.")
                elif uploaded is None:
                    st.error("Please upload a floor plan image.")
                else:
                    campaign = create_campaign(name.strip())
                    image = Image.open(uploaded).convert("RGB")
                    save_floor_plan(campaign, image)
                    _activate_campaign(campaign, image, measurements=[])
                    st.rerun()

    with tab_resume:
        campaigns = list_campaigns()
        if not campaigns:
            st.info(":material/inbox: No saved campaigns found. Create one above.")
            return
        for c in campaigns:
            with st.container(border=True):
                cols = st.columns([5, 1])
                with cols[0]:
                    st.markdown(f"**{c.name}**")
                    st.caption(
                        f":material/schedule: {c.created_at.strftime('%Y-%m-%d %H:%M')}  ·  "
                        f":material/table_rows: {c.measurement_count} captured positions  ·  "
                        f":material/folder: `{c.directory.name}`"
                    )
                with cols[1]:
                    if st.button(":material/play_arrow: Resume", key=f"resume_{c.directory}"):
                        image = (
                            Image.open(str(c.floor_plan_path)).convert("RGB")
                            if c.floor_plan_path.exists()
                            else None
                        )
                        measurements = load_measurements_from_csv(c.measurements_csv_path)
                        _activate_campaign(c, image, measurements)
                        st.rerun()


def _activate_campaign(
    campaign: Campaign,
    image: Image.Image | None,
    measurements: list[Measurement],
) -> None:
    """Load a campaign and its floor plan into session state."""
    st.session_state.active_campaign = campaign
    st.session_state.raw_floor_plan = image
    st.session_state.stripped_floor_plan = image.copy() if image else None
    st.session_state.measurements = measurements
    st.session_state.selected_cell = GridCell(0, 0)
    st.session_state.app_reported_cell = GridCell(0, 0)
    st.session_state.click_mode = "true"
    st.session_state.continuous_running = False
    # Seed slider values from campaign settings (must be set before widgets render).
    st.session_state.pixels_per_meter = campaign.pixels_per_meter
    st.session_state.cell_size_meters = campaign.cell_size_meters
    st.session_state.scan_duration_s = campaign.scan_duration
    st.session_state.mac_filter_text = "\n".join(campaign.mac_filter)
    # Invalidate background cache.
    st.session_state["_bg_cache_key"] = None
    st.session_state["_canvas_bg"] = None


# ---------------------------------------------------------------------------
# Campaign screen — the main measurement UI.
# ---------------------------------------------------------------------------

def _show_campaign_screen() -> None:
    campaign: Campaign = st.session_state.active_campaign

    # --- Sidebar ---
    _render_sidebar(campaign)

    # Read sidebar-controlled session state values.
    pixels_per_meter: float = st.session_state.get("pixels_per_meter", 60.0)
    cell_size_meters: float = st.session_state.get("cell_size_meters", 1.0)
    scan_duration: int = int(st.session_state.get("scan_duration_s", 3))
    mac_filter_text: str = st.session_state.get("mac_filter_text", "")
    mac_filter = [ln.strip() for ln in mac_filter_text.splitlines() if ln.strip()]
    display_zoom: float = st.session_state.get("display_zoom", 1.0)

    grid_spacing_px = compute_grid_spacing_px(pixels_per_meter, cell_size_meters)

    # --- Top bar ---
    hdr_left, hdr_right = st.columns([5, 1])
    with hdr_left:
        st.title(f":material/sensors: {campaign.name}")
        st.caption(f":material/folder: `{campaign.directory}`")
    with hdr_right:
        if st.button(":material/arrow_back: Campaigns", key="back_btn"):
            _save_settings_and_leave(campaign, pixels_per_meter, cell_size_meters, scan_duration, mac_filter)

    if st.session_state.stripped_floor_plan is None:
        st.warning("No floor plan loaded. Go back and recreate the campaign.")
        st.stop()

    # --- Build composite background image (cached in session state) ---
    selected: GridCell = st.session_state.selected_cell
    app_reported: GridCell = st.session_state.app_reported_cell
    cell_states = _build_cell_states(st.session_state.measurements)

    orig_w, orig_h = st.session_state.stripped_floor_plan.size
    max_rows = max(1, orig_h // grid_spacing_px)
    max_cols = max(1, orig_w // grid_spacing_px)
    st.session_state.grid_max_rows = max_rows
    st.session_state.grid_max_cols = max_cols

    _bg_cache_key = (
        id(st.session_state.stripped_floor_plan),
        grid_spacing_px,
        display_zoom,
        selected.row, selected.col,
        app_reported.row, app_reported.col,
        tuple(sorted((str(k), v) for k, v in cell_states.items())),
    )

    if st.session_state.get("_bg_cache_key") != _bg_cache_key:
        canvas_bg = composite_grid(
            st.session_state.stripped_floor_plan,
            grid_spacing_px=grid_spacing_px,
            selected_cell=(selected.row, selected.col),
            app_reported_cell=(app_reported.row, app_reported.col),
            cell_states=cell_states,
            display_scale=display_zoom,
        )
        st.session_state["_bg_cache_key"] = _bg_cache_key
        st.session_state["_canvas_bg"] = canvas_bg
    else:
        canvas_bg = st.session_state["_canvas_bg"]

    disp_w, disp_h = canvas_bg.size  # Already scaled by display_zoom.

    # Stable canvas key — only changes when grid cell size (layout) changes.
    canvas_key = f"canvas_{grid_spacing_px}"

    # --- Arrow-key listener (CCv2) ---
    def _on_arrow_key() -> None:
        key_state = st.session_state.get("arrow_keys") or {}
        direction = key_state.get("direction") if isinstance(key_state, dict) else None
        if not direction:
            return
        new_cell = st.session_state.selected_cell.moved(direction)
        if new_cell.is_valid(st.session_state.grid_max_rows, st.session_state.grid_max_cols):
            st.session_state.selected_cell = new_cell

    _ARROW_KEY_COMPONENT(key="arrow_keys", data={}, on_direction_change=_on_arrow_key)

    # --- Main layout ---
    col_canvas, col_controls = st.columns([4, 1])

    with col_canvas:
        # Mode toggle — controls what a canvas click selects.
        st.segmented_control(
            "Click mode",
            options=["true", "app"],
            format_func=lambda m: (
                ":material/my_location: True position" if m == "true"
                else ":material/pin_drop: App reported"
            ),
            key="click_mode",
            label_visibility="collapsed",
        )

        # Canvas wrapped in a fixed-height scrollable container.
        with st.container(height=680, border=False):
            canvas_result = st_canvas(
                background_image=canvas_bg,
                height=disp_h,
                width=disp_w,
                drawing_mode="point",
                point_display_radius=0,
                stroke_color="rgba(0,0,0,0)",
                fill_color="rgba(0,0,0,0)",
                key=canvas_key,
            )

        # Map canvas click → grid cell.
        if canvas_result.json_data:
            objects = canvas_result.json_data.get("objects", [])
            if objects:
                last = objects[-1]
                orig_x = last["left"] / display_zoom
                orig_y = last["top"] / display_zoom
                row, col = cell_from_click(orig_x, orig_y, grid_spacing_px)
                clicked = GridCell(row, col)
                click_mode = st.session_state.get("click_mode", "true")
                if click_mode == "true" and clicked != selected:
                    st.session_state.selected_cell = clicked
                    st.rerun()
                elif click_mode == "app" and clicked != app_reported:
                    st.session_state.app_reported_cell = clicked
                    st.rerun()

    with col_controls:
        # --- Cell status ---
        st.subheader("Position")
        st.metric(":material/my_location: True cell", str(selected), help="Red highlight on map")
        st.metric(":material/pin_drop: App cell", str(app_reported), help="Gold highlight on map")

        # --- Arrow pad buttons ---
        r_up = st.columns(3)
        with r_up[1]:
            if st.button(":material/arrow_upward:", key="nav_n", help="North (↑)"):
                _move_selected("N", max_rows, max_cols)
        r_mid = st.columns(3)
        with r_mid[0]:
            if st.button(":material/arrow_back:", key="nav_w", help="West (←)"):
                _move_selected("W", max_rows, max_cols)
        with r_mid[1]:
            st.button(":material/location_on:", disabled=True, key="nav_ctr")
        with r_mid[2]:
            if st.button(":material/arrow_forward:", key="nav_e", help="East (→)"):
                _move_selected("E", max_rows, max_cols)
        r_down = st.columns(3)
        with r_down[1]:
            if st.button(":material/arrow_downward:", key="nav_s", help="South (↓)"):
                _move_selected("S", max_rows, max_cols)

        st.divider()

        # --- Capture ---
        st.subheader("Capture")
        if st.button(":material/sensors: Capture snapshot", type="primary", key="capture_btn"):
            _run_capture(selected, app_reported, scan_duration, mac_filter, campaign)

        st.divider()

        # --- Continuous mode controls ---
        st.subheader("Continuous")
        direction_options = {"E": "→ East", "W": "← West", "N": "↑ North", "S": "↓ South"}
        cont_dir = st.selectbox(
            "Direction",
            options=list(direction_options.keys()),
            format_func=direction_options.get,
            key="cont_direction",
            label_visibility="collapsed",
        )
        cont_interval = _advanced_slider("Interval (s)", "cont_interval", 1, 300, 10, is_int=True)

        if not st.session_state.continuous_running:
            if st.button(":material/play_arrow: Start auto-scan", key="cont_start"):
                st.session_state.continuous_settings = {
                    "direction": cont_dir,
                    "interval": cont_interval,
                    "scan_duration": scan_duration,
                    "mac_filter": mac_filter or None,
                }
                st.session_state.continuous_running = True
                st.session_state.continuous_next_scan_at = time.time()  # Scan immediately.
                st.rerun()
        else:
            if st.button(":material/stop: Stop", key="cont_stop", type="secondary"):
                st.session_state.continuous_running = False
                st.rerun()

        # The countdown display lives in its own fragment so it ticks every second.
        _continuous_fragment()

        st.divider()

        # --- Phone sensor ---
        _render_phone_sensor_controls()

    # --- Results table ---
    st.divider()
    _render_results_table(st.session_state.measurements, campaign, pixels_per_meter, cell_size_meters, scan_duration, mac_filter)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def _render_sidebar(campaign: Campaign) -> None:
    with st.sidebar:
        st.title(":material/settings: Settings")

        st.header("Image processing")
        strip_hex = st.color_picker("Strip colour", value="#FFFFFF")
        strip_tol = _advanced_slider("Tolerance", "strip_tol", 0, 255, 30, is_int=True)
        c1, c2 = st.columns(2)
        if c1.button("Apply strip", key="apply_strip"):
            r, g, b = int(strip_hex[1:3], 16), int(strip_hex[3:5], 16), int(strip_hex[5:7], 16)
            st.session_state.stripped_floor_plan = strip_color_range(
                st.session_state.raw_floor_plan, (r, g, b), strip_tol
            )
            st.session_state["_bg_cache_key"] = None
        if c2.button("Reset", key="reset_strip"):
            st.session_state.stripped_floor_plan = st.session_state.raw_floor_plan.copy()
            st.session_state["_bg_cache_key"] = None

        st.header("Grid settings")
        _advanced_slider(
            "Pixels per meter", "pixels_per_meter", 1, 1000, 60, is_int=True,
            help_text="Increase until one grid square matches 1 real metre on the floor plan."
        )
        _advanced_slider(
            "Cell size (m)", "cell_size_meters", 0.05, 10.0, 1.0, step=0.05
        )
        _advanced_slider(
            "Display zoom", "display_zoom", 0.1, 10.0, 1.0, step=0.1,
            help_text="Zoom in for finer grid interaction. Does not change measurement scale."
        )

        st.header("Scan settings")
        _advanced_slider("Scan duration (s)", "scan_duration_s", 1, 120, 3, is_int=True)
        st.text_area(
            "MAC filter (one prefix per line)",
            placeholder="E2:C5:6D\nD0:23:56",
            height=70,
            key="mac_filter_text",
        )

        st.divider()
        st.caption(f":material/folder: `{campaign.directory.name}`")
        n = len(st.session_state.measurements)
        st.caption(f":material/table_rows: {n} measurements this session")


# ---------------------------------------------------------------------------
# Results table
# ---------------------------------------------------------------------------

def _render_results_table(
    measurements: list[Measurement],
    campaign: Campaign,
    pixels_per_meter: float,
    cell_size_meters: float,
    scan_duration: int,
    mac_filter: list[str],
) -> None:
    count = len(measurements)
    st.subheader(f":material/table_rows: Measurements ({count} captured)")

    if not measurements:
        st.info("No measurements yet. Select a cell and click :material/sensors: Capture snapshot.")
        return

    rows = []
    for m in measurements:
        for r in m.scan_results:
            adv_str = " | ".join(f"{k}={v}" for k, v in r.adv_data.items())
            rows.append({
                "Time": m.timestamp.strftime("%H:%M:%S"),
                "True (r,c)": str(m.true_grid),
                "App (r,c)": str(m.app_reported_grid),
                "MAC": r.mac_address,
                "Device": r.device_name,
                "RSSI mean": r.rssi_mean,
                "RSSI median": r.rssi_median,
                "RSSI var": r.rssi_variance,
                "Samples": r.sample_count,
                "Raw Data": adv_str,
            })

    st.dataframe(pd.DataFrame(rows), hide_index=True)

    metadata = {
        "pixels_per_meter": pixels_per_meter,
        "cell_size_meters": cell_size_meters,
        "scan_duration_seconds": scan_duration,
        "mac_filter": mac_filter,
        "campaign": campaign.name,
    }
    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        st.download_button(
            ":material/download: CSV",
            data=measurements_to_csv_bytes(measurements),
            file_name=f"ble_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
    with dl2:
        st.download_button(
            ":material/download: JSON",
            data=measurements_to_json_bytes(measurements, metadata),
            file_name=f"ble_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
        )
    with dl3:
        if st.button(":material/delete: Clear measurements"):
            st.session_state.measurements = []
            st.rerun()


# ---------------------------------------------------------------------------
# Phone sensor controls
# ---------------------------------------------------------------------------

def _render_phone_sensor_controls() -> None:
    st.subheader("Phone (ADB)")
    client: PhoneSensorClient | None = st.session_state.phone_client

    if client and client.is_connected:
        st.success(":material/phone_android: Connected")
        if st.button(":material/link_off: Disconnect", key="phone_dc"):
            client.disconnect()
            st.session_state.phone_client = None
            st.rerun()
    else:
        st.caption("Connect phone via `adb forward tcp:5000 tcp:5000`")
        if st.button(":material/link: Connect", key="phone_conn"):
            c = PhoneSensorClient()
            if c.connect():
                st.session_state.phone_client = c
                st.rerun()
            else:
                st.error("Refused. Check ADB forward is running.")


# ---------------------------------------------------------------------------
# Action helpers — keep the campaign screen body readable.
# ---------------------------------------------------------------------------

def _advanced_slider(
    label: str,
    key: str,
    default_min: float,
    default_max: float,
    default_val: float,
    step: float = 1.0,
    is_int: bool = False,
    help_text: str = "",
) -> float:
    """A synced slider + text input with a popover to change min/max bounds."""
    t = int if is_int else float

    min_key = f"{key}_min"
    max_key = f"{key}_max"
    st.session_state.setdefault(min_key, t(default_min))
    st.session_state.setdefault(max_key, t(default_max))
    
    st.session_state.setdefault(key, t(default_val))
    st.session_state.setdefault(f"{key}_num", st.session_state[key])

    c_min = st.session_state[min_key]
    c_max = st.session_state[max_key]

    with st.popover(f"⚙️ {label} Range", help="Configure slider minimum and maximum"):
        col1, col2 = st.columns(2)
        new_min = col1.number_input("Min", value=c_min, key=f"ui_{min_key}")
        new_max = col2.number_input("Max", value=c_max, key=f"ui_{max_key}")
        c_min, c_max = t(new_min), t(new_max)
        if c_min > c_max:
            c_max = c_min
        st.session_state[min_key] = c_min
        st.session_state[max_key] = c_max

    if st.session_state[key] < c_min: st.session_state[key] = c_min
    if st.session_state[key] > c_max: st.session_state[key] = c_max

    def on_slider():
        st.session_state[f"{key}_num"] = st.session_state[key]

    def on_num():
        val = st.session_state[f"{key}_num"]
        if val < c_min: val = c_min
        if val > c_max: val = c_max
        st.session_state[key] = val

    if help_text:
        st.markdown(label, help=help_text)
    else:
        st.markdown(label)

    c_slider, c_num = st.columns([3, 1])
    with c_slider:
        st.slider(
            label, min_value=c_min, max_value=c_max, step=t(step), key=key,
            on_change=on_slider, label_visibility="collapsed"
        )
    with c_num:
        st.number_input(
            label, min_value=c_min, max_value=c_max, step=t(step), key=f"{key}_num",
            on_change=on_num, label_visibility="collapsed"
        )
        
    return st.session_state[key]


def _move_selected(direction: str, max_rows: int, max_cols: int) -> None:
    new_cell = st.session_state.selected_cell.moved(direction)
    if new_cell.is_valid(max_rows, max_cols):
        st.session_state.selected_cell = new_cell
    st.rerun()


def _run_capture(
    selected: GridCell,
    app_reported: GridCell,
    scan_duration: int,
    mac_filter: list[str],
    campaign: Campaign | None,
) -> None:
    with st.spinner(f"Scanning BLE for {scan_duration}s…"):
        scan_results = asyncio.run(scan_ble_devices(scan_duration, mac_filter or None))

    measurement = Measurement(
        timestamp=datetime.now(),
        true_grid=GridCell(selected.row, selected.col),
        app_reported_grid=GridCell(app_reported.row, app_reported.col),
        scan_results=scan_results,
        scan_duration_seconds=float(scan_duration),
    )
    st.session_state.measurements.append(measurement)

    if campaign:
        append_measurement_csv(campaign.measurements_csv_path, measurement)
        _autosave_json(campaign)

    st.success(f":material/check_circle: Captured {len(scan_results)} device(s) at {selected}.")


def _autosave_json(campaign: Campaign) -> None:
    """Overwrite session.json with the current full measurement set."""
    metadata = {
        "campaign": campaign.name,
        "pixels_per_meter": campaign.pixels_per_meter,
        "cell_size_meters": campaign.cell_size_meters,
    }
    save_session_json(st.session_state.measurements, metadata, campaign.session_json_path)


def _save_settings_and_leave(
    campaign: Campaign,
    pixels_per_meter: float,
    cell_size_meters: float,
    scan_duration: int,
    mac_filter: list[str],
) -> None:
    update_settings(campaign, pixels_per_meter, cell_size_meters, scan_duration, mac_filter)
    st.session_state.active_campaign = None
    st.session_state.raw_floor_plan = None
    st.session_state.stripped_floor_plan = None
    st.session_state.measurements = []
    st.session_state.continuous_running = False
    st.session_state["_bg_cache_key"] = None
    st.session_state["_canvas_bg"] = None
    st.rerun()


def _build_cell_states(measurements: list[Measurement]) -> dict[tuple[int, int], str]:
    """
    Build a cell-state lookup from the current measurements list.

    A cell is "full" if it has both scan results AND a non-zero app_reported_grid.
    Otherwise it is "ble" if it has scan results.
    """
    states: dict[tuple[int, int], str] = {}
    for m in measurements:
        key = (m.true_grid.row, m.true_grid.col)
        has_ble = bool(m.scan_results)
        has_app = m.app_reported_grid != GridCell(0, 0)
        if has_ble and has_app:
            states[key] = "full"
        elif has_ble:
            if states.get(key) != "full":  # Don't downgrade from full.
                states[key] = "ble"
    return states


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if st.session_state.active_campaign is None:
    _show_landing_screen()
else:
    _show_campaign_screen()
