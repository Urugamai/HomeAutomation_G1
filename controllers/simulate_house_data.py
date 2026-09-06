import sys
import time
import json
import random

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("[CRITICAL] 'paho-mqtt' library missing from active environment.")
    sys.exit(1)

from libraries.paho_compat import create_client


def generate_mock_telemetry_stream(broker_ip="192.168.2.2"):
    """
    Independent test script to feed various real-world weather metrics
    and energy fluctuations to your broker for desktop layout verification.
    """
    print(f"[TEST FEED] Launching network data injector targeting {broker_ip}...")

    client = create_client()

    try:
        client.connect(broker_ip, 1883, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[CONNECTION FAILURE] Could not reach broker: {e}")
        return

    # A collection of diverse weather scenarios to test text layouts
    weather_scenarios = [
        {
            "desc": "Standard winter morning sequence (Today's min has passed)",
            "today": {"min": None, "max": 14.0, "rain": 70, "summary": "Showers easing around midday. Wind westerly."},
            "tomorrow": {"min": 8.0, "max": 15.0, "rain": 20, "summary": "Mostly sunny. Light morning frost patches."}
        },
        {
            "desc": "Extreme weather pattern sequence (Checking long text lines)",
            "today": {"min": 11.0, "max": 23.0, "rain": 90, "summary": "Severe thunderstorm warning. Damaging wind gusts developing."},
            "tomorrow": {"min": 9.0, "max": 14.0, "rain": 65, "summary": "Possible hail. Cold front sweeping across coastal strips."}
        },
        {
            "desc": "Perfect baseline spring sequence",
            "today": {"min": None, "max": 19.5, "rain": 5, "summary": "Clear and sunny day. Calm bay breezes."},
            "tomorrow": {"min": 10.5, "max": 21.0, "rain": 10, "summary": "Beautiful clear skies continuing throughout."}
        }
    ]

    scenario_index = 0
    print("[RUNNING] Pushing test packets to your broker topics. Press Ctrl+C to halt.")

    try:
        while True:
            scenario = weather_scenarios[scenario_index]
            print(f"\n[INJECTING] Profile: {scenario['desc']}")

            # 1. Structure and publish the multi-day forecast array package
            forecast_packet = {
                "station_region": "Melbourne/Altona Metro Area",
                "last_updated_tick": time.time(),
                "forecast_set": [
                    {
                        "day_index": 0,
                        "expected_min": scenario["today"]["min"],
                        "expected_max": scenario["today"]["max"],
                        "rain_probability": scenario["today"]["rain"],
                        "summary": scenario["today"]["summary"]
                    },
                    {
                        "day_index": 1,
                        "expected_min": scenario["tomorrow"]["min"],
                        "expected_max": scenario["tomorrow"]["max"],
                        "rain_probability": scenario["tomorrow"]["rain"],
                        "summary": scenario["tomorrow"]["summary"]
                    }
                ]
            }
            client.publish("home/environment/forecast", json.dumps(forecast_packet), retain=True)

            # 2. Structure and publish real-time internal / external climate tracking packets
            climate_packet = {
                "temperature": round(random.uniform(20.5, 22.5), 1),
                "hvac_state": random.choice(["OFF", "HEATING", "COOLING"]),
                "hvac_in_rest": False
            }
            client.publish("home/environment/inside", json.dumps(climate_packet))

            # 3. Structure and publish SigenStor asset data flow load profiles
            sigen_packet = {
                "battery_soc": random.randint(65, 95),
                "battery_flow": random.randint(-2200, 3200),
                "grid_flow": random.randint(-1800, 4200),
                "solar_kwh_today": round(random.uniform(12.5, 24.0), 1)
            }
            client.publish("home/power/sigen", json.dumps(sigen_packet))

            print("[SUCCESS] Telemetry packets broadcasted successfully.")

            # Rotate down to the next text scenario frame configuration profile
            scenario_index = (scenario_index + 1) % len(weather_scenarios)

            # Hold profile configuration variables active for 8 seconds before shifting loops
            time.sleep(8.0)

    except KeyboardInterrupt:
        print("\n[STOPPED] Terminating mock dataset broadcast loop.")
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    # Pull custom broker destination target configurations from command lines if supplied
    target_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.2.2"
    generate_mock_telemetry_stream(broker_ip=target_ip)
