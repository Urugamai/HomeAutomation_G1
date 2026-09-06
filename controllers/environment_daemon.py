import sys
import time
import json
import configparser
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    import smbus2
    import bme280

    IS_RASPI = True
except ImportError:
    GPIO = None
    smbus2 = None
    bme280 = None
    IS_RASPI = False

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

        self.t_min = 20.0
        self.t_max = 24.0

        self.current_hvac_state = "OFF"
        self.last_state_change_time = time.time()
        self.is_resting = False
        self.rest_start_time = 0.0
        self.blind_pre_close_sent = False

        self.bus = None
        self.discovered_bme_addr = None
        self.bme_calibration_params = None
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
                    self.bus.read_byte(addr)
                    self.discovered_bme_addr = addr
                    self.bme_calibration_params = bme280.load_calibration_data(self.bus, addr)
                    print(f"[I2C SUCCESS] Auto-detected and calibrated Bosch BME at: {hex(addr)}")
                    break
                except Exception:
                    continue

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
            if self.discovered_bme_addr and self.bme_calibration_params:
                bme_data = bme280.sample(self.bus, self.discovered_bme_addr, self.bme_calibration_params)
                temp_c = round(bme_data.temperature, 1)
                humidity = round(bme_data.humidity, 1)

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
            "room_name": "Living Area",
            "temperature": temp,
            "humidity": humidity,
            "light_lux": round(lux, 1),
            "hvac_state": self.current_hvac_state,
            "hvac_in_rest": self.is_resting,
            "timestamp": time.time()
        }
        self.mqtt_client.publish("home/environment/living", json.dumps(payload), retain=True)


if __name__ == "__main__":
    daemon = LivingAreaHardwareController()
    daemon.start()
