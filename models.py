"""
Data models for the BLE measurement campaign.

Each class has a single, clear responsibility:
- GridCell: identifies a position on the floor plan grid.
- ScanResult: holds one device's RSSI statistics from a single scan window.
- Measurement: a complete snapshot — ground truth position, app-reported position,
  and all discovered devices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class GridCell:
    """A (row, col) position on the measurement grid, zero-indexed."""
    row: int
    col: int

    def __str__(self) -> str:
        return f"({self.row}, {self.col})"

    def moved(self, direction: str) -> "GridCell":
        """Return a new GridCell shifted one step in the given cardinal direction."""
        offsets = {"N": (-1, 0), "S": (1, 0), "W": (0, -1), "E": (0, 1)}
        dr, dc = offsets[direction]
        return GridCell(self.row + dr, self.col + dc)

    def is_valid(self, max_rows: int, max_cols: int) -> bool:
        """Return True if this cell is within the grid bounds."""
        return 0 <= self.row < max_rows and 0 <= self.col < max_cols


@dataclass
class ScanResult:
    """RSSI statistics for a single Bluetooth device discovered during a scan window."""
    mac_address: str
    device_name: str
    rssi_mean: float
    rssi_median: float
    rssi_variance: float
    sample_count: int
    tx_power: Optional[int] = None
    # Raw readings stored for later analysis; not exported to CSV.
    rssi_readings: list[int] = field(default_factory=list)


@dataclass
class Measurement:
    """A complete captured snapshot at one grid position."""
    timestamp: datetime
    true_grid: GridCell
    app_reported_grid: GridCell
    scan_results: list[ScanResult]
    scan_duration_seconds: float
    notes: str = ""
