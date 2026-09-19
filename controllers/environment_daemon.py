import sys
import time
import json
import socket
import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import smbus2
except ImportError:
    smbus2 = None

IS_RASPI = sys.platform.startswith("linux")
IS_SIMULATION = sys.platform == "win32"

try:
    import bme680
except ImportError:
    bme680 = None

from libraries.paho_compat import create_client


class LivingAreaHardwareController:
    """
    Living-area environment publisher for the physical sensor hardware.
    Natively calibrates Bosch BME280 metrics and reads VEML6030 modules.
    Includes persistent self-healing network retry hooks for boot delays.
    """
    I2C_BUS_ID = 1
    ADDR_VEML6030 = 0x10
    ADDR_BME_ALT = 0x76
    ADDR_BME_MAIN = 0x77

    def __init__(self):
        print("[INIT] Initializing Living Area Master Automation Subsystem...")
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.hostname = socket.gethostname()

        self.bus = None
        self.discovered_bme_addr = None
        self.bme_sensor_type = None
        self.bme_calibration_params = None
        self.bme680_sensor = None
        self.veml_is_online = False
        self._shared_null_published = False

        self._initialize_hardware()

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

    def _initialize_hardware(self):
        """Configures physical board pin states and queries active I2C addresses."""
        if not IS_RASPI:
            if IS_SIMULATION:
                print("[HARDWARE] Windows detected. Arming virtual device simulation abstractions.")
            else:
                print("[HARDWARE] No Raspberry Pi I2C hardware is available.")
            return
        if smbus2 is None:
            print("[HARDWARE] smbus2 is unavailable; environment readings will be null.")
            return

        try:
            self.bus = smbus2.SMBus(self.I2C_BUS_ID)

            for addr in [self.ADDR_BME_MAIN, self.ADDR_BME_ALT]:
                try:
                    chip_id = self.bus.read_byte_data(addr, 0xD0)
                    if chip_id == 0x60:
                        self.bme_calibration_params = (
                            self._load_bme280_calibration(addr)
                        )
                        self.bme_sensor_type = "BME280_DIRECT"
                    elif chip_id == 0x61:
                        if bme680 is None:
                            raise RuntimeError(
                                "bme680 Python package is not installed"
                            )
                        self.bme680_sensor = bme680.BME680(addr)
                        self.bme_sensor_type = "BME680"
                    else:
                        raise RuntimeError(
                            f"unknown Bosch sensor chip ID 0x{chip_id:02x}"
                        )
                    self.discovered_bme_addr = addr
                    print(
                        f"[I2C SUCCESS] Detected and initialized "
                        f"{self.bme_sensor_type} at {hex(addr)}"
                    )
                    break
                except Exception as error:
                    self.discovered_bme_addr = None
                    self.bme_sensor_type = None
                    self.bme_calibration_params = None
                    self.bme680_sensor = None
                    print(
                        f"[I2C WARN] Bosch environmental sensor setup failed at "
                        f"{hex(addr)}: "
                        f"{error}"
                    )

            try:
                self.bus.read_byte(self.ADDR_VEML6030)
                self.bus.write_word_data(self.ADDR_VEML6030, 0x00, 0x0000)
                time.sleep(0.01)
                self.veml_is_online = True
                print("[I2C SUCCESS] Auto-detected and initialized VEML6030 Light Sensor at hex address: 0x10")
            except Exception as e:
                print(f"[I2C WARN] VEML6030 failed handshake initialization: {e}")
                self.veml_is_online = False

        except Exception as e:
            print(f"[HARDWARE CRITICAL] Failed initializing Pi interaction lines: {e}")

    def start(self):
        """Launches the thread listener with an automated, self-healing network retry loop."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("[CRITICAL] 'paho-mqtt' library missing.")
            return

        self.mqtt_client = create_client()
        self.mqtt_client.on_connect = lambda c, u, f, rc, p=None: None

        # FIXED: Self-healing reconnection manager loops continuously if Wi-Fi hasn't bound yet
        connected = False
        print(f"[MQTT CONNECTING] Establishing link to network broker at {self.broker_ip}...")

        while not connected:
            try:
                self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
                self.mqtt_client.loop_start()
                print("[MQTT SUCCESS] Successfully established pipeline link with network broker.")
                connected = True
            except (OSError, Exception) as e:
                print(f"[NETWORK DELAY] Broker link unreachable: {e}. Retrying in 5 seconds...")
                time.sleep(5.0)  # Pause cleanly before attempting the next network handshake

        print("[RUNNING] Living Area environment loop active. Sampling sensors every 5 seconds.")
        try:
            while True:
                self._process_environment_tick()
                time.sleep(5.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Stopping living-area environment telemetry.")
            self.mqtt_client.loop_stop()

    def _on_settings_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            settings = {
                "t_min": float(data.get("target_min", self.t_min)),
                "t_max": float(data.get("target_max", self.t_max)),
                "fan_preheat_seconds": float(
                    data.get("fan_preheat_seconds", self.fan_preheat_seconds)
                ),
                "fan_postrun_seconds": float(
                    data.get("fan_postrun_seconds", self.fan_postrun_seconds)
                ),
                "min_run_seconds": float(
                    data.get("min_run_seconds", self.min_run_seconds)
                ),
                "max_run_seconds": float(
                    data.get("max_run_seconds", self.max_run_seconds)
                ),
                "rest_seconds": float(data.get("rest_seconds", self.rest_seconds)),
            }
            with self._settings_lock:
                if not self._settings_are_valid(settings):
                    print("[SETTINGS REJECTED] HVAC timing or target thresholds are invalid.")
                    return
                for name, value in settings.items():
                    setattr(self, name, value)
                try:
                    self.settings_store.save(self._settings_payload())
                except OSError as error:
                    print(f"[SETTINGS ERROR] Unable to persist HVAC settings: {error}")
            print(
                f"[SETTINGS] Min: {self.t_min}°C | Max: {self.t_max}°C | "
                f"Preheat: {self.fan_preheat_seconds}s | Postrun: {self.fan_postrun_seconds}s"
            )
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as e:
            print(f"[MQTT ERROR] Failed parsing setting adjustment frame: {e}")

    @staticmethod
    def _settings_are_valid(settings: dict) -> bool:
        values = tuple(settings.values())
        return (
            all(math.isfinite(value) for value in values)
            and settings["t_min"] < settings["t_max"]
            and settings["min_run_seconds"] > 0
            and settings["max_run_seconds"] >= settings["min_run_seconds"]
            and settings["fan_preheat_seconds"] >= 0
            and settings["fan_postrun_seconds"] >= 0
            and settings["rest_seconds"] >= 0
        )

    def _load_persisted_settings(self):
        settings = self.settings_store.load()
        if not settings:
            return
        self.t_min = settings["target_min"]
        self.t_max = settings["target_max"]
        self.fan_preheat_seconds = settings["fan_preheat_seconds"]
        self.fan_postrun_seconds = settings["fan_postrun_seconds"]
        self.min_run_seconds = settings["min_run_seconds"]
        self.max_run_seconds = settings["max_run_seconds"]
        self.rest_seconds = settings["rest_seconds"]

    def _settings_payload(self):
        return {
            "target_min": self.t_min,
            "target_max": self.t_max,
            "fan_preheat_seconds": self.fan_preheat_seconds,
            "fan_postrun_seconds": self.fan_postrun_seconds,
            "min_run_seconds": self.min_run_seconds,
            "max_run_seconds": self.max_run_seconds,
            "rest_seconds": self.rest_seconds,
        }

    def _read_sensors(self) -> tuple[float | None, float | None, float | None, float | None]:
        """Polls physical sensors safely using factory calibration polynomials."""
        if not IS_RASPI:
            if not IS_SIMULATION:
                return None, None, None, None
            import random
            return round(21.5 + random.uniform(-0.1, 0.1), 1), 52.0, 320.0, 1013.0
        if not self.bus:
            return None, None, None, None

        temp_c, humidity, lux, pressure = None, None, None, None

        try:
            if self.bme_sensor_type == "BME280_DIRECT":
                temp_c, humidity, pressure = self._read_bme280(
                    addr=self.discovered_bme_addr
                )
            elif self.bme_sensor_type == "BME680" and self.bme680_sensor:
                if self.bme680_sensor.get_sensor_data():
                    temp_c = round(self.bme680_sensor.data.temperature, 1)
                    humidity = round(self.bme680_sensor.data.humidity, 1)
                    pressure = round(self.bme680_sensor.data.pressure, 1)

            if not self.veml_is_online:
                try:
                    self.bus.read_byte(self.ADDR_VEML6030)
                    self.bus.write_word_data(self.ADDR_VEML6030, 0x00, 0x0000)
                    self.veml_is_online = True
                except Exception:
                    pass

            if self.veml_is_online:
                try:
                    lux_raw = self.bus.read_word_data(self.ADDR_VEML6030, 0x04)
                    lux = float(lux_raw) * 0.0576
                except Exception:
                    self.veml_is_online = False

        except Exception as e:
            print(f"[I2C READ EXCEPTION] Telemetry extraction stalled: {e}")

        if pressure is not None and not 800.0 <= pressure <= 1100.0:
            print(f"[SENSOR WARN] Ignoring invalid pressure reading: {pressure}")
            pressure = None
        return temp_c, humidity, lux, pressure

    def _process_environment_tick(self):
        temp, humidity, lux, pressure = self._read_sensors()
        self._publish_telemetry(temp, humidity, lux, pressure)

    @staticmethod
    def _signed(value, bits):
        if value & (1 << (bits - 1)):
            return value - (1 << bits)
        return value

    def _load_bme280_calibration(self, addr):
        read = self.bus.read_i2c_block_data
        block = read(addr, 0x88, 24)
        block.append(self.bus.read_byte_data(addr, 0xA1))
        block.extend(read(addr, 0xE1, 7))
        return {
            "t1": block[0] | block[1] << 8,
            "t2": self._signed(block[2] | block[3] << 8, 16),
            "t3": self._signed(block[4] | block[5] << 8, 16),
            "p1": block[6] | block[7] << 8,
            "p2": self._signed(block[8] | block[9] << 8, 16),
            "p3": self._signed(block[10] | block[11] << 8, 16),
            "p4": self._signed(block[12] | block[13] << 8, 16),
            "p5": self._signed(block[14] | block[15] << 8, 16),
            "p6": self._signed(block[16] | block[17] << 8, 16),
            "p7": self._signed(block[18] | block[19] << 8, 16),
            "p8": self._signed(block[20] | block[21] << 8, 16),
            "p9": self._signed(block[22] | block[23] << 8, 16),
            "h1": block[24],
            "h2": self._signed(block[25] | block[26] << 8, 16),
            "h3": block[27],
            "h4": self._signed((block[28] << 4) | (block[29] & 0x0F), 12),
            "h5": self._signed((block[30] << 4) | (block[29] >> 4), 12),
            "h6": self._signed(block[31], 8),
        }

    def _read_bme280(self, addr):
        calibration = self.bme_calibration_params
        self.bus.write_byte_data(addr, 0xF2, 0x01)
        self.bus.write_byte_data(addr, 0xF4, 0x25)
        time.sleep(0.01)
        raw = self.bus.read_i2c_block_data(addr, 0xF7, 8)
        adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
        adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
        adc_h = (raw[6] << 8) | raw[7]

        var1 = (
            (adc_t / 16384.0 - calibration["t1"] / 1024.0)
            * calibration["t2"]
        )
        var2 = (
            (adc_t / 131072.0 - calibration["t1"] / 8192.0) ** 2
            * calibration["t3"]
        )
        t_fine = var1 + var2
        temperature = t_fine / 5120.0

        humidity = t_fine - 76800.0
        humidity = (
            adc_h
            - (calibration["h4"] * 64.0
               + calibration["h5"] / 16384.0 * humidity)
        ) * (
            calibration["h2"] / 65536.0
            * (1.0 + calibration["h6"] / 67108864.0 * humidity
               * (1.0 + calibration["h3"] / 67108864.0 * humidity))
        )
        humidity *= 1.0 - calibration["h1"] * humidity / 524288.0
        pressure_var1 = t_fine / 2.0 - 64000.0
        pressure_var2 = pressure_var1 * pressure_var1 * calibration["p6"] / 32768.0
        pressure_var2 += pressure_var1 * calibration["p5"] * 2.0
        pressure_var2 = pressure_var2 / 4.0 + calibration["p4"] * 65536.0
        pressure_var1 = (
            calibration["p3"] * pressure_var1 * pressure_var1 / 524288.0
            + calibration["p2"] * pressure_var1
        ) / 524288.0
        pressure_var1 = (1.0 + pressure_var1 / 32768.0) * calibration["p1"]
        if pressure_var1 == 0:
            pressure = 0.0
        else:
            pressure = (1048576.0 - adc_p - pressure_var2 / 4096.0)
            pressure = pressure * 6250.0 / pressure_var1
            pressure_var1 = calibration["p9"] * pressure * pressure / 2147483648.0
            pressure_var2 = pressure * calibration["p8"] / 32768.0
            pressure = pressure + (pressure_var1 + pressure_var2 + calibration["p7"]) / 16.0
            pressure /= 100.0
        return (
            round(temperature, 1),
            round(max(0.0, min(100.0, humidity)), 1),
            round(pressure, 1),
        )

    def _apply_physical_relay_state(self, target_mode: str):
        if not IS_RASPI:
            print(f"[MOCK RELAY OUT] Switching Board Pins to State: -> {target_mode}")
            return

        GPIO.output(self.RELAY_HEAT, GPIO.LOW)
        GPIO.output(self.RELAY_COOL, GPIO.LOW)
        if target_mode == "HEATING":
            GPIO.output(self.RELAY_HEAT, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        elif target_mode == "COOLING":
            GPIO.output(self.RELAY_COOL, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        elif target_mode == "FAN":
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        else:
            GPIO.output(self.RELAY_FAN, GPIO.LOW)

    def _process_automation_tick(self):
        with self._settings_lock:
            self._process_automation_tick_locked()

    def _process_automation_tick_locked(self):
        current_temp, humidity, lux, pressure = self._read_sensors()
        now = time.time()

        if self.hvac_sequence_state == "POSTRUN":
            if now - self.sequence_started_at >= self.fan_postrun_seconds:
                self.hvac_sequence_state = "OFF"
                self.pending_hvac_state = None
                self._apply_physical_relay_state("OFF")
                self.blind_pre_close_sent = False
            self._publish_telemetry(current_temp, humidity, lux, pressure)
            return

        if self.is_resting:
            if now - self.rest_start_time >= self.rest_seconds:
                print("[SAFETY] Mandatory compressor rest interval elapsed. Re-arming coils.")
                self.is_resting = False
            else:
                self._publish_telemetry(current_temp, humidity, lux, pressure)
                return

        next_state = self._requested_hvac_state(current_temp)

        if self.hvac_sequence_state == "PREHEAT":
            if next_state != self.pending_hvac_state:
                if next_state == "OFF":
                    self.hvac_sequence_state = "OFF"
                    self.pending_hvac_state = None
                    self._apply_physical_relay_state("OFF")
                else:
                    self.pending_hvac_state = next_state
                    self.sequence_started_at = now
            elif now - self.sequence_started_at >= self.fan_preheat_seconds:
                self._start_active_run(self.pending_hvac_state, now)
            self._publish_telemetry(current_temp, humidity, lux, pressure)
            return

        if self.current_hvac_state in ("HEATING", "COOLING"):
            active_duration = now - self.active_run_started_at
            if active_duration >= self.max_run_seconds:
                print("[SAFETY] Maximum active run reached. Enforcing mandatory rest.")
                self._end_active_run(now, start_rest=True)
            elif next_state != self.current_hvac_state and active_duration >= self.min_run_seconds:
                print(f"[AUTOMATION] Ending {self.current_hvac_state} after minimum run period.")
                self._end_active_run(now)
            self._publish_telemetry(current_temp, humidity, lux, pressure)
            return

        if next_state != "OFF":
            self._start_preheat(next_state, now)
        self._publish_telemetry(current_temp, humidity, lux, pressure)

    def _requested_hvac_state(self, current_temp: float) -> str:
        if current_temp < self.t_min:
            return "HEATING"
        if current_temp > self.t_max:
            return "COOLING"
        return "OFF"

    def _start_preheat(self, target_state: str, now: float):
        self.pending_hvac_state = target_state
        self.hvac_sequence_state = "PREHEAT"
        self.sequence_started_at = now
        self._apply_physical_relay_state("FAN")
        self._send_blind_pre_close()
        if self.fan_preheat_seconds == 0:
            self._start_active_run(target_state, now)

    def _start_active_run(self, target_state: str, now: float):
        self.current_hvac_state = target_state
        self.pending_hvac_state = None
        self.hvac_sequence_state = target_state
        self.active_run_started_at = now
        self._apply_physical_relay_state(target_state)
        print(f"[AUTOMATION] Active {target_state} run started.")

    def _end_active_run(self, now: float, start_rest: bool = False):
        self.current_hvac_state = "OFF"
        self.active_run_started_at = None
        self.hvac_sequence_state = "POSTRUN"
        self.sequence_started_at = now
        self._apply_physical_relay_state(
            "FAN" if self.fan_postrun_seconds > 0 else "OFF"
        )
        if self.fan_postrun_seconds == 0:
            self.hvac_sequence_state = "OFF"
        if start_rest:
            self.is_resting = True
            self.rest_start_time = now

    def _send_blind_pre_close(self):
        if not self.blind_pre_close_sent:
            print("[ANTICIPATOR] Climate request detected. Issuing anticipatory blind drop.")
            self.mqtt_client.publish(
                "home/blinds/command",
                json.dumps({"action": "CLOSE", "reason": "LIVING_ZONE_ANTICIPATION"}),
            )
            self.blind_pre_close_sent = True

    def _publish_telemetry(
        self,
        temp: float | None,
        humidity: float | None,
        lux: float | None,
        pressure: float | None,
    ):
        payload = {
            "room_name": self.hostname,
            "hostname": self.hostname,
            "device_name": self.hostname,
            "temperature": temp,
            "humidity": humidity,
            "pressure": pressure,
            "light_lux": round(lux, 1) if lux is not None else None,
            "timestamp": time.time()
        }
        payload_json = json.dumps(payload)
        if temp is not None or not getattr(self, "_shared_null_published", False):
            self.mqtt_client.publish(
                "home/environment/living",
                payload_json,
                retain=True,
            )
            if temp is None:
                self._shared_null_published = True
        self.mqtt_client.publish(
            f"home/environment/living/{self.hostname}",
            payload_json,
            retain=True,
        )
        print(
            f"[TELEMETRY] {self.hostname}: "
            f"{temp if temp is not None else '--'}°C, "
            f"{humidity if humidity is not None else '--'}% RH, "
            f"{f'{lux:.1f}' if lux is not None else '--'} lx"
        )


if __name__ == "__main__":
    daemon = LivingAreaHardwareController()
    daemon.start()
