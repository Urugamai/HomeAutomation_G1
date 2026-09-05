import sys
import time
import socket
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Import our new protocol parser engine
from hardware.cbus_protocol import CBusProtocolEngine


@dataclass
class CBUSDevice:
    """Represents a CBUS device with its addressing and state."""
    application: int
    group: int
    device_type: str
    current_state: Any = None
    last_update: float = 0.0


class CBUSInterface(ABC):
    """Abstract base class for CBUS communication interfaces."""

    @abstractmethod
    def connect(self) -> bool: pass

    @abstractmethod
    def disconnect(self) -> None: pass

    @abstractmethod
    def send_command(self, application: int, group: int, command: str, value: Any) -> bool: pass

    @abstractmethod
    def receive_message(self) -> Optional[Any]: pass


class NetworkCBUSInterface(CBUSInterface):
    """Network interface for CBUS communication via ser2net TCP bridge."""

    def __init__(self, host: str = "192.168.2.2", port: int = 2000, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket_connection = None
        self.connected = False
        self.prefix_index = 2
        self.prefixes = ["\\", "/", "<"]

    def connect(self) -> bool:
        """Connects and transmits the required 5500PC Smart Interface Mode handshakes."""
        try:
            self.socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_connection.settimeout(self.timeout)
            self.socket_connection.connect((self.host, self.port))
            self.connected = True
            print(f"[INFO] Connected to C-Bus 5500PC Text-Hex Gateway at {self.host}:{self.port}")

            print("[PCI HANDSHAKE] Activating Smart Interface firmware modes...")
            self.socket_connection.sendall(b"~~~\r\n")
            time.sleep(0.15)
            self.socket_connection.sendall(b"A30001\r\n")  # Force Connect Mode ON
            time.sleep(0.15)
            self.socket_connection.sendall(b"A30301\r\n")  # Force Monitor Mode ON
            time.sleep(0.15)

            try:
                self.socket_connection.setblocking(False)
                self.socket_connection.recv(2048)
            except Exception:
                pass
            self.socket_connection.setblocking(True)
            return True
        except Exception as e:
            print(f"[ERROR] Failed connecting to 5500PC interface: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        self.connected = False
        if self.socket_connection:
            try:
                self.socket_connection.close()
            except Exception:
                pass

    def send_command(self, application: int, group: int, command: str, value: Any) -> bool:
        if not self.connected or not self.socket_connection: return False
        try:
            cmd_hex = "01" if command == "OFF" else "79"
            if command not in ["ON", "OFF"]:
                cmd_hex = f"{int(value):02X}" if value is not None else "FF"

            base_payload = f"0500{application:02X}00{cmd_hex}{group:02X}"
            lrc_checksum = CBusProtocolEngine.calculate_lrc(base_payload)
            packet = f"\\{base_payload}{lrc_checksum}\r\n"
            self.socket_connection.sendall(packet.encode('ascii'))
            return True
        except Exception as e:
            print(f"[ERROR] Failed sending ASCII hex command frame: {e}")
            return False

    def send_query(self, application: int, group: int) -> bool:
        if not self.connected or not self.socket_connection: return False
        try:
            base_payload = f"0500{application:02X}0001{group:02X}"
            lrc_checksum = CBusProtocolEngine.calculate_lrc(base_payload)
            packet = f"\\{base_payload}{lrc_checksum}\r\n"
            self.socket_connection.sendall(packet.encode('ascii'))
            return True
        except Exception: return False

    def send_bulk_sync(self, application: int) -> bool:
        if not self.connected or not self.socket_connection: return False
        try:
            base_payload = f"0500{application:02X}000100"
            lrc_checksum = CBusProtocolEngine.calculate_lrc(base_payload)
            packet = f"\\{base_payload}{lrc_checksum}\r\n"
            print(f"[PCI BULK SYNC SEND] Requesting network snapshot: {repr(packet)}")
            self.socket_connection.sendall(packet.encode('ascii'))
            return True
        except Exception: return False

    def receive_message(self) -> Optional[List[Dict[str, Any]]]:
        if not self.connected or not self.socket_connection: return None
        try:
            self.socket_connection.setblocking(False)
            try:
                data = self.socket_connection.recv(4096)
                if data:
                    raw_stream = data.decode('ascii', errors='ignore')
                    return CBusProtocolEngine.parse_text_stream(raw_stream, self.prefixes)
            except BlockingIOError:
                pass
            finally:
                self.socket_connection.setblocking(True)
                self.socket_connection.settimeout(self.timeout)
        except Exception:
            self.connected = False
        return None


class CBUSDeviceManager:
    """High-level manager for CBUS device control and monitoring."""

    def __init__(self, interface: CBUSInterface):
        self.interface = interface
        self.devices: Dict[str, CBUSDevice] = {}
        self.is_windows = False

    def connect(self) -> bool:
        return self.interface.connect()

    def disconnect(self) -> None:
        self.interface.disconnect()

    def register_device(self, name: str, application: int, group: int, device_type: str) -> None:
        self.devices[name] = CBUSDevice(application=application, group=group, device_type=device_type, last_update=time.time())

    def control_device(self, name: str, command: str, value: Any = None) -> bool:
        if name not in self.devices: return False
        device = self.devices[name]
        success = self.interface.send_command(device.application, device.group, command, value)
        if success:
            device.current_state = value if value is not None else command
            device.last_update = time.time()
        return success

    def query_device_status(self, name: str) -> bool:
        if name not in self.devices: return False
        device = self.devices[name]
        if hasattr(self.interface, 'send_query'):
            return self.interface.send_query(device.application, device.group)
        return False

    def process_incoming_messages(self) -> List[Dict[str, Any]]:
        messages = []
        while True:
            message = self.interface.receive_message()
            if not message:
                break
            if isinstance(message, list):
                for single_msg in message:
                    messages.append(single_msg)
                    self._update_device_state(single_msg)
            else:
                messages.append(message)
                self._update_device_state(message)
        return messages

    def _update_device_state(self, message: Dict[str, Any]) -> None:
        for name, device in self.devices.items():
            if (message["application"] == device.application and message["group"] == device.group):
                if message["command"] == "ON":
                    device.current_state = 100
                elif message["command"] == "OFF":
                    device.current_state = 0
                else:
                    device.current_state = message.get("value", message["command"])
                device.last_update = time.time()

    def request_network_sync(self, application: int) -> bool:
        if hasattr(self.interface, 'send_bulk_sync'):
            return self.interface.send_bulk_sync(application)
        return False
