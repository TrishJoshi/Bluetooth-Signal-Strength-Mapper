"""
Phone sensor TCP client stub.

Architecture:
- The phone runs a TCP server on port 5000 (a native Android BLE bridge app or a
  mock Termux script).
- `adb forward tcp:5000 tcp:5000` tunnels that port to the laptop's localhost.
- PhoneSensorClient connects to localhost:5000 and reads newline-delimited JSON packets.

Protocol:
    Each line is a JSON object with at minimum:
    {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "device_name": "Unknown",
        "rssi": -72,
        "timestamp": 1727071000.123
    }
    Optional fields: "tx_power", "manufacturer_data_hex".

PhoneSensorClient is intentionally simple: it reads packets into a thread-safe queue
that the Streamlit app can drain on demand. MockPhoneSensorServer exists for local
testing without a physical phone.
"""

from __future__ import annotations

import json
import queue
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional


_MOCK_DEVICES = [
    {"mac_address": "E2:C5:6D:B5:43:21", "device_name": "Steerpath Beacon A"},
    {"mac_address": "E2:C5:6D:B5:43:22", "device_name": "Steerpath Beacon B"},
    {"mac_address": "E2:C5:6D:B5:43:23", "device_name": "Steerpath Beacon C"},
    {"mac_address": "D0:23:56:A1:B2:C3", "device_name": "Polar H10"},
    {"mac_address": "AA:BB:CC:DD:EE:FF", "device_name": "Unknown"},
]


@dataclass
class PhonePacket:
    """One BLE advertisement packet received from the phone."""
    mac_address: str
    device_name: str
    rssi: int
    timestamp: float
    tx_power: Optional[int] = None
    manufacturer_data_hex: Optional[str] = None


class PhoneSensorClient:
    """
    TCP client that receives BLE data from the phone via ADB port forwarding.

    Usage:
        client = PhoneSensorClient()
        if client.connect():
            packet = client.read_packet(timeout=1.0)
        client.disconnect()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 5000) -> None:
        self._host = host
        self._port = port
        self._socket: Optional[socket.socket] = None
        self._packet_queue: queue.Queue[PhonePacket] = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def connect(self) -> bool:
        """
        Attempt to connect to the phone's TCP server.

        Returns True on success, False if the connection was refused
        (phone not connected, ADB forward not set up, server not running).
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(3.0)
            self._socket.connect((self._host, self._port))
            self._socket.settimeout(None)
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True
            )
            self._reader_thread.start()
            return True
        except (ConnectionRefusedError, OSError):
            self._socket = None
            return False

    def read_packet(self, timeout: float = 0.1) -> Optional[PhonePacket]:
        """Return the next queued packet, or None if none arrived within `timeout`."""
        try:
            return self._packet_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_packets(self) -> list[PhonePacket]:
        """Return all currently queued packets without blocking."""
        packets = []
        while not self._packet_queue.empty():
            try:
                packets.append(self._packet_queue.get_nowait())
            except queue.Empty:
                break
        return packets

    def disconnect(self) -> None:
        """Stop the reader thread and close the socket."""
        self._stop_event.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        """Background thread: read newline-delimited JSON from the socket."""
        buffer = ""
        while not self._stop_event.is_set() and self._socket:
            try:
                chunk = self._socket.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    break
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    packet = _parse_packet(line.strip())
                    if packet:
                        self._packet_queue.put(packet)
            except OSError:
                break


class MockPhoneSensorServer:
    """
    Local mock server for testing without a physical phone.

    Streams fake BLE advertisement data on localhost:5000 at ~2 Hz.
    Run in a background thread before connecting PhoneSensorClient.

    Usage:
        server = MockPhoneSensorServer()
        server.start()
        # ... run your app ...
        server.stop()
    """

    def __init__(self, port: int = 5000, stream_hz: float = 2.0) -> None:
        self._port = port
        self._interval = 1.0 / stream_hz
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the mock server in a daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _serve(self) -> None:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", self._port))
        server_socket.listen(1)
        server_socket.settimeout(1.0)

        while not self._stop_event.is_set():
            try:
                client_socket, _ = server_socket.accept()
                self._stream_to(client_socket)
            except socket.timeout:
                continue

        server_socket.close()

    def _stream_to(self, client_socket: socket.socket) -> None:
        try:
            while not self._stop_event.is_set():
                packet = _generate_mock_packet()
                message = json.dumps(packet) + "\n"
                client_socket.sendall(message.encode("utf-8"))
                time.sleep(self._interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            client_socket.close()


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _parse_packet(line: str) -> Optional[PhonePacket]:
    """Parse one JSON line into a PhonePacket; return None on parse errors."""
    if not line:
        return None
    try:
        data = json.loads(line)
        return PhonePacket(
            mac_address=data["mac_address"],
            device_name=data.get("device_name", "Unknown"),
            rssi=int(data["rssi"]),
            timestamp=float(data.get("timestamp", time.time())),
            tx_power=data.get("tx_power"),
            manufacturer_data_hex=data.get("manufacturer_data_hex"),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _generate_mock_packet() -> dict:
    """Generate a realistic-looking fake BLE advertisement packet."""
    device = random.choice(_MOCK_DEVICES)
    return {
        "mac_address": device["mac_address"],
        "device_name": device["device_name"],
        "rssi": random.randint(-90, -40),
        "tx_power": -59,
        "timestamp": time.time(),
    }
