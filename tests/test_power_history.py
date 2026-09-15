import datetime
import json

from ui.adaptive_ui import PowerHistoryStore


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

    assert history.samples == [(now - datetime.timedelta(hours=23), 2.0)]


def test_add_sample_discards_samples_older_than_24_hours(tmp_path):
    history = PowerHistoryStore(tmp_path / "home_power_history.json")
    now = datetime.datetime.now().replace(microsecond=0)
    history.samples = [
        (now - datetime.timedelta(hours=24, seconds=1), 1.0),
        (now - datetime.timedelta(hours=23), 2.0),
    ]

    history.add_sample(now, 3.0)

    assert history.samples == [
        (now - datetime.timedelta(hours=23), 2.0),
        (now, 3.0),
    ]
