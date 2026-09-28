"""
Session persistence — saving and loading measurement data.

CSV schema (one row per device per measurement):
    timestamp, true_row, true_col, app_row, app_col,
    mac_address, device_name, rssi_mean, rssi_median, rssi_variance,
    sample_count, tx_power, scan_duration_seconds, notes

JSON schema: full session dump including raw RSSI arrays.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from models import GridCell, Measurement, ScanResult

_CSV_COLUMNS = [
    "timestamp",
    "true_row", "true_col",
    "app_row", "app_col",
    "mac_address", "device_name",
    "rssi_mean", "rssi_median", "rssi_variance",
    "sample_count", "tx_power",
    "adv_data",
    "scan_duration_seconds", "notes",
]

# ---------------------------------------------------------------------------
# Write functions
# ---------------------------------------------------------------------------

def append_measurement_csv(csv_path: Path, measurement: Measurement) -> None:
    """
    Append one measurement to the CSV file, creating it with headers if needed.

    Safe for repeated calls — opens in append mode so existing rows are preserved.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        for row in _measurement_to_rows(measurement):
            writer.writerow(row)


def save_measurements_csv(measurements: list[Measurement], filepath: Path) -> None:
    """Write all measurements to a CSV file (overwrites if exists)."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for m in measurements:
            for row in _measurement_to_rows(m):
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


# ---------------------------------------------------------------------------
# In-memory bytes (for st.download_button)
# ---------------------------------------------------------------------------

def measurements_to_csv_bytes(measurements: list[Measurement]) -> bytes:
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for m in measurements:
        for row in _measurement_to_rows(m):
            writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def measurements_to_json_bytes(
    measurements: list[Measurement],
    metadata: dict[str, Any],
) -> bytes:
    session = {
        "metadata": metadata,
        "exported_at": datetime.now().isoformat(),
        "measurements": [_measurement_to_dict(m) for m in measurements],
    }
    return json.dumps(session, indent=2).encode("utf-8")


# ---------------------------------------------------------------------------
# Load (for resuming a campaign)
# ---------------------------------------------------------------------------

def load_measurements_from_csv(csv_path: Path) -> list[Measurement]:
    """
    Reconstruct Measurement objects from a saved CSV file.

    Raw RSSI arrays are not stored in CSV, so rssi_readings will be empty.
    Statistics (mean, median, variance) are preserved.
    """
    if not csv_path.exists():
        return []

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Group rows that share the same timestamp + true position.
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row.get("timestamp", ""), row.get("true_row", "0"), row.get("true_col", "0"))
        groups.setdefault(key, []).append(row)

    measurements = []
    for rows_group in groups.values():
        first = rows_group[0]
        scan_results = [_row_to_scan_result(r) for r in rows_group if r.get("mac_address")]
        try:
            measurements.append(Measurement(
                timestamp=datetime.fromisoformat(first["timestamp"]),
                true_grid=GridCell(int(first["true_row"]), int(first["true_col"])),
                app_reported_grid=GridCell(
                    int(first.get("app_row") or 0),
                    int(first.get("app_col") or 0),
                ),
                scan_results=[r for r in scan_results if r is not None],
                scan_duration_seconds=float(first.get("scan_duration_seconds") or 3.0),
                notes=first.get("notes", ""),
            ))
        except (ValueError, KeyError):
            pass

    return measurements


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

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
                 "rssi_median": "", "rssi_variance": "", "sample_count": 0, "tx_power": "", "adv_data": ""}]
    return [
        {**base,
         "mac_address": r.mac_address,
         "device_name": r.device_name,
         "rssi_mean": r.rssi_mean,
         "rssi_median": r.rssi_median,
         "rssi_variance": r.rssi_variance,
         "sample_count": r.sample_count,
         "tx_power": r.tx_power if r.tx_power is not None else "",
         "adv_data": json.dumps(r.adv_data) if r.adv_data else ""}
        for r in m.scan_results
    ]


def _measurement_to_dict(m: Measurement) -> dict:
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
                "adv_data": r.adv_data,
                "rssi_readings": r.rssi_readings,
            }
            for r in m.scan_results
        ],
    }


def _row_to_scan_result(row: dict) -> ScanResult | None:
    try:
        adv_data_str = row.get("adv_data", "")
        adv_data = json.loads(adv_data_str) if adv_data_str else {}
        
        return ScanResult(
            mac_address=row["mac_address"],
            device_name=row.get("device_name", "Unknown"),
            rssi_mean=float(row["rssi_mean"]) if row.get("rssi_mean") else 0.0,
            rssi_median=float(row["rssi_median"]) if row.get("rssi_median") else 0.0,
            rssi_variance=float(row["rssi_variance"]) if row.get("rssi_variance") else 0.0,
            sample_count=int(row["sample_count"]) if row.get("sample_count") else 0,
            tx_power=int(row["tx_power"]) if row.get("tx_power") else None,
            adv_data=adv_data,
            rssi_readings=[],
        )
    except (ValueError, KeyError):
        return None
