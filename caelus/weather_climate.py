"""Cache ERA5 same-calendar-date weather statistics independently of forecasts."""

import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import requests

from caelus import __version__
from caelus.settings import AppSettings

logger = logging.getLogger(__name__)
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START = date(1991, 1, 1)
CACHE_FORMAT = 3


def latest_history_date() -> date:
    """Allow five days for ERA5 publication."""
    return datetime.now(timezone.utc).date() - timedelta(days=5)


VARIABLES = {
    "temperature_2m_mean": "temperature_c",
    "relative_humidity_2m_mean": "humidity_pct",
    "wind_speed_10m_mean": "wind_kmh",
    "rain_sum": "rain_mm",
}
EXTREMES = {
    f"{variable.removesuffix('_mean')}_{stat}": f"{field}_{stat}"
    for variable, field in VARIABLES.items() if variable.endswith('_mean')
    for stat in ("min", "max")
}
ALL_VARIABLES = {**VARIABLES, **EXTREMES}
DAY_KEYS = {(date(2000, 1, 1) + timedelta(days=i)).strftime("%m-%d") for i in range(366)}


def _valid_value(key: str, value) -> bool:
    key = key.removesuffix("_min").removesuffix("_max")
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value)
            and (key == "temperature_c" or value >= 0)
            and (key != "humidity_pct" or value <= 100))


def summarize_weather_history(payload: dict, end: date) -> dict:
    """Summarize historical extrema and daily means by station-local calendar date."""
    daily = payload.get("daily") or {}
    count = (end - START).days + 1
    if any(len(daily.get(key, [])) != count for key in ("time", *ALL_VARIABLES)):
        raise ValueError("Weather history does not cover the complete baseline")
    totals, samples, extrema = {}, {}, {}
    for index in range(count):
        day = START + timedelta(days=index)
        if daily["time"][index] != day.isoformat():
            raise ValueError("Weather history has missing or duplicate dates")
        key = day.strftime("%m-%d")
        sums = totals.setdefault(key, dict.fromkeys(VARIABLES.values(), 0.0))
        for variable, field in VARIABLES.items():
            value = daily[variable][index]
            if not _valid_value(field, value):
                raise ValueError(f"Weather history contains invalid {variable}")
            sums[field] += value
        bounds = extrema.setdefault(key, {})
        for variable, field in {**EXTREMES, "rain_sum": "rain_mm"}.items():
            value = daily[variable][index]
            if not _valid_value(field, value):
                raise ValueError(f"Weather history contains invalid {variable}")
            for stat in ("min", "max") if field == "rain_mm" else (field.rsplit("_", 1)[1],):
                name = f"{field}_{stat}" if field == "rain_mm" else field
                reducer = min if stat == "min" else max
                # Keep the earliest year when an extreme occurs more than once.
                if name not in bounds or reducer(bounds[name], value) != bounds[name]:
                    bounds[name] = value
                    bounds[f"{name}_year"] = day.year
        samples[key] = samples.get(key, 0) + 1
    return {key: {**{field: round(value / samples[key], 3) for field, value in sums.items()},
                  **extrema[key], "samples": samples[key]} for key, sums in totals.items()}


class WeatherClimateService:
    """Load a compact persistent climatology without delaying dashboard requests."""

    daily_variables = ",".join(ALL_VARIABLES)
    expected_units = {"temperature_2m_mean": "°C", "relative_humidity_2m_mean": "%",
                      "wind_speed_10m_mean": "km/h", "rain_sum": "mm"}

    for variable in EXTREMES:
        expected_units[variable] = expected_units[variable.rsplit("_", 1)[0] + "_mean"]

    def __init__(self, cache_path: Path, session=requests):
        self.cache_path = Path(cache_path)
        self.session = session
        self.payload = {"status": "warming"}
        self.location = None
        self.task = None
        self.next_check = 0.0

    def snapshot(self, settings: AppSettings, *, now: datetime | None = None) -> dict:
        """Return today's station-local historical statistics, scheduling background refreshes."""
        location = {"latitude": round(settings.latitude, 4),
                    "longitude": round(settings.longitude, 4), "timezone": settings.timezone}
        if location != self.location:
            self.location = location
            self.payload = {"status": "warming"}
            self.next_check = 0.0
        if settings.latitude == 0 and settings.longitude == 0:
            return {"status": "unavailable", "reason": "Set a station location"}
        if (self.task is None or self.task.done()) and time.monotonic() >= self.next_check:
            self.task = asyncio.create_task(self._load(dict(location)), name="WeatherClimate")
        result = {key: value for key, value in self.payload.items() if key != "calendar_averages"}
        if result.get("status") == "ready":
            current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(location["timezone"]))
            result["date"] = current.date().isoformat()
            result["averages"] = dict(self.payload["calendar_averages"][current.strftime("%m-%d")])
        return result

    async def close(self) -> None:
        """Cancel background retrieval when the application stops."""
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def _read_cache(self, location: dict) -> dict | None:
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if (cached.get("cache_format") != CACHE_FORMAT or cached.get("location") != location
                    or cached.get("status") != "ready" or cached.get("start_date") != START.isoformat()):
                return None
            end = date.fromisoformat(cached["end_date"])
            requested = date.fromisoformat(cached["requested_end_date"])
            if not START <= end <= requested <= latest_history_date():
                return None
            averages = cached["calendar_averages"]
            samples = Counter((START + timedelta(days=i)).strftime("%m-%d")
                              for i in range((end - START).days + 1))
            if set(averages) != DAY_KEYS or any(
                row.get("samples") != samples[key]
                or any(not _valid_value(field, row.get(field)) for field in (*ALL_VARIABLES.values(), "rain_mm_min", "rain_mm_max"))
                or any(
                    type(row.get(f"{field}_{stat}_year")) is not int
                    or not START <= date.fromisoformat(f"{row[f'{field}_{stat}_year']}-{key}") <= end
                    for field in VARIABLES.values() for stat in ("min", "max")
                )
                for key, row in averages.items()
            ):
                return None
            return cached
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Historical weather cache could not be read: %s", exc)
            return None

    def _fetch(self, location: dict, end: date) -> dict:
        response = self.session.get(ARCHIVE_URL, params={
            **location, "start_date": START.isoformat(), "end_date": end.isoformat(),
            "daily": self.daily_variables, "models": "era5", "precipitation_unit": "mm",
            "temperature_unit": "celsius", "wind_speed_unit": "kmh",
        }, headers={"User-Agent": f"Caelus/{__version__} local-weather-dashboard"}, timeout=45)
        response.raise_for_status()
        data = response.json()
        if any(data.get("daily_units", {}).get(key) != unit for key, unit in self.expected_units.items()):
            raise ValueError("Historical weather has unexpected units")
        daily = data.get("daily") or {}
        keys = ("time", *ALL_VARIABLES)
        count = (end - START).days + 1
        if any(len(daily.get(key, [])) != count for key in keys):
            raise ValueError("Historical weather does not cover the requested dates")
        available = count
        while available and any(daily[key][available - 1] is None for key in ALL_VARIABLES):
            available -= 1
        if count - available > 7:
            raise ValueError("Historical weather is missing more than a week of recent data")
        actual_end = end - timedelta(days=count - available)
        summary = summarize_weather_history(
            {"daily": {key: daily[key][:available] for key in keys}}, actual_end)
        return {"cache_format": CACHE_FORMAT, "status": "ready", "location": location,
                "start_date": START.isoformat(), "end_date": actual_end.isoformat(),
                "requested_end_date": end.isoformat(), "baseline": f"1991–{actual_end.year}",
                "source": "Open-Meteo / ERA5", "calendar_averages": summary, "stale": False}

    def _write_cache(self, payload: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.cache_path)

    async def _load(self, location: dict) -> None:
        try:
            cached = await asyncio.to_thread(self._read_cache, location)
            if location != self.location:
                return
            if cached is not None:
                self.payload = cached
            end = latest_history_date()
            if cached is None or cached["requested_end_date"] != end.isoformat():
                result = await asyncio.to_thread(self._fetch, location, end)
                if location != self.location:
                    return
                self.payload = result
                try:
                    await asyncio.to_thread(self._write_cache, result)
                except OSError as exc:
                    logger.warning("Historical weather cache could not be saved: %s", exc)
            if location == self.location:
                self.next_check = time.monotonic() + 3600
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if location == self.location:
                if self.payload.get("status") == "ready":
                    self.payload = {**self.payload, "stale": True}
                else:
                    self.payload = {"status": "unavailable", "reason": "Historical statistics unavailable"}
                self.next_check = time.monotonic() + 300
            logger.warning("Historical weather unavailable: %s", exc)
