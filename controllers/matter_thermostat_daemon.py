"""Bridges HVAC actuator commands to a commissioned Matter thermostat."""

import asyncio
import configparser
import json
import sys
import uuid
from pathlib import Path

import aiohttp
import yaml

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from libraries.paho_compat import create_client

COMMAND_TOPIC = "home/hvac/matter/command"
STATUS_TOPIC = "home/hvac/matter/status"
THERMOSTAT_CLUSTER = 0x0201
FAN_CONTROL_CLUSTER = 0x0202
SYSTEM_MODE_ATTRIBUTE = 0x001C
HEATING_SETPOINT_ATTRIBUTE = 0x0012
COOLING_SETPOINT_ATTRIBUTE = 0x0011
FAN_MODE_ATTRIBUTE = 0x0000
SYSTEM_MODES = {"OFF": 0, "HEATING": 4, "COOLING": 3}


class MatterThermostatDaemon:
    CONFIG_PATH = project_root / "config" / "matter-thermostat.yml"

    def __init__(self):
        self.config = self._load_config()
        self.client = create_client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _load_config(self):
        with self.CONFIG_PATH.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
        if not isinstance(config, dict):
            raise RuntimeError("matter-thermostat.yml must contain a mapping")
        return config

    def start(self):
        broker = self._broker()
        self.client.connect(broker, 1883, keepalive=60)
        self.client.loop_forever()

    def _broker(self):
        config = configparser.ConfigParser()
        config.read(project_root / "config.ini")
        return config.get("MQTT", "broker", fallback="localhost")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe(COMMAND_TOPIC)
        self._publish_status("disabled" if not self.config.get("enabled") else "ready")

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            mode = str(payload["mode"]).upper()
            if mode not in {"OFF", "HEATING", "COOLING", "FAN"}:
                raise ValueError(f"Unsupported thermostat mode: {mode}")
            if not self.config.get("enabled"):
                raise RuntimeError("Matter thermostat integration is disabled")
            asyncio.run(self._apply_mode(mode))
            self._publish_status("commanded", mode=mode)
        except (KeyError, TypeError, ValueError, RuntimeError, aiohttp.ClientError) as error:
            self._publish_status("error", error=str(error))

    async def _apply_mode(self, mode):
        node_id = self.config.get("node-id")
        if not isinstance(node_id, int):
            raise RuntimeError("Set node-id after commissioning the thermostat")
        endpoint_id = int(self.config.get("endpoint-id", 1))
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.config["matter-server-url"]) as websocket:
                await websocket.receive_json()
                if mode == "FAN":
                    if not self.config.get("fan-control-enabled"):
                        raise RuntimeError("Thermostat fan control is not enabled")
                    await self._write_attribute(
                        websocket, node_id, endpoint_id, FAN_CONTROL_CLUSTER, FAN_MODE_ATTRIBUTE, 1
                    )
                    return
                await self._write_attribute(
                    websocket, node_id, endpoint_id, THERMOSTAT_CLUSTER,
                    SYSTEM_MODE_ATTRIBUTE, SYSTEM_MODES[mode],
                )
                if mode == "HEATING":
                    await self._write_attribute(
                        websocket, node_id, endpoint_id, THERMOSTAT_CLUSTER,
                        HEATING_SETPOINT_ATTRIBUTE,
                        round(float(self.config["active-heating-setpoint-c"]) * 100),
                    )
                elif mode == "COOLING":
                    await self._write_attribute(
                        websocket, node_id, endpoint_id, THERMOSTAT_CLUSTER,
                        COOLING_SETPOINT_ATTRIBUTE,
                        round(float(self.config["active-cooling-setpoint-c"]) * 100),
                    )

    async def _write_attribute(self, websocket, node_id, endpoint_id, cluster_id, attribute_id, value):
        message_id = uuid.uuid4().hex
        await websocket.send_json(
            {
                "message_id": message_id,
                "command": "write_attribute",
                "args": {
                    "node_id": node_id,
                    "attribute_path": f"{endpoint_id}/{cluster_id}/{attribute_id}",
                    "value": value,
                },
            }
        )
        while response := await websocket.receive_json():
            if response.get("message_id") == message_id:
                if "error_code" in response:
                    raise RuntimeError(response.get("details") or "Matter attribute write failed")
                return

    def _publish_status(self, state, **details):
        self.client.publish(STATUS_TOPIC, json.dumps({"state": state, **details}), retain=True)


if __name__ == "__main__":
    MatterThermostatDaemon().start()
