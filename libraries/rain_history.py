"""Rain accumulation kept on the NAS so every display can chart and total it.

The Ecowitt gateway reports a cumulative "rain today" counter. The ecowitt daemon
turns its increments into hourly and daily buckets (millimetres, local time) and
stores them in a small JSON file. The Android app parses the same file format.
"""
import datetime
import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)

HOURLY_RETENTION = datetime.timedelta(hours=48)
DAILY_RETENTION = datetime.timedelta(days=400)
HOUR_KEY = "%Y-%m-%dT%H"
DAY_KEY = "%Y-%m-%d"


class RainHistoryStore:
    STORAGE_PATH = Path("/mnt/WatsonHome/home_rain_history.json")

    def __init__(self, storage_path=None):
        self.storage_path = Path(storage_path or self.STORAGE_PATH)
        self.data = self._empty()
        self._warned = False
        self._mtime = None
        self.reload()

    @staticmethod
    def _empty():
        return {
            "version": 1,
            "last_daily_mm": None,
            "last_date": None,
            "hourly": {},
            "daily": {},
        }

    def reload(self):
        """Re-reads the file when it changed; returns True if data was replaced."""
        try:
            mtime = self.storage_path.stat().st_mtime
        except OSError:
            return False
        if mtime == self._mtime:
            return False
        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            data = self._empty()
            data["last_daily_mm"] = payload.get("last_daily_mm")
            data["last_date"] = payload.get("last_date")
            data["hourly"] = {
                str(k): float(v) for k, v in payload.get("hourly", {}).items()
            }
            data["daily"] = {
                str(k): float(v) for k, v in payload.get("daily", {}).items()
            }
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            LOGGER.warning("Unable to load rain history from %s: %s", self.storage_path, exc)
            return False
        self.data = data
        self._mtime = mtime
        return True

    def record(self, now, rain_today_mm):
        """Adds the rain that fell since the previous reading; returns the increment."""
        if rain_today_mm is None:
            return 0.0
        rain_today_mm = float(rain_today_mm)
        today = now.strftime(DAY_KEY)
        last = self.data["last_daily_mm"]
        if self.data["last_date"] == today and last is not None and rain_today_mm >= last:
            delta = rain_today_mm - last
        else:
            # New day, first reading, or the gateway counter was reset.
            delta = rain_today_mm
        delta = round(delta, 3)

        changed = delta > 0 or last != rain_today_mm or self.data["last_date"] != today
        if delta > 0:
            hour_key = now.strftime(HOUR_KEY)
            self.data["hourly"][hour_key] = round(
                self.data["hourly"].get(hour_key, 0.0) + delta, 3)
            self.data["daily"][today] = round(
                self.data["daily"].get(today, 0.0) + delta, 3)
        self.data["last_daily_mm"] = rain_today_mm
        self.data["last_date"] = today
        if changed:
            self._prune(now)
            self._write()
        return delta

    def _prune(self, now):
        hour_cutoff = (now - HOURLY_RETENTION).strftime(HOUR_KEY)
        day_cutoff = (now - DAILY_RETENTION).strftime(DAY_KEY)
        self.data["hourly"] = {
            k: v for k, v in self.data["hourly"].items() if k >= hour_cutoff}
        self.data["daily"] = {
            k: v for k, v in self.data["daily"].items() if k >= day_cutoff}

    def _write(self):
        if not self.storage_path.parent.is_dir():
            if not self._warned:
                LOGGER.warning("Rain history storage is unavailable: %s", self.storage_path.parent)
                self._warned = True
            return
        temporary_path = self.storage_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(self.data, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.storage_path)
            self._mtime = self.storage_path.stat().st_mtime
        except OSError as exc:
            LOGGER.warning("Unable to save rain history to %s: %s", self.storage_path, exc)
            try:
                temporary_path.unlink()
            except OSError:
                pass


def hourly_series(data, now, hours=24):
    """Oldest to newest [(hour_start, mm)] ending with the current hour."""
    end = now.replace(minute=0, second=0, microsecond=0)
    result = []
    for back in range(hours - 1, -1, -1):
        start = end - datetime.timedelta(hours=back)
        result.append((start, data["hourly"].get(start.strftime(HOUR_KEY), 0.0)))
    return result


def daily_series(data, now, days=7):
    """Oldest to newest [(date, mm)] ending today."""
    today = now.date()
    result = []
    for back in range(days - 1, -1, -1):
        day = today - datetime.timedelta(days=back)
        result.append((day, data["daily"].get(day.strftime(DAY_KEY), 0.0)))
    return result


def monthly_series(data, now, months=12):
    """Oldest to newest [(first_of_month, mm)] ending with the current month."""
    totals = {}
    for key, value in data["daily"].items():
        totals[key[:7]] = totals.get(key[:7], 0.0) + value
    year, month = now.year, now.month
    result = []
    for back in range(months - 1, -1, -1):
        index = year * 12 + (month - 1) - back
        y, m = divmod(index, 12)
        result.append((datetime.date(y, m + 1, 1), totals.get(f"{y:04d}-{m + 1:02d}", 0.0)))
    return result


def totals(data, now):
    """Rain totals in mm: today, rolling 7 days, calendar month and calendar year."""
    today = now.date()
    daily = data["daily"]
    week_start = today - datetime.timedelta(days=6)
    month_prefix = today.strftime("%Y-%m")
    year_prefix = today.strftime("%Y")
    result = {"day": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}
    for key, value in daily.items():
        if key == today.strftime(DAY_KEY):
            result["day"] += value
        if week_start.strftime(DAY_KEY) <= key <= today.strftime(DAY_KEY):
            result["week"] += value
        if key.startswith(month_prefix):
            result["month"] += value
        if key.startswith(year_prefix):
            result["year"] += value
    return result
