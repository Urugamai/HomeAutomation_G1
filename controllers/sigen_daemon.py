import sys
import time as pytime
import json
import asyncio
from pathlib import Path
import configparser

# Safe import configuration for your custom package folder placement
try:
    from libraries.sigen_library import Sigen

    SIGEN_LIB_AVAILABLE = True
except ImportError:
    # Fallback to local root search rules if libraries namespace package isn't linked
    try:
        from sigen_library import Sigen

        SIGEN_LIB_AVAILABLE = True
    except ImportError:
        SIGEN_LIB_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)


class SigenPowerAutomationDaemon:
    """
    Headless asyncio background supervisor interacting with your custom Sigen library.
    Normalises asynchronous solar statistics and updates the centralized home MQ endpoints.
    """

    def __init__(self):
        print("[INIT] Launching SigenStor Inverter Data Ingestion Daemon...")

        # Load centralized configuration variables
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.username = self._get_config_str("SIGEN", "username", "Junkmail_MWW@Internode.on.net")
        self.password = self._get_config_str("SIGEN", "password", "b$JJPX6!Lg8*cmr")
        self.region = self._get_config_str("SIGEN", "region", "au")

        self.sigstore = None
        self.mqtt_client = None

        if not SIGEN_LIB_AVAILABLE:
            print("[CRITICAL] 'sigen_library' folder was not found inside your libraries package path.")
            print("Please ensure libraries/sigen_library/__init__.py exists.")
            sys.exit(1)

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
        """Initializes standard Paho connections synchronous link targets."""
        self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        try:
            print(f"[MQTT] Connecting Sigen data loop to broker at {self.broker_ip}...")
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Sigen Daemon failed connecting to broker: {e}")
            sys.exit(1)

    async def run_async_loop(self):
        """Orchestrates asynchronous initializations and periodic query schedules."""
        # 1. Instantiate your custom api connection framework
        self.sigstore = Sigen(username=self.username, password=self.password, region=self.region)

        try:
            print("[SIGEN] Initializing asynchronous portal network sockets...")
            await self.sigstore.async_initialize()
            print("[SIGEN SUCCESS] Remote API session token obtained successfully.")
        except Exception as e:
            print(f"[SIGEN CRITICAL] Initialization sequence aborted by remote host: {e}")
            return

        print("[ARMED] Sigen data sync loop active. Refreshing solar stats every 15 seconds.")

        # 2. Continuous data gathering loop using clean asyncio scheduling wrappers
        while True:
            try:
                # Trigger simultaneous async calls natively to maximize performance
                await self.sigstore.refresh()

                # Safely extract dictionary nodes using your wrapper attributes
                station_info = getattr(self.sigstore, 'station_info', {}) or {}
                energy_flow = getattr(self.sigstore, 'energy_flow', {}) or {}

                # Extract your custom property values safely, handling possible None responses
                battery_soc = energy_flow.get("batterySoc", 0)
                battery_power = energy_flow.get("batteryPower", 0)
                grid_power = energy_flow.get("buySellPower", 0)
                solar_yield_today = energy_flow.get("pvDayNrg", 0.0)

                # 3. Compile the canonical system JSON packet format matching your UI expectations
                unified_sigen_payload = {
                    "battery_soc": int(battery_soc) if battery_soc is not None else 0,
                    "battery_flow": int(battery_power) if battery_power is not None else 0,
                    "grid_flow": int(grid_power) if grid_power is not None else 0,
                    "solar_kwh_today": float(solar_yield_today) if solar_yield_today is not None else 0.0
                }

                # 4. Broadcast the metrics over the shared UI telemetry topics with retention enabled
                json_data = json.dumps(unified_sigen_payload)
                self.mqtt_client.publish("home/power/sigen", json_data, retain=True)
                print(f"[SIGEN SYNC] Broadcasted metrics to 'home/power/sigen': {json_data}")

            except Exception as e:
                print(f"[SIGEN UPDATE EXCEPTION] Processing cycle skipped on this tick: {e}")

            # Yield system resources cleanly for 15 seconds before launching the next sync check
            await asyncio.sleep(15.0)


def main():
    daemon = SigenPowerAutomationDaemon()
    daemon.init_mqtt()

    # Fire up the asynchronous runtime loop engine cleanly
    try:
        asyncio.run(daemon.run_async_loop())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Halting Sigen energy tracking daemon loops safely.")
        if daemon.mqtt_client:
            daemon.mqtt_client.loop_stop()


if __name__ == "__main__":
    main()
