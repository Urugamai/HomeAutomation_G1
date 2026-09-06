import sys
import time
import json
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)

from libraries.paho_compat import create_client


class BlindAutomationDaemon:
    """
    Headless background supervisor managing window shade positioning.
    Balances automated HVAC insulation logic with real-time outdoor brightness metrics.
    """

    def __init__(self):
        print("[INIT] Launching Autonomous Blind Controller Daemon...")
        self.broker_ip = self._load_broker_config()
        self.current_blind_position = "OPEN"  # Tracks position: OPEN or CLOSED
        self.last_action_time = time.time()

        # Brightness thresholds (lux)
        self.LUX_SUNNY_THRESHOLD = 35000.0  # Close to block radiant heat load
        self.LUX_DARK_THRESHOLD = 500.0  # Close at dusk for insulation privacy

    def _load_broker_config(self) -> str:
        config_path = Path(__file__).resolve().parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get("MQTT", "broker", fallback="localhost")
            except Exception:
                pass
        return "localhost"

    def start(self):
        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        try:
            self.client.connect(self.broker_ip, 1883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Blind Daemon broker handshake failed: {e}")

        print("[RUNNING] Blind monitoring loop armed. Listening for environment changes.")
        try:
            while True:
                time.sleep(1.0)  # Keep service alive while MQTT callbacks process payloads
        except KeyboardInterrupt:
            print("[SHUTDOWN] Terminating Blind Automation Daemon.")
            self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        print(f"[MQTT] Blind Daemon bound to broker ({self.broker_ip}).")
        # Listen for both physical weather station updates and climate commands
        self.client.subscribe("home/blinds/command")
        self.client.subscribe("home/environment/ecowitt")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))

            # Scenario A: Handle direct commands sent by the HVAC Engine
            if msg.topic == "home/blinds/command":
                action = payload.get("action")
                reason = payload.get("reason", "UNKNOWN")
                if action in ["OPEN", "CLOSE"]:
                    print(f"[COMMAND] HVAC core requested blind state: {action} (Reason: {reason})")
                    self._execute_blind_movement(action)

            # Scenario B: Handle light reading updates from the Ecowitt station
            elif msg.topic == "home/environment/ecowitt":
                # Ensure we don't override an HVAC command if it occurred very recently (5-minute buffer)
                if time.time() - self.last_action_time < 300:
                    return

                outside_light = float(payload.get("light_lux", 10000.0))
                outside_temp = float(payload.get("temperature", 20.0))

                # Automated environmental protection rules
                if outside_light > self.LUX_SUNNY_THRESHOLD and outside_temp > 25.0:
                    # It's hot and sunny outside; shut blinds to block incoming thermal load
                    self._execute_blind_movement("CLOSE")
                elif outside_light < self.LUX_DARK_THRESHOLD:
                    # It's getting dark; drop blinds for night insulation
                    self._execute_blind_movement("CLOSE")
                elif self.LUX_DARK_THRESHOLD <= outside_light <= self.LUX_SUNNY_THRESHOLD:
                    # Ambient clear day conditions; open up for natural light routing
                    self._execute_blind_movement("OPEN")

        except Exception as e:
            print(f"[PARSE EXCEPTION] Blind Daemon failed to evaluate message: {e}")

    def _execute_blind_movement(self, target_position: str):
        """Dispatches outbound command string to C-Bus controller interfaces."""
        if self.current_blind_position == target_position:
            return  # Avoid sending duplicate commands over the bus lines

        print(f"[HARDWARE OUTPUT] Transmitting C-Bus command packet: Set Blinds -> {target_position}")

        # Format standard structure expected by your CBus Controller driver block
        cbus_payload = {
            "network": 254,
            "application": 88,  # Typical lighting/shutter control block address
            "group": 12,  # Shutter Group address link
            "action": "ON" if target_position == "CLOSE" else "OFF"
        }

        self.client.publish("home/cbus/command", json.dumps(cbus_payload))
        self.current_blind_position = target_position
        self.last_action_time = time.time()


if __name__ == "__main__":
    daemon = BlindAutomationDaemon()
    daemon.start()
