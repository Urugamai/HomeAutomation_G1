import sys
import time
import json
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)

# Import your working local Sigen python library source components
try:
    # This assumes your fixed sigen files or package exist in your python environment paths
    # or inside your local project libraries folder structure
    import sigen

    SIGEN_LIB_AVAILABLE = True
except ImportError:
    SIGEN_LIB_AVAILABLE = False


class SigenPowerAutomationDaemon:
    """
    Background supervisor pulling asset metrics directly from your SigenStor system.
    Normalises solar generation, grid consumption, and battery SOC to update the MQ bus.
    """

    def __init__(self):
        print("[INIT] Launching SigenStor Web Data Ingestion Daemon...")

        # Load credentials and connection parameters from config.ini
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.api_endpoint = self._get_config_str("SIGEN", "api_endpoint", "https://sigenstor.com")
        self.username = self._get_config_str("SIGEN", "username", "")
        self.password = self._get_config_str("SIGEN", "password", "")

        if not SIGEN_LIB_AVAILABLE:
            print("[WARN] Sigen library wrapper not detected globally. Running simulation templates.")

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

    def start(self):
        self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            print(f"[MQTT] Connecting Sigen daemon to broker at {self.broker_ip}...")
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Sigen Daemon failed connecting to broker: {e}")

        # Authenticate your Sigen client session hook if hardware library is available
        if SIGEN_LIB_AVAILABLE:
            try:
                print(f"[SIGEN] Authenticating account token for user: {self.username}...")
                # Update this configuration syntax to precisely match your local fixed library call profile
                self.sigen_client = sigen.Client(endpoint=self.api_endpoint, username=self.username, password=self.password)
                self.sigen_client.login()
                print("[SIGEN SUCCESS] Hardware API token session established.")
            except Exception as e:
                print(f"[SIGEN ERROR] Failed to connect to Sigen portal: {e}")
                sys.exit(1)

        print("[ARMED] Sigen data sync loop active. Refreshing solar stats every 15 seconds.")
        try:
            while True:
                self._fetch_and_publish_sigen_telemetry()
                time.sleep(15.0)  # Query the solar portal every 15 seconds
        except KeyboardInterrupt:
            print("[SHUTDOWN] Halting Sigen energy tracking loops.")
            self.mqtt_client.loop_stop()

    def _fetch_and_publish_sigen_telemetry(self):
        """Fetches raw inverter data, maps values onto a standard payload dictionary, and posts to MQ."""
        if SIGEN_LIB_AVAILABLE and hasattr(self, 'sigen_client'):
            try:
                # Query your working local library functions to pull fresh production attributes
                # Update these exact fields to line up with your fixed dictionary structure:
                realtime_stats = self.sigen_client.get_realtime_data()

                battery_soc = int(realtime_stats.get("battery_soc", 0))
                battery_flow = int(realtime_stats.get("battery_power_watts", 0))  # Positive=Charging, Negative=Discharging
                grid_flow = int(realtime_stats.get("grid_power_watts", 0))  # Positive=Importing, Negative=Exporting
                solar_kwh_today = float(realtime_stats.get("solar_yield_kwh", 0.0))

            except Exception as e:
                print(f"[SIGEN FETCH ERROR] API extraction failed, skipping tick: {e}")
                return
        else:
            # High-fidelity fallback testing values if executing offline on your Windows desktop
            import random
            battery_soc = 82
            battery_flow = random.randint(-1800, 2400)
            grid_flow = random.randint(-1200, 3100)
            solar_kwh_today = 16.4

        # Structure the standardized data packet expected by your UI and Charger daemon
        sigen_payload = {
            "battery_soc": battery_soc,
            "battery_flow": battery_flow,
            "grid_flow": grid_flow,
            "solar_kwh_today": solar_kwh_today
        }

        # Broadcast the payload with retention flagged true so touch panels match instantly on power-on
        json_data = json.dumps(sigen_payload)
        self.mqtt_client.publish("home/power/sigen", json_data, retain=True)
        print(f"[SIGEN REFRESH] Synced metrics to broker: {json_data}")


if __name__ == "__main__":
    daemon = SigenPowerAutomationDaemon()
    daemon.start()
