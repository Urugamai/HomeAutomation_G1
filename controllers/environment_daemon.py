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
    import RPi.GPIO as GPIO
    import smbus2

    IS_RASPI = True
except ImportError:
    GPIO = None
    smbus2 = None
    IS_RASPI = False

try:
    import bme680
except ImportError:
    bme680 = None

from libraries.paho_compat import create_client


class LivingAreaHardwareController:
    """
    Core automation engine driving Living Area physical hardware.
    Natively calibrates Bosch BME280 metrics and reads VEML6030 modules.
    Includes persistent self-healing network retry hooks for boot delays.
    """
    RELAY_HEAT = 26
    RELAY_COOL = 20
    RELAY_FAN = 21

    I2C_BUS_ID = 1
    ADDR_VEML6030 = 0x10
    ADDR_BME_ALT = 0x76
    ADDR_BME_MAIN = 0x77

    def __init__(self):
        print("[INIT] Initializing Living Area Master Automation Subsystem...")
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")
        self.hostname = socket.gethostname()

        self.t_min = 20.0
        self.t_max = 24.0

        self.current_hvac_state = "OFF"
        self.last_state_change_time = time.time()
        self.is_resting = False
        self.rest_start_time = 0.0
        self.blind_pre_close_sent = False

        self.bus = None
        self.discovered_bme_addr = None
        self.bme_sensor_type = None
        self.bme_calibration_params = None
        self.bme680_sensor = None
        self.veml_is_online = False

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
            print("[HARDWARE] Windows 11 detected. Arming virtual device simulation abstractions.")
            return

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for pin in [self.RELAY_HEAT, self.RELAY_COOL, self.RELAY_FAN]:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)

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
        self.mqtt_client.on_connect = lambda c, u, f, rc, p=None: c.subscribe("home/hvac/settings")
        self.mqtt_client.on_message = self._on_settings_message

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

        print("[RUNNING] Living Area automation loop active. Sampling sensors every 5 seconds.")
        try:
            while True:
                self._process_automation_tick()
                time.sleep(5.0)
        except KeyboardInterrupt:
            print("[SHUTDOWN] Demobilizing automation relays. Isolating contactors.")
            self._apply_physical_relay_state("OFF")
            if IS_RASPI:
                GPIO.cleanup()
            self.mqtt_client.loop_stop()

    def _on_settings_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            self.t_min = float(data.get("target_min", self.t_min))
            self.t_max = float(data.get("target_max", self.t_max))
            print(f"[SETTINGS] Thresholds adjusted -> Min: {self.t_min}°C | Max: {self.t_max}°C")
        except Exception as e:
            print(f"[MQTT ERROR] Failed parsing setting adjustment frame: {e}")

    def _read_sensors(self) -> tuple[float, float, float]:
        """Polls physical sensors safely using factory calibration polynomials."""
        if not IS_RASPI or not self.bus:
            import random
            return round(21.5 + random.uniform(-0.1, 0.1), 1), 52.0, 320.0

        temp_c, humidity, lux = 22.0, 50.0, 0.0

        try:
            if self.bme_sensor_type == "BME280_DIRECT":
                temp_c, humidity = self._read_bme280(addr=self.discovered_bme_addr)
            elif self.bme_sensor_type == "BME680" and self.bme680_sensor:
                if self.bme680_sensor.get_sensor_data():
                    temp_c = round(self.bme680_sensor.data.temperature, 1)
                    humidity = round(self.bme680_sensor.data.humidity, 1)

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

        return temp_c, humidity, lux

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
        return round(temperature, 1), round(max(0.0, min(100.0, humidity)), 1)

    def _apply_physical_relay_state(self, target_mode: str):
        self.current_hvac_state = target_mode
        self.last_state_change_time = time.time()

        if not IS_RASPI:
            print(f"[MOCK RELAY OUT] Switching Board Pins to State: -> {target_mode}")
            return

        if target_mode == "HEATING":
            GPIO.output(self.RELAY_COOL, GPIO.LOW)
            time.sleep(0.05)
            GPIO.output(self.RELAY_HEAT, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        elif target_mode == "COOLING":
            GPIO.output(self.RELAY_HEAT, GPIO.LOW)
            time.sleep(0.05)
            GPIO.output(self.RELAY_COOL, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        else:
            GPIO.output(self.RELAY_HEAT, GPIO.LOW)
            GPIO.output(self.RELAY_COOL, GPIO.LOW)
            GPIO.output(self.RELAY_FAN, GPIO.LOW)

    def _process_automation_tick(self):
        current_temp, humidity, lux = self._read_sensors()
        now = time.time()

        if self.is_resting:
            if now - self.rest_start_time >= 300:
                print("[SAFETY] 5-minute compressor rest cycle elapsed. Re-arming coils.")
                self.is_resting = False
            else:
                if self.current_hvac_state != "OFF":
                    self._apply_physical_relay_state("OFF")
                self._publish_telemetry(current_temp, humidity, lux)
                return

        if self.current_hvac_state in ["HEATING", "COOLING"]:
            if now - self.last_state_change_time >= 600:
                print(f"[SAFETY] Max 10-minute continuous run boundary hit. Enforcing 5-minute rest.")
                self._apply_physical_relay_state("OFF")
                self.is_resting = True
                self.rest_start_time = now
                self.blind_pre_close_sent = False
                self._publish_telemetry(current_temp, humidity, lux)
                return

        if current_temp <= (self.t_min + 1.0) or current_temp >= (self.t_max - 1.0):
            if not self.blind_pre_close_sent and self.current_hvac_state == "OFF":
                print("[ANTICIPATOR] Climate approaching thresholds. Issuing anticipatory blind drop.")
                self.mqtt_client.publish("home/blinds/command", json.dumps({"action": "CLOSE", "reason": "LIVING_ZONE_ANTICIPATION"}))
                self.blind_pre_close_sent = True

        next_state = "OFF"
        if current_temp < self.t_min:
            next_state = "HEATING"
        elif current_temp > self.t_max:
            next_state = "COOLING"

        if next_state != self.current_hvac_state and not self.is_resting:
            print(f"[AUTOMATION] Thermal transition initiated: {self.current_hvac_state} -> {next_state}")
            self._apply_physical_relay_state(next_state)
            if next_state == "OFF":
                self.blind_pre_close_sent = False

        self._publish_telemetry(current_temp, humidity, lux)

    def _publish_telemetry(self, temp: float, humidity: float, lux: float):
        payload = {
            "room_name": self.hostname,
            "hostname": self.hostname,
            "device_name": self.hostname,
            "temperature": temp,
            "humidity": humidity,
            "light_lux": round(lux, 1),
            "hvac_state": self.current_hvac_state,
            "hvac_in_rest": self.is_resting,
            "timestamp": time.time()
        }
        payload_json = json.dumps(payload)
        self.mqtt_client.publish("home/environment/living", payload_json, retain=True)
        self.mqtt_client.publish(
            f"home/environment/living/{self.hostname}",
            payload_json,
            retain=True,
        )
        print(
            f"[TELEMETRY] {self.hostname}: "
            f"{temp:.1f}°C, {humidity:.1f}% RH, {lux:.1f} lx"
        )


if __name__ == "__main__":
    daemon = LivingAreaHardwareController()
    daemon.start()
