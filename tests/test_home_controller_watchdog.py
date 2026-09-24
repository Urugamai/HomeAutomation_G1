import os

from controllers import home_controller_watchdog


def test_heartbeat_is_fresh_only_within_the_watchdog_window(tmp_path):
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    now = 1_000_000.0
    os.utime(heartbeat, (now - 599, now - 599))

    assert home_controller_watchdog.heartbeat_is_fresh(heartbeat, now=now)

    os.utime(heartbeat, (now - 601, now - 601))

    assert not home_controller_watchdog.heartbeat_is_fresh(heartbeat, now=now)


def test_missing_heartbeat_is_unhealthy(tmp_path):
    assert not home_controller_watchdog.heartbeat_is_fresh(tmp_path / "heartbeat")
