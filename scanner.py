"""
Async BLE scanner using the bleak library.

Design:
- Uses BleakScanner with a detection_callback to capture every advertisement
  packet in real-time, accumulating RSSI readings per device over the scan window.
  This bypasses OS-level RSSI caching which only reports a single value per device.
- After the window closes, computes mean/median/variance per device.
- mac_filter accepts a list of MAC address prefixes (e.g. "AA:BB") or full
  addresses. Pass None or empty list to capture all visible devices.

Requires: bleak>=0.22, Linux with BlueZ and a BLE adapter.
"""

from __future__ import annotations

import asyncio
import statistics
from collections import defaultdict
from typing import Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from models import ScanResult


async def scan_ble_devices(
    duration_seconds: float,
    mac_filter: Optional[list[str]] = None,
) -> list[ScanResult]:
    """
    Run a BLE scan for `duration_seconds` and return per-device RSSI statistics.

    Args:
        duration_seconds: How long to keep the scanner active (3–5 s recommended).
        mac_filter: Optional list of MAC address prefixes or full addresses to
                    include. Case-insensitive. Pass None to include all devices.

    Returns:
        A list of ScanResult objects, sorted by mean RSSI descending (strongest first).
    """
    rssi_accumulator: dict[str, list[int]] = defaultdict(list)
    adv_accumulator: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    device_names: dict[str, str] = {}
    tx_powers: dict[str, Optional[int]] = {}

    normalised_filter = _normalise_filter(mac_filter)

    def on_advertisement(device: BLEDevice, advertisement: AdvertisementData) -> None:
        mac = device.address.upper()
        if normalised_filter and not _matches_filter(mac, normalised_filter):
            return
        rssi_accumulator[mac].append(advertisement.rssi)
        
        # Check for Eddystone service UUID (0xFEAA)
        is_eddystone = (
            "0000feaa-0000-1000-8000-00805f9b34fb" in advertisement.service_data or
            "0000feaa-0000-1000-8000-00805f9b34fb" in advertisement.service_uuids
        )
        
        # Prefer the device name from the current packet, or fall back to previously seen / "Unknown"
        if device.name:
            device_names[mac] = device.name
        elif is_eddystone and device_names.get(mac, "Unknown") == "Unknown":
            device_names[mac] = "Eddystone™"
        elif mac not in device_names:
            device_names[mac] = "Unknown"
            
        if advertisement.tx_power is not None:
            tx_powers[mac] = advertisement.tx_power
            
        # Accumulate raw manufacturer and service data payloads (as hex strings)
        for cid, data in advertisement.manufacturer_data.items():
            adv_accumulator[mac][f"Mfg:0x{cid:04x}"].add(data.hex())
        for uuid, data in advertisement.service_data.items():
            adv_accumulator[mac][f"Srv:{uuid}"].add(data.hex())

    # Use active scanning to proactively request local names from devices
    scanner = BleakScanner(detection_callback=on_advertisement, scanning_mode="active")

    await scanner.start()
    await asyncio.sleep(duration_seconds)
    await scanner.stop()

    return _build_results(rssi_accumulator, device_names, tx_powers, adv_accumulator)


def _build_results(
    rssi_accumulator: dict[str, list[int]],
    device_names: dict[str, str],
    tx_powers: dict[str, Optional[int]],
    adv_accumulator: dict[str, dict[str, set[str]]],
) -> list[ScanResult]:
    """Convert raw RSSI accumulator data into sorted ScanResult objects."""
    results = []
    for mac, readings in rssi_accumulator.items():
        mean_rssi = statistics.mean(readings)
        median_rssi = statistics.median(readings)
        variance_rssi = statistics.variance(readings) if len(readings) > 1 else 0.0

        # Flatten sets of hex strings into comma-separated strings for CSV/display
        formatted_adv_data = {
            k: ",".join(sorted(v)) for k, v in adv_accumulator[mac].items()
        }

        results.append(
            ScanResult(
                mac_address=mac,
                device_name=device_names[mac],
                rssi_mean=round(mean_rssi, 2),
                rssi_median=float(median_rssi),
                rssi_variance=round(variance_rssi, 2),
                sample_count=len(readings),
                tx_power=tx_powers.get(mac),
                adv_data=formatted_adv_data,
                rssi_readings=readings,
            )
        )

    return sorted(results, key=lambda r: r.rssi_mean, reverse=True)


def _normalise_filter(mac_filter: Optional[list[str]]) -> list[str]:
    """Return an uppercase, stripped list of filter strings, or empty list."""
    if not mac_filter:
        return []
    return [entry.strip().upper() for entry in mac_filter if entry.strip()]


def _matches_filter(mac: str, normalised_filter: list[str]) -> bool:
    """Return True if mac starts with any of the filter prefixes."""
    return any(mac.startswith(prefix) for prefix in normalised_filter)
