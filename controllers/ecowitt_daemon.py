import sys
import socket
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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
        self.api_url = self._get_config_str("ECOWITT", "api_url", "").rstrip("/")
        if self.api_url == "https://ecowitt.net":
            self.api_url = "https://api.ecowitt.net"
        self.application_key = self._get_config_str("ECOWITT", "application_key", "")
        self.user_key = self._get_config_str("ECOWITT", "user_key", "")
        self.mac_address = self._get_config_str("ECOWITT", "mac_address", "")
        self.api_interval = 60.0
        self._last_api_poll = 0.0

        self.mqtt_client = None
        print(
            f"[CONFIG] Ecowitt API telemetry: "
            f"{'enabled' if self._api_enabled() else 'disabled'} "
            f"(interval {self.api_interval:.0f}s)"
        )

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

            if self._api_enabled() and time.monotonic() - self._last_api_poll >= self.api_interval:
                try:
                    api_payload = self._fetch_api_payload()
                    if api_payload:
                        self._publish_payloads({}, api_payload)
                        print(
                            "[ECOWITT API] Published "
                            f"{len(api_payload) - 1} outdoor measurements."
                        )
                    self._last_api_poll = time.monotonic()
                except Exception as e:
                    print(f"[API ERROR] Failed to fetch Ecowitt real-time data: {e}")

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
                "outside_temp": out_temp_c,
                "humidity": out_humidity,
                "wind_speed": wind_speed_kmh,
                "wind_speed_kmh": wind_speed_kmh,
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

    def _api_enabled(self):
        return bool(self.api_url and self.application_key and self.user_key and self.mac_address)

    def _fetch_api_payload(self):
        """Fetch normalized outdoor fields from the Ecowitt cloud API.

        The LAN query format differs between gateway firmware versions and does
        not reliably include solar/rain fields. The API response has stable
        logical names, so it is used when the optional MAC address is configured.
        """
        query = urlencode({
            "application_key": self.application_key,
            "api_key": self.user_key,
            "mac": self.mac_address,
            "call_back": "all",
        })
        request = Request(
            f"{self.api_url}/api/v3/device/real_time?{query}",
            headers={"Accept": "application/json", "User-Agent": "HomeAutomation_G1"},
        )
        with urlopen(request, timeout=8) as response:
            document = json.loads(response.read().decode("utf-8"))
        if document.get("code") not in (None, 0, "0"):
            raise RuntimeError(document.get("msg", f"API returned code {document.get('code')}"))
        return self._normalise_api_payload(document.get("data", document))

    @classmethod
    def _normalise_api_payload(cls, payload):
        def measurement_in(section_names, value_names):
            section = cls._find_section(payload, section_names)
            measurement = cls._find_measurement(section, value_names)
            if measurement is None:
                measurement = cls._find_measurement(payload, value_names)
            if measurement is None:
                return None, ""
            return cls._as_float(measurement[0]), measurement[1]

        temperature, temperature_unit = measurement_in(
            ("outdoor", "outdoor_temperature"), ("temperature", "temp", "temp_c"))
        humidity, _ = measurement_in(("outdoor",), ("humidity", "humidity_pct"))
        solar, _ = measurement_in(
            ("solar_and_uvi", "solar", "light"),
            ("solar", "solarradiation", "solar_radiation", "light", "lux"))
        rain_rate, rain_rate_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("rain_rate", "rainrate", "rain_rate_mm"))
        rain_daily, rain_daily_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("daily", "dailyrain", "daily_rain", "daily_mm"))
        rain_event, rain_event_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("event", "eventrain", "event_rain"))
        rain_week, rain_week_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("weekly", "weeklyrain", "weekly_rain"))
        rain_month, rain_month_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("monthly", "monthlyrain", "monthly_rain"))
        rain_year, rain_year_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("yearly", "yearlyrain", "yearly_rain"))
        rain_total, rain_total_unit = measurement_in(
            ("rainfall_piezo", "rain", "rainfall"),
            ("total", "totalrain", "total_rain"))
        wind_speed, wind_speed_unit = measurement_in(
            ("wind",), ("wind_speed", "windspeed", "speed"))
        wind_gust, wind_gust_unit = measurement_in(("wind",), ("wind_gust", "windgust", "gust"))
        wind_direction, _ = measurement_in(
            ("wind",), ("wind_direction", "winddir", "direction"))

        temperature = cls._fahrenheit_to_celsius(temperature, temperature_unit)
        rain_rate = cls._inches_to_mm(rain_rate, rain_rate_unit)
        rain_daily = cls._inches_to_mm(rain_daily, rain_daily_unit)
        rain_event = cls._inches_to_mm(rain_event, rain_event_unit)
        rain_week = cls._inches_to_mm(rain_week, rain_week_unit)
        rain_month = cls._inches_to_mm(rain_month, rain_month_unit)
        rain_year = cls._inches_to_mm(rain_year, rain_year_unit)
        rain_total = cls._inches_to_mm(rain_total, rain_total_unit)
        wind_speed = cls._mph_to_kmh(wind_speed, wind_speed_unit)
        wind_gust = cls._mph_to_kmh(wind_gust, wind_gust_unit)

        result = {"timestamp": time.time()}
        cls._set_if_number(result, "temperature", temperature)
        cls._set_if_number(result, "outside_temp", temperature)
        cls._set_if_number(result, "humidity", humidity)
        cls._set_if_number(result, "solar_radiation", solar)
        # Ecowitt reports solar radiation in W/m². This is an estimated lux
        # equivalent, retained separately so consumers can choose either unit.
        if solar is not None:
            result["outside_lux"] = round(solar * 126.7, 1)
        cls._set_if_number(result, "rain_rate", rain_rate)
        cls._set_if_number(result, "rain_today", rain_daily)
        cls._set_if_number(result, "rain_event", rain_event)
        cls._set_if_number(result, "rain_week", rain_week)
        cls._set_if_number(result, "rain_month", rain_month)
        cls._set_if_number(result, "rain_year", rain_year)
        cls._set_if_number(result, "rain_total", rain_total)
        cls._set_if_number(result, "wind_speed", wind_speed)
        cls._set_if_number(result, "wind_speed_kmh", wind_speed)
        cls._set_if_number(result, "wind_gust", wind_gust)
        cls._set_if_number(result, "wind_direction", wind_direction)
        return result

    @staticmethod
    def _find_section(value, names):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in names:
                    return child
                found = EcowittLanIngestionDaemon._find_section(child, names)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = EcowittLanIngestionDaemon._find_section(child, names)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _find_value(value, names):
        measurement = EcowittLanIngestionDaemon._find_measurement(value, names)
        return measurement[0] if measurement else None

    @staticmethod
    def _find_measurement(value, names):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in names:
                    if isinstance(child, dict):
                        measured_value = child.get("value", child.get("val"))
                        if measured_value is not None:
                            return measured_value, str(child.get("unit", ""))
                    elif not isinstance(child, list):
                        return child, ""
            for child in value.values():
                found = EcowittLanIngestionDaemon._find_measurement(child, names)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = EcowittLanIngestionDaemon._find_measurement(child, names)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _as_float(value):
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _set_if_number(target, key, value):
        if value is not None:
            target[key] = value

    @staticmethod
    def _fahrenheit_to_celsius(value, unit):
        if value is not None and "f" in unit.lower():
            return round((value - 32.0) * 5.0 / 9.0, 1)
        return value

    @staticmethod
    def _inches_to_mm(value, unit):
        if value is not None and "in" in unit.lower():
            return round(value * 25.4, 2)
        return value

    @staticmethod
    def _mph_to_kmh(value, unit):
        if value is not None and "mph" in unit.lower():
            return round(value * 1.60934, 1)
        return value

    def _generate_simulated_dual_telemetry(self):
        """Generates realistic changing indoor and outdoor trends for local PC testing."""
        import random
        simulated_outdoor_temp = round(14.5 + random.uniform(-0.1, 0.1), 1)
        outdoor_payload = {
            "temperature": simulated_outdoor_temp,
            "outside_temp": simulated_outdoor_temp,
            "humidity": random.randint(62, 70),
            "outside_lux": round(random.uniform(1500, 25000), 1),
            "solar_radiation": round(random.uniform(12, 200), 1),
            "rain_rate": 0.0,
            "rain_today": round(random.uniform(0, 4), 1),
            "rain_event": 0.0,
            "wind_speed": round(16.5 + random.uniform(-1.0, 2.0), 1),
            "wind_speed_kmh": round(16.5 + random.uniform(-1.0, 2.0), 1),
            "wind_gust": round(random.uniform(20, 35), 1),
            "wind_direction": random.randint(0, 359),
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
        if rumpus_dict:
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
