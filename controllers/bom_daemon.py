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
    print("[CRITICAL] 'paho-mqtt' library missing. Run 'pip install paho-mqtt'.")
    sys.exit(1)


class BomForecastXmlDaemon:
    """
    Background supervisor parsing official BOM XML structural forecast products hourly.
    Extracts multi-day predictive weather metrics tailored for touchscreen display pipelines.
    """

    def __init__(self):
        print("[INIT] Launching Bureau of Meteorology (BOM) XML Forecast Sync Daemon...")

        # Load centralized path configurations
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.ftp_host = self._get_config_str("BOM", "ftp_host", "ftp.bom.gov.au")
        self.remote_dir = self._get_config_str("BOM", "remote_dir", "/anon/gen/fwo/")

        # Point to the official XML 7-day forecast file for the Victorian/Altona area
        self.target_file = self._get_config_str("BOM", "forecast_file", "IDV71073.xml")

    def _get_config_str(self, section, key, fallback) -> str:
        config_path = Path(__file__).resolve().parent / "config.ini"
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
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] BOM XML Daemon failed connecting to broker: {e}")

        print(f"[RUNNING] Hourly BOM XML engine armed. Tracking target file: {self.target_file}")
        try:
            while True:
                # Trigger an data execution cycle immediately on launch, then sleep
                self._fetch_and_parse_bom_xml()
                print("[STANDBY] Forecast matrix synchronized. Sleeping for 60 minutes.")
                time.sleep(3600.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Halting BOM XML forecast monitoring loops.")
            self.mqtt_client.loop_stop()

    def _fetch_and_parse_bom_xml(self):
        """Pulls down the target XML text payload over public anonymous FTP channels cleanly."""
        print(f"[FTP CONNECT] Querying forecast data blocks -> {self.ftp_host}")
        xml_bytes = io_bytes = bytearray()
        ftp = ftplib.FTP()

        try:
            ftp.connect(self.ftp_host, 21, timeout=15)
            ftp.login()  # Free anonymous access point
            ftp.cwd(self.remote_dir)

            # Read structural binary streams into local system data structures
            ftp.retrbinary(f"RETR {self.target_file}", xml_bytes.extend)
            ftp.quit()

            # Process string conversions safely
            raw_xml_text = xml_bytes.decode('utf-8', errors='ignore')
            self._process_xml_tree(raw_xml_text)

        except Exception as e:
            print(f"[FTP XML ERROR] Remote transfer pipeline stalled or dropped: {e}")
            try:
                ftp.close()
            except:
                pass

    def _process_xml_tree(self, xml_string: str):
        """Parses the nested BOM schema elements to harvest structured forecast parameters."""
        try:
            root = ET.fromstring(xml_string)

            # Trackers for mapping structural forecast metrics
            forecast_days = []

            # The BOM XML layout separates forecasts by specific area nodes using "aac" identifiers.
            # AAC="VIC_PT001" represents the main Melbourne / Metropolitan area covering Altona.
            for area in root.findall(".//area[@aac='VIC_PT001']/forecast-period"):
                day_index = area.get("index")  # index="0" means Today, "1" means Tomorrow, etc.
                start_time_utc = area.get("start-time-utc")

                # Dynamic structures to trap element properties inside each forecast tree node
                min_temp = None
                max_temp = None
                summary_text = ""

                # Check structural parameters mapped inside the forecast period leaf node
                for element in area.findall("element"):
                    elem_type = element.get("type")
                    if elem_type == "air_temperature_minimum":
                        min_temp = float(element.text)
                    elif elem_type == "air_temperature_maximum":
                        max_temp = float(element.text)

                # Check textual block properties for the day description string
                text_elem = area.find("text[@type='forecast']")
                if text_elem is not None:
                    summary_text = text_elem.text

                # Save the parsed day structure
                forecast_days.append({
                    "day_index": int(day_index),
                    "utc_timestamp": start_time_utc,
                    "expected_min": min_temp,
                    "expected_max": max_temp,
                    "summary": summary_text
                })

            if forecast_days:
                # Structure the compiled multiday matrix dictionary
                compiled_payload = {
                    "station_region": "Melbourne/Altona Metro Area",
                    "last_updated_tick": time.time(),
                    "forecast_set": forecast_days
                }

                # Broadcast the JSON structure over your local MQTT broker line
                json_data = json.dumps(compiled_payload)
                self.mqtt_client.publish("home/environment/forecast", json_data, retain=True)
                print(f"[XML SUCCESS] Streamed clean forecast array: {json_data}")
            else:
                print("[XML WARN] Could not isolate matching metropolitan forecast nodes in XML payload.")

        except Exception as e:
            print(f"[XML TREE EXCEPTION] Failed parsing BOM document fields: {e}")


if __name__ == "__main__":
    # Inline quick buffer patch to handle standard binary writing structures
    import io

    io_bytes = bytearray

    daemon = BomForecastXmlDaemon()
    daemon.start()
