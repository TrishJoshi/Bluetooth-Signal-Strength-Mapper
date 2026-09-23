"""
Session persistence: save and export measurement data.

Responsibilities:
- Flatten Measurement objects to CSV rows for analysis in pandas/Excel.
- Dump the full session (including raw RSSI arrays) to JSON.
- Load a previous JSON session back into objects.

CSV schema (one row per device per measurement):
    timestamp, true_row, true_col, app_row, app_col,
    mac_address, device_name, rssi_mean, rssi_median, rssi_variance,
    sample_count, tx_power, scan_duration_seconds, notes
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from models import GridCell, Measurement, ScanResult


def save_measurements_csv(measurements: list[Measurement], filepath: Path) -> None:
    """Write all measurements to a flat CSV file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for measurement in measurements:
            for row in _measurement_to_rows(measurement):
                writer.writerow(row)


def save_session_json(
    measurements: list[Measurement],
    metadata: dict[str, Any],
    filepath: Path,
) -> None:
    """Write the full session including raw RSSI arrays to JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    session = {
        "metadata": metadata,
        "exported_at": datetime.now().isoformat(),
        "measurements": [_measurement_to_dict(m) for m in measurements],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2)


def measurements_to_csv_bytes(measurements: list[Measurement]) -> bytes:
    """Return CSV content as bytes (for st.download_button)."""
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for measurement in measurements:
        for row in _measurement_to_rows(measurement):
            writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def measurements_to_json_bytes(
    measurements: list[Measurement],
    metadata: dict[str, Any],
) -> bytes:
    """Return JSON session content as bytes (for st.download_button)."""
    session = {
        "metadata": metadata,
        "exported_at": datetime.now().isoformat(),
        "measurements": [_measurement_to_dict(m) for m in measurements],
    }
    return json.dumps(session, indent=2).encode("utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "timestamp",
    "true_row", "true_col",
    "app_row", "app_col",
    "mac_address", "device_name",
    "rssi_mean", "rssi_median", "rssi_variance",
    "sample_count", "tx_power",
    "scan_duration_seconds", "notes",
]


def _measurement_to_rows(m: Measurement) -> list[dict]:
    """Expand one Measurement into one CSV row per discovered device."""
    base = {
        "timestamp": m.timestamp.isoformat(),
        "true_row": m.true_grid.row,
        "true_col": m.true_grid.col,
        "app_row": m.app_reported_grid.row,
        "app_col": m.app_reported_grid.col,
        "scan_duration_seconds": m.scan_duration_seconds,
        "notes": m.notes,
    }
    if not m.scan_results:
        return [{**base, "mac_address": "", "device_name": "", "rssi_mean": "",
                 "rssi_median": "", "rssi_variance": "", "sample_count": 0,
                 "tx_power": ""}]
    rows = []
    for r in m.scan_results:
        rows.append({
            **base,
            "mac_address": r.mac_address,
            "device_name": r.device_name,
            "rssi_mean": r.rssi_mean,
            "rssi_median": r.rssi_median,
            "rssi_variance": r.rssi_variance,
            "sample_count": r.sample_count,
            "tx_power": r.tx_power if r.tx_power is not None else "",
        })
    return rows


def _measurement_to_dict(m: Measurement) -> dict:
    """Serialise a Measurement to a JSON-compatible dict."""
    return {
        "timestamp": m.timestamp.isoformat(),
        "true_grid": {"row": m.true_grid.row, "col": m.true_grid.col},
        "app_reported_grid": {"row": m.app_reported_grid.row, "col": m.app_reported_grid.col},
        "scan_duration_seconds": m.scan_duration_seconds,
        "notes": m.notes,
        "scan_results": [
            {
                "mac_address": r.mac_address,
                "device_name": r.device_name,
                "rssi_mean": r.rssi_mean,
                "rssi_median": r.rssi_median,
                "rssi_variance": r.rssi_variance,
                "sample_count": r.sample_count,
                "tx_power": r.tx_power,
                "rssi_readings": r.rssi_readings,
            }
            for r in m.scan_results
        ],
    }
