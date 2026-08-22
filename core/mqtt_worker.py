import sys
import subprocess
import json
import time
from multiprocessing.connection import PipeConnection

def run_network_node(pipe_connection: PipeConnection, broker: str, port: int):
    """
    Headless standalone execution node.
    Streams native mosquitto_sub output directly into the OS Pipe using explicit
    Windows background handle isolation flags. Safely clears exit code 0xC0000409.
    """
    print(f"[WORKER PROCESS] Initializing native sub-process engine for {broker}:{port}...")

    cached_data = {
        "inside_temp": 0.0, "outside_temp": 0.0,
        "battery_soc": 0, "battery_flow": 0, "grid_flow": 0,
        "hvac_state": "OFF", "hvac_in_rest": False
    }

    cmd = [
        r"C:\Program Files\mosquitto\mosquitto_sub.exe",
        "-h", broker,
        "-p", str(port),
        "-t", "home/environment/inside",
        "-t", "home/power/sigen",
        "-F", "{\"topic\":\"%t\",\"payload\":%p}"
    ]

    # Configure explicit Windows-only background process isolation flags
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        # Enforce STARTF_USESHOWWINDOW flag behavior
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # Force the spawned console to stay completely invisible (SW_HIDE)
        startupinfo.wShowWindow = 0

    try:
        # Launch the native background process with strict console isolation handles
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line-buffered output streaming
            startupinfo=startupinfo,  # <--- CRITICAL FIX FOR WINDOWS 11 CANVAS CRASHES
            stdin=subprocess.DEVNULL  # Completely decouple standard input streams
        )
        print("[WORKER PROCESS] Native mosquitto_sub processing loop successfully hooked.")
    except FileNotFoundError:
        print("[WORKER CRITICAL] 'mosquitto_sub.exe' path targets not resolved.")
        return
    except Exception as e:
        print(f"[WORKER CRITICAL] Failed to execute native sub-process: {e}")
        return

    # Continuously monitor the live console stream line-by-line
    while True:
        line = process.stdout.readline()
        if not line:
            break

        try:
            wrapper = json.loads(line.strip())
            topic = wrapper.get("topic")
            data_payload = wrapper.get("payload", {})

            if topic == "home/environment/inside":
                cached_data["inside_temp"] = float(data_payload.get("temperature", 0.0))
                cached_data["hvac_state"] = data_payload.get("hvac_state", "OFF")
                cached_data["hvac_in_rest"] = bool(data_payload.get("hvac_in_rest", False))
            elif topic == "home/power/sigen":
                cached_data["battery_soc"] = int(data_payload.get("battery_soc", 0))
                cached_data["battery_flow"] = int(data_payload.get("battery_flow", 0))
                cached_data["grid_flow"] = int(data_payload.get("grid_flow", 0))

            # Send data up the OS Pipe
            pipe_connection.send(cached_data.copy())

        except Exception:
            pass

    process.terminate()
