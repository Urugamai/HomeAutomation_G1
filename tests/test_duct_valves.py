import datetime
import json

from libraries.duct_valves import DuctValveController, desired_levels

TZ = datetime.timezone(datetime.timedelta(hours=11))
LOCATION = {"latitude": -37.868, "longitude": 144.832}


def at(hour, minute=0):
    return datetime.datetime(2026, 12, 21, hour, minute, tzinfo=TZ)


class Recorder:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, **kwargs):
        message = json.loads(payload)
        address = int(message["topic"].split("cbus_")[1].split("/")[0])
        self.sent.append((address, message["payload"]["brightness"]))


def test_bedrooms_closed_by_day_open_after_sunset():
    assert desired_levels(at(12), 60, False) == (100, 0)
    assert desired_levels(at(7), 20, False) == (100, 100)
    assert desired_levels(at(21), -5, True) == (100, 100)


def test_main_reduces_to_half_after_2200_only_while_running():
    assert desired_levels(at(22, 30), -30, True) == (50, 100)
    assert desired_levels(at(22, 30), -30, False) == (100, 100)
    assert desired_levels(at(23), -30, True)[0] > 0


def test_startup_opens_both_then_closes_bedrooms():
    client = Recorder()
    valves = DuctValveController(lambda: client, LOCATION)

    valves.update(at(13), False)

    assert client.sent == [(35, 255), (42, 255), (42, 0)]


def test_changeover_opens_both_before_closing_one():
    client = Recorder()
    valves = DuctValveController(lambda: client, LOCATION)
    valves.levels = (50, 100)

    valves.update(at(13), True)

    assert client.sent == [(35, 255), (42, 0)]


def test_no_commands_when_levels_unchanged():
    client = Recorder()
    valves = DuctValveController(lambda: client, LOCATION)
    valves.update(at(13), False)
    client.sent.clear()

    valves.update(at(14), False)

    assert client.sent == []


def test_main_valve_is_never_fully_closed():
    for hour in range(24):
        for running in (True, False):
            main, bedrooms = desired_levels(at(hour), 10 if 9 <= hour < 19 else -10, running)
            assert main > 0 or bedrooms > 0
            assert main >= 50


def test_open_fractions_always_sum_to_at_least_one():
    from libraries.duct_valves import _enforce_min_total

    assert _enforce_min_total(50, 0) == (100, 0)
    assert _enforce_min_total(30, 40) == (60, 40)
    assert _enforce_min_total(-5, 200) == (0, 100)
    for hour in range(24):
        for sun in (10, -10):
            for running in (True, False):
                for pct in (0, 25, 50, 100):
                    levels = desired_levels(at(hour), sun, running, {'main-reduced-percent': pct})
                    assert sum(levels) >= 100

