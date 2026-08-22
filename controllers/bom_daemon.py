import sys
import time
import json
import ftplib
import xml.etree.ElementTree as ET
from pathlib import Path
import configparser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)


class BomForecastXmlDaemon:
    """
    Background supervisor parsing official BOM XML structural forecast products hourly.
    Tracks location attributes directly to prevent node parsing drops across Windows and Pi.
    """

    def __init__(self):
        print("[INIT] Launching Bureau of Meteorology (BOM) XML Forecast Sync Daemon...")

        # Load centralized configuration variables
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.ftp_host = self._get_config_str("BOM", "ftp_host", "ftp.bom.gov.au")
        self.remote_dir = self._get_config_str("BOM", "remote_dir", "/anon/gen/fwo/")
        self.target_file = self._get_config_str("BOM", "forecast_file", "IDV10450.xml")

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
            print(f"[MQTT] Connecting data pipeline to broker at {self.broker_ip}...")
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] BOM Daemon failed connecting to broker: {e}")

        print(f"[ARMED] Hourly BOM XML engine active. Tracking file: {self.target_file}")
        try:
            while True:
                self._fetch_and_parse_bom_xml()
                print("[STANDBY] Forecast matrix synchronized. Next update in 60 minutes.")
                time.sleep(3600.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Halting BOM XML forecast monitoring loops.")
            self.mqtt_client.loop_stop()

    def _fetch_and_parse_bom_xml(self):
        print(f"[FTP FETCH] Requesting weather package from {self.ftp_host}...")
        xml_bytes = bytearray()
        ftp = ftplib.FTP()

        try:
            ftp.connect(self.ftp_host, 21, timeout=15)
            ftp.login()  # Free public anonymous access link
            ftp.cwd(self.remote_dir)
            ftp.retrbinary(f"RETR {self.target_file}", xml_bytes.extend)
            ftp.quit()

            raw_xml_text = xml_bytes.decode('utf-8', errors='ignore')
            self._process_xml_tree(raw_xml_text)

        except Exception as e:
            print(f"[FTP ERROR] Remote transfer pipeline failed or timed out: {e}")
            try:
                ftp.close()
            except:
                pass

    def _process_xml_tree(self, xml_string: str):
        """Parses nested schemas matching literal BOM description elements safely."""
        try:
            root = ET.fromstring(xml_string)
            forecast_days = []

            # Target the explicit location node for Melbourne/Altona metropolitan zones
            # Maps onto <area description="Melbourne" type="location"> inside IDV10450.xml
            target_area = None
            for area in root.findall(".//area"):
                if area.get("description") == "Melbourne" and area.get("type") == "location":
                    target_area = area
                    break

            if target_area is None:
                print("[XML WARN] Could not isolate 'Melbourne' location block in XML payload.")
                return

            # Extract daily forecast elements from the targeted area branch
            for period in target_area.findall("forecast-period"):
                day_index = period.get("index")  # index="0" = Today, "1" = Tomorrow
                start_time_utc = period.get("start-time-utc")

                min_temp = None
                max_temp = None
                summary_text = ""

                # Iterate internal data points
                for element in period.findall("element"):
                    elem_type = element.get("type")
                    if elem_type == "air_temperature_minimum":
                        min_temp = float(element.text) if element.text else None
                    elif elem_type == "air_temperature_maximum":
                        max_temp = float(element.text) if element.text else None

                text_elem = period.find("text[@type='forecast']")
                if text_elem is not None:
                    summary_text = text_elem.text

                forecast_days.append({
                    "day_index": int(day_index),
                    "utc_timestamp": start_time_utc,
                    "expected_min": min_temp,
                    "expected_max": max_temp,
                    "summary": summary_text
                })

            if forecast_days:
                compiled_payload = {
                    "station_region": "Melbourne/Altona Metro Area",
                    "last_updated_tick": time.time(),
                    "forecast_set": forecast_days
                }

                # Broadcast the clean array over your local MQ broker
                json_data = json.dumps(compiled_payload)
                self.mqtt_client.publish("home/environment/forecast", json_data, retain=True)
                print(f"[XML SUCCESS] Extracted and streamed forecast data successfully: {len(forecast_days)} days.")
            else:
                print("[XML WARN] Forecast periods block was empty inside matching location node.")

        except Exception as e:
            print(f"[XML TREE EXCEPTION] Failed parsing BOM document fields: {e}")


if __name__ == "__main__":
    daemon = BomForecastXmlDaemon()
    daemon.start()
