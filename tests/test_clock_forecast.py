from ui.Clock.Clock import ClockWindow


def test_clock_forecast_titles_use_the_forecast_date():
    assert ClockWindow._forecast_title(
        {"day_index": 0, "utc_timestamp": "2026-10-11T00:00:00Z"}
    ) == "2026-10-11"
    assert ClockWindow._forecast_title(
        {"day_index": 1, "utc_timestamp": "2026-10-12T00:00:00Z"}
    ) == "2026-10-12"
