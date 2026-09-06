import sys
from pathlib import Path

# Dynamic system path hook to guarantee cross-folder package imports resolve cleanly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import time as pytime
import json
import asyncio
import configparser

try:
    from libraries.sigen_library import Sigen

    SIGEN_LIB_AVAILABLE = True
except ImportError:
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

from libraries.paho_compat import create_client


class SigenPowerAutomationDaemon:
    """
    Headless background supervisor interacting with your custom Sigen library asynchronously.
    Preserves raw float precision across all active energy properties to ensure high resolution.
    """

    def __init__(self):
        print("[INIT] Launching SigenStor Inverter Data Ingestion Daemon...")

        # Load configuration parameters
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.username = self._get_config_str("SIGEN", "username", "Junkmail_MWW@Internode.on.net")
        self.password = self._get_config_str("SIGEN", "password", "b$JJPX6!Lg8*cmr")
        self.region = self._get_config_str("SIGEN", "region", "au")

        self.sigstore = None
        self.mqtt_client = None

        if not SIGEN_LIB_AVAILABLE:
            print("[CRITICAL] 'sigen_library' folder could not be mounted by the Python compiler.")
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
        self.mqtt_client = create_client()
        try:
            print(f"[MQTT] Connecting Sigen data loop to broker at {self.broker_ip}...")
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Sigen Daemon failed connecting to broker: {e}")
            sys.exit(1)

    async def run_async_loop(self):
        """Orchestrates asynchronous initializations and periodic query schedules."""
        self.sigstore = Sigen(username=self.username, password=self.password, region=self.region)

        try:
            print("[SIGEN] Initializing asynchronous portal network sockets...")
            await self.sigstore.async_initialize()
            print("[SIGEN SUCCESS] Remote API session token obtained successfully.")
        except Exception as e:
            print(f"[SIGEN CRITICAL] Initialization sequence aborted by remote host: {e}")
            return

        print("[ARMED] Sigen data sync loop active. Refreshing solar stats every 15 seconds.")

        while True:
            try:
                # Fetch fresh statistics from the Sigen endpoints
                station_info = await self.sigstore.fetch_station_info()
                energy_flow = await self.sigstore.get_energy_flow()
                operational_mode = await self.sigstore.get_operational_mode()

                if station_info is None: station_info = {}
                if energy_flow is None: energy_flow = {}

                # FIXED: Shifted fields to pure floats to capture full decimal precision
                complete_sigen_payload = {
                    "battery_soc": float(energy_flow.get("batterySoc", -1.0)) if energy_flow.get("batterySoc") is not None else -1.0,
                    "battery_flow": float(energy_flow.get("batteryPower", 0.0)) if energy_flow.get("batteryPower") is not None else 0.0,
                    "grid_flow": float(energy_flow.get("buySellPower", 0.0)) if energy_flow.get("buySellPower") is not None else 0.0,
                    "solar_power": float(energy_flow.get("pvPower", 0.0)) if energy_flow.get("pvPower") is not None else 0.0,
                    "solar_kwh_today": float(energy_flow.get("pvDayNrg", 0.0)) if energy_flow.get("pvDayNrg") is not None else 0.0,

                    # Retain float resolution across auxiliary tracking parameters
                    "load_power": float(energy_flow.get("loadPower", 0.0)) if energy_flow.get("loadPower") is not None else 0.0,
                    "ev_power": float(energy_flow.get("evPower", 0.0)) if energy_flow.get("evPower") is not None else 0.0,
                    "aircon_power": float(energy_flow.get("acPower", 0.0)) if energy_flow.get("acPower") is not None else 0.0,

                    "station_status": int(energy_flow.get("stationStatus", 0)) if energy_flow.get("stationStatus") is not None else 0,
                    "status": int(station_info.get("status", 0)) if station_info.get("status") is not None else 0,
                    "shutdown_reason": int(station_info.get("shutdownReason", 0)) if station_info.get("shutdownReason") is not None else 0,
                    "operational_mode": str(operational_mode) if operational_mode is not None else "UNKNOWN"
                }

                # Broadcast the high-resolution payload
                json_data = json.dumps(complete_sigen_payload)
                self.mqtt_client.publish("home/power/sigen", json_data, retain=True)
                print(f"[SIGEN SYNC] Sent high-resolution data payload: {json_data}")

            except Exception as e:
                print(f"[SIGEN UPDATE EXCEPTION] Processing cycle skipped on this tick: {e}")

            await asyncio.sleep(15.0)


def main():
    daemon = SigenPowerAutomationDaemon()
    daemon.init_mqtt()

    try:
        asyncio.run(daemon.run_async_loop())
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Halting Sigen energy tracking daemon loops safely.")
        if daemon.mqtt_client:
            daemon.mqtt_client.loop_start()


if __name__ == "__main__":
    main()
