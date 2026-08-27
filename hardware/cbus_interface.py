import sys
import time
import socket
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Safe, conditional hardware imports that won't crash Windows
try:
    if sys.platform != "win32":
        import serial
    else:
        serial = None
except ImportError:
    serial = None


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
    def connect(self) -> bool:
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        pass
    
    @abstractmethod
    def send_command(self, application: int, group: int, command: str, value: Any) -> bool:
        pass
    
    @abstractmethod
    def receive_message(self) -> Optional[Dict[str, Any]]:
        pass


class SerialCBUSInterface(CBUSInterface):
    """
    Serial interface for CBUS communication via CGate or PCI interface.
    Supports both physical serial connections and USB-to-serial adapters.
    """
    
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 9600, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None
        self.is_windows = (sys.platform == "win32")
        self.connected = False
        
    def connect(self) -> bool:
        """Establish serial connection to CBUS interface."""
        if self.is_windows:
            print("[INFO] Windows detected. Initializing CBUS simulation mode.")
            self.connected = True
            return True
        
        if not serial:
            print("[ERROR] pyserial library not available. Install with: pip install pyserial")
            return False
        
        try:
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            self.serial_connection.reset_input_buffer()
            self.serial_connection.reset_output_buffer()
            self.connected = True
            print(f"[INFO] CBUS serial connection established on {self.port}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to CBUS interface: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Close serial connection."""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            print("[INFO] CBUS serial connection closed")
        self.connected = False
    
    def send_command(self, application: int, group: int, command: str, value: Any) -> bool:
        """
        Send a command to a CBUS device.
        
        Args:
            application: CBUS application ID (e.g., 56 for lighting)
            group: CBUS group address
            command: Command type (e.g., 'ON', 'OFF', 'LEVEL')
            value: Command value (e.g., brightness level 0-255)
        """
        if not self.connected:
            return False
        
        if self.is_windows:
            print(f"[SIMULATION] CBUS Command: App={application}, Group={group}, Cmd={command}, Value={value}")
            return True
        
        try:
            # CBUS SAL (Serial Application Language) packet structure
            # Format: /<application>/<group>/<command>/<value>!
            packet = f"/{application}/{group}/{command}/{value}!\r\n"
            
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.write(packet.encode('ascii'))
                self.serial_connection.flush()
                return True
            return False
        except Exception as e:
            print(f"[ERROR] Failed to send CBUS command: {e}")
            return False
    
    def receive_message(self) -> Optional[Dict[str, Any]]:
        """
        Receive and parse a message from CBUS interface.
        
        Returns:
            Dictionary with parsed message data or None if no message available
        """
        if not self.connected:
            return None
        
        if self.is_windows:
            # Simulate random CBUS messages for testing
            import random
            if random.random() < 0.1:  # 10% chance of message
                return {
                    "application": random.choice([56, 36, 80]),
                    "group": random.randint(1, 255),
                    "command": random.choice(["ON", "OFF", "LEVEL"]),
                    "value": random.randint(0, 255) if random.random() > 0.5 else None,
                    "timestamp": time.time()
                }
            return None
        
        try:
            if self.serial_connection and self.serial_connection.is_open:
                if self.serial_connection.in_waiting > 0:
                    raw_data = self.serial_connection.readline().decode('ascii', errors='ignore').strip()
                    if raw_data:
                        return self._parse_cbus_message(raw_data)
        except Exception as e:
            print(f"[ERROR] Failed to receive CBUS message: {e}")
        
        return None
    
    def _parse_cbus_message(self, raw_message: str) -> Optional[Dict[str, Any]]:
        """Parse raw CBUS SAL message into structured data."""
        try:
            # Parse SAL format: /<application>/<group>/<command>/<value>!
            if raw_message.startswith('/') and raw_message.endswith('!'):
                parts = raw_message[1:-1].split('/')
                if len(parts) >= 3:
                    message = {
                        "application": int(parts[0]),
                        "group": int(parts[1]),
                        "command": parts[2],
                        "value": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                        "timestamp": time.time()
                    }
                    return message
        except Exception as e:
            print(f"[ERROR] Failed to parse CBUS message: {e}")
        
        return None


class NetworkCBUSInterface(CBUSInterface):
    """
    Network interface for CBUS communication via ser2net TCP bridge.
    Connects to a ser2net server that exposes CBUS serial port over TCP.
    """
    
    def __init__(self, host: str = "192.168.2.2", port: int = 2000, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket_connection = None
        self.connected = False
        
    def connect(self) -> bool:
        """Establish TCP connection to ser2net server."""
        try:
            self.socket_connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket_connection.settimeout(self.timeout)
            self.socket_connection.connect((self.host, self.port))
            self.connected = True
            print(f"[INFO] CBUS network connection established to {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to CBUS ser2net server: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> None:
        """Close TCP connection."""
        if self.socket_connection:
            try:
                self.socket_connection.close()
                print("[INFO] CBUS network connection closed")
            except Exception as e:
                print(f"[ERROR] Failed to close CBUS network connection: {e}")
        self.connected = False
    
    def send_command(self, application: int, group: int, command: str, value: Any) -> bool:
        """
        Send a command to a CBUS device via TCP.
        
        Args:
            application: CBUS application ID (e.g., 56 for lighting)
            group: CBUS group address
            command: Command type (e.g., 'ON', 'OFF', 'LEVEL')
            value: Command value (e.g., brightness level 0-255)
        """
        if not self.connected or not self.socket_connection:
            return False
        
        try:
            # CBUS SAL (Serial Application Language) packet structure
            # Format: /<application>/<group>/<command>/<value>!
            packet = f"/{application}/{group}/{command}/{value}!\r\n"
            
            self.socket_connection.sendall(packet.encode('ascii'))
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send CBUS command via TCP: {e}")
            self.connected = False
            return False
    
    def receive_message(self) -> Optional[Dict[str, Any]]:
        """
        Receive and parse a message from CBUS interface via TCP.
        
        Returns:
            Dictionary with parsed message data or None if no message available
        """
        if not self.connected or not self.socket_connection:
            return None
        
        try:
            # Set socket to non-blocking for peek check
            self.socket_connection.setblocking(False)
            try:
                data = self.socket_connection.recv(1024)
                if data:
                    raw_message = data.decode('ascii', errors='ignore').strip()
                    if raw_message:
                        return self._parse_cbus_message(raw_message)
            except BlockingIOError:
                # No data available
                pass
            finally:
                # Restore blocking mode with timeout
                self.socket_connection.setblocking(True)
                self.socket_connection.settimeout(self.timeout)
        except Exception as e:
            print(f"[ERROR] Failed to receive CBUS message via TCP: {e}")
            self.connected = False
        
        return None
    
    def _parse_cbus_message(self, raw_message: str) -> Optional[Dict[str, Any]]:
        """Parse raw CBUS SAL message into structured data."""
        try:
            # Parse SAL format: /<application>/<group>/<command>/<value>!
            if raw_message.startswith('/') and raw_message.endswith('!'):
                parts = raw_message[1:-1].split('/')
                if len(parts) >= 3:
                    message = {
                        "application": int(parts[0]),
                        "group": int(parts[1]),
                        "command": parts[2],
                        "value": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                        "timestamp": time.time()
                    }
                    return message
        except Exception as e:
            print(f"[ERROR] Failed to parse CBUS message: {e}")
        
        return None


class CBUSDeviceManager:
    """
    High-level manager for CBUS device control and monitoring.
    Implements the DataSourceInterface pattern for consistency with the codebase.
    """
    
    def __init__(self, interface: CBUSInterface):
        self.interface = interface
        self.devices: Dict[str, CBUSDevice] = {}
        self.is_windows = (sys.platform == "win32")
        
    def connect(self) -> bool:
        """Initialize CBUS interface connection."""
        return self.interface.connect()
    
    def disconnect(self) -> None:
        """Close CBUS interface connection."""
        self.interface.disconnect()
    
    def register_device(self, name: str, application: int, group: int, device_type: str) -> None:
        """Register a CBUS device for monitoring and control."""
        self.devices[name] = CBUSDevice(
            application=application,
            group=group,
            device_type=device_type,
            last_update=time.time()
        )
        print(f"[INFO] Registered CBUS device: {name} (App={application}, Group={group}, Type={device_type})")
    
    def control_device(self, name: str, command: str, value: Any = None) -> bool:
        """Send a command to a registered CBUS device."""
        if name not in self.devices:
            print(f"[ERROR] Device not registered: {name}")
            return False
        
        device = self.devices[name]
        success = self.interface.send_command(device.application, device.group, command, value)
        
        if success:
            device.current_state = value if value is not None else command
            device.last_update = time.time()
            print(f"[INFO] Device {name} controlled: {command} -> {value}")
        
        return success
    
    def fetch_data(self) -> Dict[str, Any]:
        """
        Fetch current state of all registered devices and any incoming messages.
        Implements DataSourceInterface pattern.
        """
        data = {
            "devices": {},
            "incoming_messages": [],
            "timestamp": time.time()
        }
        
        # Update device states
        for name, device in self.devices.items():
            data["devices"][name] = {
                "application": device.application,
                "group": device.group,
                "type": device.device_type,
                "state": device.current_state,
                "last_update": device.last_update
            }
        
        # Check for incoming messages
        message = self.interface.receive_message()
        if message:
            data["incoming_messages"].append(message)
        
        return data
    
    def process_incoming_messages(self) -> List[Dict[str, Any]]:
        """Process all pending incoming messages from CBUS network."""
        messages = []
        while True:
            message = self.interface.receive_message()
            if not message:
                break
            messages.append(message)
            
            # Update device state if message matches a registered device
            for name, device in self.devices.items():
                if (message["application"] == device.application and 
                    message["group"] == device.group):
                    device.current_state = message.get("value", message["command"])
                    device.last_update = time.time()
        
        return messages
