"""
Campaign management — directory structure, metadata, and lifecycle.

A campaign is a named measurement session tied to a specific floor plan.
Directory layout:
    campaigns/<timestamp>_<name>/
        campaign.json      # name, created_at, and grid/scan settings
        floor_plan.png     # copy of the uploaded floor plan image
        measurements.csv   # appended after every capture (never lost)
        session.json       # full session dump including raw RSSI arrays
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image


CAMPAIGNS_ROOT = Path("campaigns")


@dataclass
class Campaign:
    """A named measurement session with its own directory, settings, and data files."""

    name: str
    directory: Path
    created_at: datetime
    pixels_per_meter: float = 60.0
    cell_size_meters: float = 1.0
    scan_duration: int = 3
    mac_filter: list[str] = field(default_factory=list)

    @property
    def floor_plan_path(self) -> Path:
        return self.directory / "floor_plan.png"

    @property
    def measurements_csv_path(self) -> Path:
        return self.directory / "measurements.csv"

    @property
    def session_json_path(self) -> Path:
        return self.directory / "session.json"

    @property
    def meta_path(self) -> Path:
        return self.directory / "campaign.json"

    @property
    def measurement_count(self) -> int:
        """Number of grid positions captured (CSV rows minus header)."""
        if not self.measurements_csv_path.exists():
            return 0
        with open(self.measurements_csv_path, encoding="utf-8") as f:
            # Count unique timestamps as a proxy for unique measurement events.
            lines = [ln for ln in f if ln.strip()]
        return max(0, len(lines) - 1)  # subtract header row


def create_campaign(name: str) -> Campaign:
    """Create a new campaign directory and write its metadata file."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug = _sanitize_dirname(name)
    directory = CAMPAIGNS_ROOT / f"{timestamp}_{slug}"
    directory.mkdir(parents=True, exist_ok=True)

    campaign = Campaign(
        name=name,
        directory=directory,
        created_at=datetime.now(),
    )
    _write_meta(campaign)
    return campaign


def save_floor_plan(campaign: Campaign, image: Image.Image) -> None:
    """Save the floor plan image into the campaign directory as PNG."""
    image.save(str(campaign.floor_plan_path), format="PNG")


def update_settings(
    campaign: Campaign,
    pixels_per_meter: float,
    cell_size_meters: float,
    scan_duration: int,
    mac_filter: list[str],
) -> Campaign:
    """Return a campaign with updated settings and persist them to disk."""
    updated = Campaign(
        name=campaign.name,
        directory=campaign.directory,
        created_at=campaign.created_at,
        pixels_per_meter=pixels_per_meter,
        cell_size_meters=cell_size_meters,
        scan_duration=scan_duration,
        mac_filter=list(mac_filter),
    )
    _write_meta(updated)
    return updated


def list_campaigns() -> list[Campaign]:
    """Return all valid campaigns in the campaigns root, newest first."""
    if not CAMPAIGNS_ROOT.exists():
        return []
    campaigns = []
    for path in sorted(CAMPAIGNS_ROOT.iterdir(), reverse=True):
        if path.is_dir() and (path / "campaign.json").exists():
            try:
                campaigns.append(_load_from_dir(path))
            except (KeyError, ValueError, json.JSONDecodeError):
                pass  # Corrupt or incomplete — skip silently.
    return campaigns


def load_campaign_from_dir(directory: Path) -> Campaign:
    return _load_from_dir(directory)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _write_meta(campaign: Campaign) -> None:
    meta = {
        "name": campaign.name,
        "created_at": campaign.created_at.isoformat(),
        "pixels_per_meter": campaign.pixels_per_meter,
        "cell_size_meters": campaign.cell_size_meters,
        "scan_duration": campaign.scan_duration,
        "mac_filter": campaign.mac_filter,
    }
    campaign.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _load_from_dir(directory: Path) -> Campaign:
    meta = json.loads((directory / "campaign.json").read_text(encoding="utf-8"))
    return Campaign(
        name=meta["name"],
        directory=directory,
        created_at=datetime.fromisoformat(meta["created_at"]),
        pixels_per_meter=float(meta.get("pixels_per_meter", 60.0)),
        cell_size_meters=float(meta.get("cell_size_meters", 1.0)),
        scan_duration=int(meta.get("scan_duration", 3)),
        mac_filter=meta.get("mac_filter", []),
    )


def _sanitize_dirname(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.strip())
    slug = re.sub(r"[\s\-]+", "_", slug)
    return slug[:40] or "campaign"
