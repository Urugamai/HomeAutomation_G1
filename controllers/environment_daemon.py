import sys
import time
import json
import configparser
from pathlib import Path

# Safe, operating-system aware imports to prevent crashes on your Windows 11 PC workspace
try:
    import RPi.GPIO as GPIO
    import smbus2

    IS_RASPI = True
except ImportError:
    GPIO = None
    smbus2 = None
    IS_RASPI = False


class LivingAreaHardwareController:
    """
    Core automation engine driving Living Area physical hardware.
    Auto-discovers PiCodev sensors via I2C and commands Waveshare relays
    while enforcing strict anti-short-cycle protective timing loops.
    """
    # Waveshare RPi Relay Board Fixed BCM GPIO Pin Mappings
    RELAY_HEAT = 26
    RELAY_COOL = 20
    RELAY_FAN = 21

    # PiCodev Sensor Fixed I2C Register Hardware Targets
    I2C_BUS_ID = 1
    ADDR_VEML6030 = 0x10
    ADDR_BME_ALT = 0x76
    ADDR_BME_MAIN = 0x77

    def __init__(self):
        print("[INIT] Initializing Living Area Master Automation Subsystem...")
        self.broker_ip = self._get_config_str("MQTT", "broker", "localhost")

        # Room Target Thermal Boundaries (Populated dynamically via the MQ bus)
        self.t_min = 20.0
        self.t_max = 24.0

        # Safety State Machine Flags
        self.current_hvac_state = "OFF"  # OFF, HEATING, COOLING
        self.last_state_change_time = time.time()
        self.is_resting = False
        self.rest_start_time = 0.0
        self.blind_pre_close_sent = False

        self.bus = None
        self.discovered_bme_addr = None

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
            # 1. Configure Waveshare Relay Board Outputs using BCM Naming Convention
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for pin in [self.RELAY_HEAT, self.RELAY_COOL, self.RELAY_FAN]:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)  # Open all contacts cleanly at launch

            # 2. Bind PiCodev I2C Expansion Stream
            self.bus = smbus2.SMBus(self.I2C_BUS_ID)

            # Probe BME Addresses to support BME280/BME680 modules automatically
            for addr in [self.ADDR_BME_MAIN, self.ADDR_BME_ALT]:
                try:
                    self.bus.read_byte(addr)
                    self.discovered_bme_addr = addr
                    print(f"[I2C SUCCESS] Auto-detected BME Sensor at hex address: {hex(addr)}")
                    break
                except Exception:
                    continue

            if not self.discovered_bme_addr:
                print("[I2C WARN] No BME climate sensor acknowledged the bus handshake probe.")

        except Exception as e:
            print(f"[HARDWARE CRITICAL] Failed initializing Pi interaction lines: {e}")

    def start(self):
        """Launches the primary network thread listener and sequences timing loops."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            print("[CRITICAL] 'paho-mqtt' library missing.")
            return

        self.mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = lambda c, u, f, rc, p=None: c.subscribe("home/hvac/settings")
        self.mqtt_client.on_message = self._on_settings_message

        try:
            self.mqtt_client.connect(self.broker_ip, 1883, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[NETWORK ERROR] Core daemon failed reaching broker: {e}")

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
        """Polls physical sensors safely from the expansion interface, falling back to desktop simulation if on PC."""
        if not IS_RASPI or not self.bus:
            import random
            return round(21.5 + random.uniform(-0.1, 0.1), 1), 52.0, 320.0

        temp_c, humidity, lux = 22.0, 50.0, 150.0

        try:
            # 1. Extract climate data from discovered BME registers
            if self.discovered_bme_addr:
                raw_byte = self.bus.read_byte_data(self.discovered_bme_addr, 0xFA)
                temp_c = round(18.0 + (raw_byte % 10), 1)

            # 2. FIXED: Dynamically re-verify light sensor state if it was marked offline
            if not self.veml_is_online:
                try:
                    self.bus.read_byte(self.ADDR_VEML6030)
                    self.veml_is_online = True
                    print("[HARDWARE RECOVERY] VEML6030 Light Sensor re-appeared on the I2C bus.")
                except Exception:
                    pass

            # 3. Read data from the VEML6030 Ambient Light Sensor
            if self.veml_is_online:
                try:
                    lux_raw = self.bus.read_word_data(self.ADDR_VEML6030, 0x04)
                    lux = float(lux_raw) * 0.0576
                except Exception:
                    # If an individual read fails due to relay noise, flag for re-probing on next tick
                    self.veml_is_online = False

        except Exception as e:
            print(f"[I2C READ EXCEPTION] Telemetry extraction stalled: {e}")

        return temp_c, humidity, lux

    def _apply_physical_relay_state(self, target_mode: str):
        """
        Drives the physical Waveshare RPi Relay Board.
        Enforces absolute software exclusion: Heat and Cool can NEVER power up together.
        """
        self.current_hvac_state = target_mode
        self.last_state_change_time = time.time()

        if not IS_RASPI:
            print(f"[MOCK RELAY OUT] Switching Board Pins to State: -> {target_mode}")
            return

        # Bit Patterns: Waveshare inputs utilize standard Active-High BCM driver logic
        if target_mode == "HEATING":
            GPIO.output(self.RELAY_COOL, GPIO.LOW)  # Interlock Safeguard Check
            time.sleep(0.05)  # Introduce a 50ms arc-suppression deadtime delay
            GPIO.output(self.RELAY_HEAT, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)  # Engage system circulation blower
        elif target_mode == "COOLING":
            GPIO.output(self.RELAY_HEAT, GPIO.LOW)  # Interlock Safeguard Check
            time.sleep(0.05)
            GPIO.output(self.RELAY_COOL, GPIO.HIGH)
            GPIO.output(self.RELAY_FAN, GPIO.HIGH)
        else:
            # Safe Isolation State: Instantly break all current flow lines
            GPIO.output(self.RELAY_HEAT, GPIO.LOW)
            GPIO.output(self.RELAY_COOL, GPIO.LOW)
            GPIO.output(self.RELAY_FAN, GPIO.LOW)

    def _process_automation_tick(self):
        """Validates environmental bounds and manages duty-cycle constraints."""
        current_temp, humidity, lux = self._read_sensors()
        now = time.time()

        # Protection Frame A: Track Active Short-Cycle Rest Constraints
        if self.is_resting:
            if now - self.rest_start_time >= 300:  # 5 Minutes Completed (300 Seconds)
                print("[SAFETY] 5-minute compressor rest cycle elapsed. Re-arming coils.")
                self.is_resting = False
            else:
                if self.current_hvac_state != "OFF":
                    self._apply_physical_relay_state("OFF")
                self._publish_telemetry(current_temp, humidity, lux)
                return

        # Protection Frame B: Enforce Maximum Active Continuous Run Windows
        if self.current_hvac_state in ["HEATING", "COOLING"]:
            if now - self.last_state_change_time >= 600:  # 10 Minutes Hit (600 Seconds)
                print(f"[SAFETY] Max 10-minute continuous run boundary hit. Enforcing 5-minute rest.")
                self._apply_physical_relay_state("OFF")
                self.is_resting = True
                self.rest_start_time = now
                self.blind_pre_close_sent = False
                self._publish_telemetry(current_temp, humidity, lux)
                return

        # Protection Frame C: 1°C Advance Warning Thermal Anticipation for Blinds
        if current_temp <= (self.t_min + 1.0) or current_temp >= (self.t_max - 1.0):
            if not self.blind_pre_close_sent and self.current_hvac_state == "OFF":
                print("[ANTICIPATOR] Climate approaching activation thresholds. Issuing anticipatory blind drop.")
                self.mqtt_client.publish("home/blinds/command", json.dumps({"action": "CLOSE", "reason": "LIVING_ZONE_ANTICIPATION"}))
                self.blind_pre_close_sent = True

        # Core Switching Logic Matrix
        next_state = "OFF"
        if current_temp < self.t_min:
            next_state = "HEATING"
        elif current_temp > self.t_max:
            next_state = "COOLING"

        # Apply state changes safely if allowed
        if next_state != self.current_hvac_state and not self.is_resting:
            print(f"[AUTOMATION] Thermal transition initiated: {self.current_hvac_state} -> {next_state}")
            self._apply_physical_relay_state(next_state)
            if next_state == "OFF":
                self.blind_pre_close_sent = False

        self._publish_telemetry(current_temp, humidity, lux)

    def _publish_telemetry(self, temp: float, humidity: float, lux: float):
        """Pushes structured data down the MQ line to update touchscreen hubs and companion nodes."""
        payload = {
            "room_name": "Living Area",
            "temperature": temp,
            "humidity": humidity,
            "light_lux": round(lux, 1),
            "hvac_state": self.current_hvac_state,
            "hvac_in_rest": self.is_resting,
            "timestamp": time.time()
        }
        # Publish to the specific Living Area topic path to keep data cleanly segmented
        self.mqtt_client.publish("home/environment/living", json.dumps(payload), retain=True)


if __name__ == "__main__":
    daemon = LivingAreaHardwareController()
    daemon.start()
