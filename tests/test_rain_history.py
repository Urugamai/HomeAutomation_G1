import datetime

from libraries.rain_history import (
    RainHistoryStore, daily_series, hourly_series, monthly_series, totals,
)


def test_rain_history_accumulates_increments_and_persists(tmp_path):
    path = tmp_path / "home_rain_history.json"
    store = RainHistoryStore(path)
    t0 = datetime.datetime(2026, 11, 20, 10, 5)

    assert store.record(t0, 1.0) == 1.0
    assert store.record(t0 + datetime.timedelta(minutes=30), 1.0) == 0.0
    assert store.record(t0 + datetime.timedelta(minutes=70), 3.5) == 2.5
    # Gateway counter reset within the same day counts as new rain.
    assert store.record(t0 + datetime.timedelta(minutes=80), 0.4) == 0.4

    reloaded = RainHistoryStore(path)
    assert reloaded.data["daily"] == {"2026-11-20": 3.9}
    assert reloaded.data["hourly"] == {"2026-11-20T10": 1.0, "2026-11-20T11": 2.9}


def test_rain_history_new_day_and_series(tmp_path):
    store = RainHistoryStore(tmp_path / "rain.json")
    store.record(datetime.datetime(2026, 11, 19, 23, 50), 5.0)
    now = datetime.datetime(2026, 11, 20, 0, 10)
    store.record(now, 2.0)

    assert store.data["daily"] == {"2026-11-19": 5.0, "2026-11-20": 2.0}
    hours = hourly_series(store.data, now)
    assert len(hours) == 24
    assert hours[-1][1] == 2.0 and hours[-2][1] == 5.0
    days = daily_series(store.data, now, 7)
    assert [mm for _, mm in days][-2:] == [5.0, 2.0]
    months = monthly_series(store.data, now)
    assert len(months) == 12 and months[-1] == (datetime.date(2026, 11, 1), 7.0)
    assert totals(store.data, now) == {"day": 2.0, "week": 7.0, "month": 7.0, "year": 7.0}


def test_reload_picks_up_changes_written_by_another_process(tmp_path):
    path = tmp_path / "rain.json"
    writer = RainHistoryStore(path)
    reader = RainHistoryStore(path)
    writer.record(datetime.datetime(2026, 11, 20, 9, 0), 1.5)

    assert reader.reload() is True
    assert reader.data["daily"] == {"2026-11-20": 1.5}
