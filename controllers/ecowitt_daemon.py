import sys
import socket
import json
import time
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)


class EcowittLanIngestionDaemon:
    """
    Headless background supervisor pulling real-time outdoor AND indoor metrics
    from a local Ecowitt GW2000 gateway device using low-latency LAN socket queries.
    Routes indoor details explicitly to a unique Rumpus Room topic path.
    """

    def __init__(self):
        print("[INIT] Launching Local Ecowitt Gateway LAN Daemon...")

        # Load centralized configuration parameters
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.gateway_ip = self._get_config_str("ECOWITT", "gateway_ip", "192.168.2.10")
        self.gateway_port = int(self._get_config_str("ECOWITT", "gateway_port", "45000"))

        self.mqtt_client = None

    def _get_config_str(self, section, key, fallback) -> str:
        config_path = Path(__file__).resolve().parent.parent / "config.ini"
        if config_path.exists():
            try:
                config = configparser.ConfigParser()
                config.read(str(config_path))
                return config.get(section, key, fallback=fallback)
            except Exception:
                pass
        return fallback

    def init_mqtt(self):
        self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            print(f"[MQTT] Connecting Ecowitt daemon to broker at {self.broker_ip}...")
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Ecowitt Daemon failed connecting to broker: {e}")
            sys.exit(1)

    def start_polling_loop(self):
        print(f"[ARMED] Querying Ecowitt station at {self.gateway_ip}:{self.gateway_port} every 10 seconds.")
        lan_command = bytes([0xBB, 0x00, 0x06, 0x03, 0x04, 0x3D])

        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(4.0)
                sock.connect((self.gateway_ip, self.gateway_port))

                sock.sendall(lan_command)
                response_bytes = sock.recv(1024)
                sock.close()

                if response_bytes:
                    self._parse_and_publish_payload(response_bytes)
                else:
                    print("[WARN] Received an empty byte array frame from Ecowitt gateway.")

            except Exception as e:
                # Windows Desktop Testing Fallback Simulation Mode
                if sys.platform == "win32":
                    self._generate_simulated_dual_telemetry()
                else:
                    print(f"[GATEWAY ERROR] Failed to fetch data from hardware link: {e}")

            time.sleep(10.0)

    def _parse_and_publish_payload(self, raw_bytes):
        """Decodes incoming byte arrays into high-resolution metrics."""
        try:
            # 1. Decode Outdoor Array Offsets
            out_temp_raw = (raw_bytes[14] << 8) | raw_bytes[15] if len(raw_bytes) > 16 else 0xFFFF
            out_temp_c = round((out_temp_raw - 400) / 10.0, 1) if out_temp_raw != 0xFFFF else 14.5

            out_humidity = int(raw_bytes[16]) if len(raw_bytes) > 17 and raw_bytes[16] != 0xFF else 65
            wind_speed_ms = ((raw_bytes[19] << 8) | raw_bytes[20]) / 10.0 if len(raw_bytes) > 20 else 0.0
            wind_speed_kmh = round(wind_speed_ms * 3.6, 1)

            # 2. Decode GW2000 Indoor Sensor Subtree Blocks (Physical Gateway is in the Rumpus Room)
            in_temp_raw = (raw_bytes[7] << 8) | raw_bytes[8] if len(raw_bytes) > 9 else 0xFFFF
            in_temp_c = round((in_temp_raw - 400) / 10.0, 1) if in_temp_raw != 0xFFFF else 21.5

            in_humidity = int(raw_bytes[9]) if len(raw_bytes) > 10 and raw_bytes[9] != 0xFF else 45

            pressure_raw = (raw_bytes[11] << 8) | raw_bytes[12] if len(raw_bytes) > 13 else 0xFFFF
            pressure_hpa = round(pressure_raw / 10.0, 1) if pressure_raw != 0xFFFF else 1013.2

            outdoor_payload = {
                "temperature": out_temp_c,
                "humidity": out_humidity,
                "wind_speed": wind_speed_kmh,
                "timestamp": time.time()
            }

            # Annotated unique payload structure representing the Rumpus Room location bounds
            rumpus_payload = {
                "room_name": "Rumpus Room",
                "temperature": in_temp_c,
                "humidity": in_humidity,
                "pressure": pressure_hpa,
                "timestamp": time.time()
            }

            self._publish_payloads(rumpus_payload, outdoor_payload)

        except Exception as e:
            print(f"[DECODE ERROR] Failed to segment byte map array fields: {e}")

    def _generate_simulated_dual_telemetry(self):
        """Generates realistic changing indoor and outdoor trends for local PC testing."""
        import random
        outdoor_payload = {
            "temperature": round(14.5 + random.uniform(-0.1, 0.1), 1),
            "humidity": random.randint(62, 70),
            "wind_speed": round(16.5 + random.uniform(-1.0, 2.0), 1),
            "timestamp": time.time()
        }

        rumpus_payload = {
            "room_name": "Rumpus Room",
            "temperature": round(21.8 + random.uniform(-0.05, 0.05), 1),
            "humidity": random.randint(45, 50),
            "pressure": round(1014.5 + random.uniform(-0.2, 0.2), 1),
            "timestamp": time.time()
        }
        self._publish_payloads(rumpus_payload, outdoor_payload)

    def _publish_payloads(self, rumpus_dict, outdoor_dict):
        # 1. Standard outdoor metrics
        self.mqtt_client.publish("home/environment/ecowitt", json.dumps(outdoor_dict), retain=True)

        # 2. FIXED: Publish to a unique, dedicated room sub-topic path to allow scale expansions
        self.mqtt_client.publish("home/environment/rumpus", json.dumps(rumpus_dict), retain=True)
        print(f"[ECOWITT SYNC] Dispatched outdoor and unique Rumpus Room telemetry parameters.")


if __name__ == "__main__":
    daemon = EcowittLanIngestionDaemon()
    daemon.init_mqtt()
    try:
        daemon.start_polling_loop()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Halting Ecowitt weather ingestion loops safely.")
        if daemon.mqtt_client:
            daemon.mqtt_client.loop_stop()
