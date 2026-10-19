import json

from libraries.solar import sun_position

QUEUE_TOPIC = "home/cbus/queued-command"
DEFAULT_SETTINGS = {
    "main-address": 35,
    "bedrooms-address": 42,
    "day-start-hour": 9,
    "main-reduce-hour": 22,
    "main-reduced-percent": 50,
}


def desired_levels(local_now, sun_elevation, hvac_running, settings=None):
    """Return (main_percent, bedrooms_percent).

    By day the bedrooms are closed so all airflow goes to the main house. At night they
    reopen, and if HVAC is still running late the main valve is reduced to push air to them.
    The main valve is never fully closed because that makes the duct noisy.
    """
    config = {**DEFAULT_SETTINGS, **(settings or {})}
    hour = local_now.hour + local_now.minute / 60.0
    if hour >= config["day-start-hour"] and sun_elevation > 0:
        return 100, 0
    late = hour >= config["main-reduce-hour"] or hour < config["day-start-hour"]
    if hvac_running and late:
        return config["main-reduced-percent"], 100
    return 100, 100


class DuctValveController:
    """Drives the two C-Bus duct valves, keeping at least one fully open during changes."""

    def __init__(self, client_getter, location, settings=None):
        self._client_getter = client_getter
        self.location = location
        self.settings = {**DEFAULT_SETTINGS, **(settings or {})}
        self.levels = None

    def update(self, local_now, hvac_running):
        client = self._client_getter()
        if client is None:
            return
        if self.location is not None:
            _, elevation = sun_position(
                self.location["latitude"], self.location["longitude"], local_now
            )
        else:
            elevation = 1.0 if 6 <= local_now.hour < 18 else -1.0
        target = desired_levels(local_now, elevation, hvac_running, self.settings)
        if target == self.levels:
            return
        current = self.levels if self.levels is not None else (None, None)
        # Open both before closing either, so airflow always has a path.
        if any(level != 100 for level in target) and current != (100, 100):
            for address, now_level in zip(self._addresses(), current):
                if now_level != 100:
                    self._publish(client, address, 100, "duct valve change-over: open both")
            current = (100, 100)
        for address, old, new in zip(self._addresses(), current, target):
            if old != new:
                self._publish(client, address, new, "duct valve schedule")
        self.levels = target

    def _addresses(self):
        return (self.settings["main-address"], self.settings["bedrooms-address"])

    @staticmethod
    def _publish(client, address, percent, reason):
        level = round(255 * percent / 100)
        payload = {"state": "ON" if level else "OFF", "brightness": level, "transition": 0}
        client.publish(
            QUEUE_TOPIC,
            json.dumps(
                {
                    "topic": f"homeassistant/light/cbus_{address}/set",
                    "payload": payload,
                    "reason": reason,
                }
            ),
            qos=1,
            retain=False,
        )
        print(f"[DUCT VALVE] address={address} -> {percent}% ({reason})")
