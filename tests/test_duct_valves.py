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


def test_both_fully_open_overnight_2100_to_0900():
    for hour in list(range(21, 24)) + list(range(0, 9)):
        for sun in (10, -10):
            for running in (True, False):
                assert desired_levels(at(hour), sun, running) == (100, 100)
    assert desired_levels(at(20, 59), 5, True) == (100, 0)
    assert desired_levels(at(9), 5, True) == (100, 0)


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
            assert main == 100


def test_open_fractions_always_sum_to_at_least_one():
    from libraries.duct_valves import _enforce_min_total

    assert _enforce_min_total(50, 0) == (100, 0)
    assert _enforce_min_total(30, 40) == (60, 40)
    assert _enforce_min_total(-5, 200) == (0, 100)
    for hour in range(24):
        for sun in (10, -10):
            for running in (True, False):
                assert sum(desired_levels(at(hour), sun, running)) >= 100

