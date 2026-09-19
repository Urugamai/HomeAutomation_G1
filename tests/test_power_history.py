import datetime
import json

from ui.adaptive_ui import EnvironmentSourcesPage, PowerHistoryStore
from ui.battery_indicator import (
    CHARGING_COLOR,
    DRAINING_COLOR,
    LOW_SOC_COLOR,
    battery_flow_color,
    battery_soc_fill_color,
)


def test_load_keeps_only_rolling_24_hour_window(tmp_path):
    now = datetime.datetime.now().replace(microsecond=0)
    storage_path = tmp_path / "home_power_history.json"
    storage_path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "timestamp": (now - datetime.timedelta(hours=24, seconds=1)).isoformat(),
                        "power_kw": 1.0,
                    },
                    {
                        "timestamp": (now - datetime.timedelta(hours=23)).isoformat(),
                        "power_kw": 2.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    history = PowerHistoryStore(storage_path)

    assert history.samples == [(now - datetime.timedelta(hours=23), 2.0, None)]


def test_add_sample_discards_samples_older_than_24_hours(tmp_path):
    history = PowerHistoryStore(tmp_path / "home_power_history.json")
    now = datetime.datetime.now().replace(microsecond=0)
    history.samples = [
        (now - datetime.timedelta(hours=24, seconds=1), 1.0, None),
        (now - datetime.timedelta(hours=23), 2.0, None),
    ]

    history.add_sample(now, 3.0, 1.5)

    assert history.samples == [
        (now - datetime.timedelta(hours=23), 2.0, None),
        (now, 3.0, 1.5),
    ]


def test_add_sample_persists_solar_generation(tmp_path):
    storage_path = tmp_path / "home_power_history.json"
    history = PowerHistoryStore(storage_path)
    now = datetime.datetime.now().replace(microsecond=0)

    history.add_sample(now, 2.0, 1.25)

    assert json.loads(storage_path.read_text(encoding="utf-8")) == {
        "samples": [
            {
                "timestamp": now.isoformat(),
                "power_kw": 2.0,
                "solar_kw": 1.25,
            }
        ]
    }
    assert PowerHistoryStore(storage_path).samples == [(now, 2.0, 1.25)]


def test_battery_soc_color_reflects_flow_and_preserves_deadband_color():
    assert battery_flow_color(-0.101) == DRAINING_COLOR
    assert battery_flow_color(0.101) == CHARGING_COLOR
    assert battery_flow_color(0.1, DRAINING_COLOR) == DRAINING_COLOR


def test_low_battery_soc_overrides_battery_flow_color():
    assert battery_soc_fill_color(9.9, CHARGING_COLOR) == LOW_SOC_COLOR
    assert battery_soc_fill_color(100, CHARGING_COLOR) == CHARGING_COLOR


def test_environment_timestamp_is_formatted_as_local_datetime():
    source = {"timestamp": 1_726_000_000}

    row = EnvironmentSourcesPage._source_row("Living", source)

    assert row[-1] == datetime.datetime.fromtimestamp(1_726_000_000).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert row[4] == "--"


def test_environment_light_lux_is_displayed_without_conversion():
    row = EnvironmentSourcesPage._source_row("living", {"light_lux": 320})

    assert row[5] == "320.0 lx"
