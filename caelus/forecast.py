import json
import logging
import math
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from caelus import __version__
from caelus.settings import AppSettings

logger = logging.getLogger(__name__)

PROVIDER_LABELS = {
    "met_no": "MET Norway",
    "open_meteo": "Open-Meteo",
    "us": "US · NWS",
}
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NWS_POINTS_URL = "https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}"
CACHE_SECONDS = 60 * 60
CACHE_FORMAT = 4


def normalize_forecast_provider(value: Any) -> str:
    """Normalize user-facing provider aliases to a supported provider key."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"", "met", "met_no", "met_norway", "norway"}:
        return "met_no"
    if text in {"open_meteo", "openmeteo"}:
        return "open_meteo"
    if text in {"us", "usa", "nws", "noaa", "weather_gov", "weather.gov"}:
        return "us"
    raise ValueError("unsupported weather forecast provider")


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _c_to_f(value: float) -> float:
    return (value * 9 / 5) + 32


def _mps_to_mph(value: float) -> float:
    return value * 2.2369362921


def _mph_to_mps(value: float) -> float:
    return value / 2.2369362921


def _f_to_c(value: float) -> float:
    return (value - 32) * 5 / 9


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _condition_icon(condition: str) -> str:
    text = condition.lower()
    if "thunder" in text:
        return "⛈️"
    if "snow" in text or "sleet" in text:
        return "🌨️"
    if "rain" in text or "shower" in text or "drizzle" in text:
        return "🌧️"
    if "fog" in text:
        return "🌫️"
    if "cloud" in text or "overcast" in text:
        return "☁️"
    if "partly" in text:
        return "🌤️"
    return "☀️"


def _precipitation_chance_label(condition: Any) -> str:
    """Name a precipitation probability as a rain or snow chance."""
    text = str(condition or "").lower()
    return "Snow chance" if "snow" in text or "sleet" in text else "Rain chance"


def _precipitation_chance_label_for_rows(rows: list[dict[str, Any]]) -> str:
    """Name the chance from every condition represented in a forecast window."""
    return _precipitation_chance_label(" ".join(str(row.get("condition") or "") for row in rows))


def _wmo_condition(code: Any) -> str:
    number = int(_safe_float(code) or 0)
    if number == 0:
        return "Clear"
    if number in {1, 2}:
        return "Partly cloudy"
    if number == 3:
        return "Cloudy"
    if number in {45, 48}:
        return "Fog"
    if 51 <= number <= 67:
        return "Rain"
    if 71 <= number <= 77:
        return "Snow"
    if 80 <= number <= 82:
        return "Rain showers"
    if 85 <= number <= 86:
        return "Snow showers"
    if number >= 95:
        return "Thunderstorms"
    return "Mixed skies"


def _met_condition(symbol: str) -> str:
    text = symbol.replace("_day", "").replace("_night", "").replace("_polartwilight", "")
    if "thunder" in text:
        return "Thunderstorms"
    if "snow" in text or "sleet" in text:
        return "Snow showers"
    if "rain" in text:
        return "Rain showers"
    if "fog" in text:
        return "Fog"
    if "cloudy" in text:
        return "Cloudy" if text == "cloudy" else "Partly cloudy"
    return "Clear"


def _condition_cloud_percent(condition: str) -> float:
    text = condition.lower()
    if any(word in text for word in ("thunder", "rain", "shower", "snow", "sleet")):
        return 85.0
    if "cloud" in text or "overcast" in text:
        return 90.0 if "partly" not in text else 55.0
    if "fog" in text:
        return 100.0
    return 10.0


def _hour_record(
    *,
    time_value: Any,
    temperature_f: Any,
    precipitation_probability: Any = 0,
    precipitation_mm: Any = 0,
    wind_mph: Any = 0,
    humidity: Any = None,
    cloud_percent: Any = None,
    condition: str,
    timezone_name: str,
) -> dict[str, Any] | None:
    timestamp = _parse_time(time_value)
    temperature = _safe_float(temperature_f)
    if timestamp is None or temperature is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ZoneInfo(timezone_name))
    local = timestamp.astimezone(ZoneInfo(timezone_name))
    return {
        "time": local.isoformat(),
        "label": local.strftime("%I %p").lstrip("0"),
        "temperature_f": round(temperature),
        "precip_probability": round(_safe_float(precipitation_probability) or 0),
        "precipitation_mm": round(_safe_float(precipitation_mm) or 0, 2),
        "wind_mph": round(_safe_float(wind_mph) or 0),
        "humidity": round(_safe_float(humidity)) if _safe_float(humidity) is not None else None,
        "cloud_percent": round(_safe_float(cloud_percent)) if _safe_float(cloud_percent) is not None else None,
        "condition": condition,
        "icon": _condition_icon(condition),
        "precip_label": _precipitation_chance_label(condition),
    }


def normalize_open_meteo(payload: dict[str, Any], timezone_name: str) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return []

    def at(name: str, index: int) -> Any:
        values = hourly.get(name)
        return values[index] if isinstance(values, list) and index < len(values) else None

    rows = []
    for index, time_value in enumerate(hourly["time"]):
        condition = _wmo_condition(at("weather_code", index))
        row = _hour_record(
            time_value=time_value,
            temperature_f=at("temperature_2m", index),
            precipitation_probability=at("precipitation_probability", index),
            precipitation_mm=at("precipitation", index),
            wind_mph=at("wind_speed_10m", index),
            humidity=at("relative_humidity_2m", index),
            cloud_percent=at("cloud_cover", index),
            condition=condition,
            timezone_name=timezone_name,
        )
        if row:
            rows.append(row)
    return rows


def normalize_met(payload: dict[str, Any], timezone_name: str) -> list[dict[str, Any]]:
    properties = payload.get("properties") if isinstance(payload, dict) else None
    series = properties.get("timeseries") if isinstance(properties, dict) else None
    if not isinstance(series, list):
        return []
    rows = []
    for item in series:
        data = item.get("data") if isinstance(item, dict) else None
        instant = data.get("instant", {}).get("details", {}) if isinstance(data, dict) else {}
        forecast_period: dict[str, Any] = {}
        if isinstance(data, dict):
            for period_name in ("next_1_hours", "next_6_hours", "next_12_hours"):
                candidate = data.get(period_name)
                if isinstance(candidate, dict):
                    forecast_period = candidate
                    break
        details = forecast_period.get("details", {})
        summary = forecast_period.get("summary", {})
        precip = _safe_float(details.get("precipitation_amount")) or 0
        probability = _safe_float(details.get("probability_of_precipitation"))
        if probability is None:
            probability = 85 if precip >= 1 else 55 if precip > 0 else 5
        condition = _met_condition(str(summary.get("symbol_code") or ""))
        temp_c = _safe_float(instant.get("air_temperature"))
        wind_mps = _safe_float(instant.get("wind_speed")) or 0
        row = _hour_record(
            time_value=item.get("time"),
            temperature_f=_c_to_f(temp_c) if temp_c is not None else None,
            precipitation_probability=probability,
            precipitation_mm=precip,
            wind_mph=_mps_to_mph(wind_mps),
            humidity=instant.get("relative_humidity"),
            cloud_percent=instant.get("cloud_area_fraction"),
            condition=condition,
            timezone_name=timezone_name,
        )
        if row:
            rows.append(row)
    return rows


def normalize_nws(payload: dict[str, Any], timezone_name: str) -> list[dict[str, Any]]:
    properties = payload.get("properties") if isinstance(payload, dict) else None
    periods = properties.get("periods") if isinstance(properties, dict) else None
    if not isinstance(periods, list):
        return []
    rows = []
    for period in periods:
        if not isinstance(period, dict):
            continue
        wind_text = str(period.get("windSpeed") or "")
        wind_values = [_safe_float(part) for part in wind_text.replace("to", " ").split()]
        wind_values = [value for value in wind_values if value is not None]
        wind = sum(wind_values) / len(wind_values) if wind_values else 0
        probability = period.get("probabilityOfPrecipitation")
        if isinstance(probability, dict):
            probability = probability.get("value")
        condition = str(period.get("shortForecast") or "Mixed skies")
        temperature = _safe_float(period.get("temperature"))
        if str(period.get("temperatureUnit") or "F").upper() == "C" and temperature is not None:
            temperature = _c_to_f(temperature)
        row = _hour_record(
            time_value=period.get("startTime"),
            temperature_f=temperature,
            precipitation_probability=probability,
            wind_mph=wind,
            humidity=(period.get("relativeHumidity") or {}).get("value")
            if isinstance(period.get("relativeHumidity"), dict)
            else period.get("relativeHumidity"),
            cloud_percent=_condition_cloud_percent(condition),
            condition=condition,
            timezone_name=timezone_name,
        )
        if row:
            rows.append(row)
    return rows


def _wind_descriptor(average_mps: float) -> str:
    if average_mps < 2:
        return "light"
    if average_mps < 5:
        return "light/moderate"
    if average_mps < 8:
        return "moderate"
    return "breezy"


def _period_name(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "overnight"


def _daily_summary(rows: list[dict[str, Any]], timezone_name: str) -> str:
    """Describe the day's early sky and most likely precipitation period."""
    if not rows:
        return "Forecast unavailable"
    third = max(1, len(rows) // 3)
    early_clouds = [float(row["cloud_percent"]) for row in rows[:third] if row.get("cloud_percent") is not None]
    average_cloud = sum(early_clouds) / len(early_clouds) if early_clouds else None
    if average_cloud is None:
        opening = rows[0]["condition"]
    elif average_cloud < 20:
        opening = "Clear"
    elif average_cloud < 45:
        opening = "Mostly clear"
    elif average_cloud < 75:
        opening = "Partly cloudy"
    else:
        opening = "Cloudy"
    wet_rows = [
        row
        for row in rows
        if row.get("precipitation_mm", 0) >= 0.05
        or any(word in row.get("condition", "").lower() for word in ("rain", "shower", "snow", "thunder"))
    ]
    if not wet_rows:
        return f"{opening} early"
    periods = Counter(
        _period_name((_parse_time(row["time"]) or datetime.now(timezone.utc)).astimezone(ZoneInfo(timezone_name)).hour)
        for row in wet_rows
    )
    wet_period = periods.most_common(1)[0][0]
    total_mm = sum(float(row.get("precipitation_mm") or 0) for row in rows)
    intensity = "light rain/showers" if total_mm < 3 else "rain/showers" if total_mm < 12 else "heavy rain/showers"
    return f"{opening} early, {intensity} {wet_period}"


def _daily_detail(rows: list[dict[str, Any]], local_date: Any, timezone_name: str) -> dict[str, Any]:
    temperatures = [float(row["temperature_f"]) for row in rows]
    humidities = [float(row["humidity"]) for row in rows if row.get("humidity") is not None]
    winds_mph = [float(row["wind_mph"]) for row in rows]
    low_f, high_f = min(temperatures), max(temperatures)
    low_mph, high_mph = min(winds_mph), max(winds_mph)
    average_mps = sum(_mph_to_mps(value) for value in winds_mph) / len(winds_mph)
    condition = Counter(row["condition"] for row in rows).most_common(1)[0][0]
    return {
        "date": local_date.isoformat(),
        "label": f"{local_date.strftime('%a %b')} {local_date.day}",
        "condition": condition,
        "summary": _daily_summary(rows, timezone_name),
        "icon": _condition_icon(condition),
        "precip_label": _precipitation_chance_label_for_rows(rows),
        "high_f": round(high_f),
        "low_f": round(low_f),
        "high_c": round(_f_to_c(high_f), 1),
        "low_c": round(_f_to_c(low_f), 1),
        "humidity_low": round(min(humidities)) if humidities else None,
        "humidity_high": round(max(humidities)) if humidities else None,
        "precip_probability": max(row["precip_probability"] for row in rows),
        "precipitation_mm": round(sum(row["precipitation_mm"] for row in rows), 1),
        "wind_descriptor": _wind_descriptor(average_mps),
        "wind_low_mph": round(low_mph),
        "wind_high_mph": round(high_mph),
        "wind_low_mps": round(_mph_to_mps(low_mph)),
        "wind_high_mps": round(_mph_to_mps(high_mph)),
    }


def build_forecast(provider: str, rows: list[dict[str, Any]], timezone_name: str) -> dict[str, Any]:
    """Build the dashboard forecast and decision inputs from normalized hours."""
    now = datetime.now(ZoneInfo(timezone_name))
    future = [row for row in rows if (_parse_time(row["time"]) or now) >= now - timedelta(minutes=90)]
    today = [row for row in future if (_parse_time(row["time"]) or now).date() == now.date()]
    window = today or future[:24]
    if not window:
        return {"ok": False, "provider": provider, "reason": "empty forecast", "hours": []}
    conditions = Counter(row["condition"] for row in window)
    condition = conditions.most_common(1)[0][0]
    display_hours = future[:24]
    daily_groups: dict[Any, list[dict[str, Any]]] = {}
    for row in future:
        parsed = _parse_time(row["time"])
        if parsed is None:
            continue
        local_date = parsed.astimezone(ZoneInfo(timezone_name)).date()
        if local_date <= now.date():
            continue
        daily_groups.setdefault(local_date, []).append(row)
    days = []
    for local_date, day_rows in list(sorted(daily_groups.items()))[:6]:
        days.append(_daily_detail(day_rows, local_date, timezone_name))
    return {
        "ok": True,
        "cache_format": CACHE_FORMAT,
        "provider": provider,
        "provider_label": PROVIDER_LABELS[provider],
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "condition": condition,
        "icon": _condition_icon(condition),
        "precip_label": _precipitation_chance_label_for_rows(window),
        "high_f": max(row["temperature_f"] for row in window),
        "low_f": min(row["temperature_f"] for row in window),
        "precip_probability": max(row["precip_probability"] for row in window),
        "precipitation_mm": round(sum(row["precipitation_mm"] for row in window), 1),
        "hours": display_hours,
        "days": days,
        "decision_hours": future[:24],
    }


def build_decisions(forecast: dict[str, Any]) -> list[dict[str, str]]:
    """Create concise environmental guidance from forecast thresholds."""
    if not forecast.get("ok"):
        return [
            {"icon": "◌", "title": "Forecast decisions", "status": "Waiting for forecast", "detail": "Choose a provider and confirm location."}
        ]
    rain_probability = int(forecast.get("precip_probability") or 0)
    rain_mm = float(forecast.get("precipitation_mm") or 0)
    low_f = int(forecast.get("low_f") or 99)
    hours = forecast.get("decision_hours") if isinstance(forecast.get("decision_hours"), list) else []
    suitable = []
    for hour in hours:
        parsed = _parse_time(hour.get("time"))
        if parsed and 8 <= parsed.hour <= 18 and hour.get("precip_probability", 0) < 25 and hour.get("wind_mph", 0) < 16:
            suitable.append(parsed)
    if suitable:
        window = f"{suitable[0].strftime('%H:%M')}–{suitable[-1].strftime('%H:%M')}"
        window_detail = "Low rain chance and manageable wind."
    else:
        window = "No clear window"
        window_detail = "Rain or wind may limit outdoor work."
    return [
        {
            "icon": "♒",
            "title": "Irrigation",
            "status": "Delay watering" if rain_probability >= 50 or rain_mm >= 2 else "Watering window open",
            "detail": f"Rain chance {rain_probability}% · {rain_mm:g} mm expected.",
        },
        {
            "icon": "❄",
            "title": "Frost protection",
            "status": "Protect tender plants" if low_f <= 36 else "No frost signal",
            "detail": f"Forecast low {low_f}°F.",
        },
        {"icon": "☀", "title": "Best outdoor window", "status": window, "detail": window_detail},
    ]


class ForecastService:
    """Fetch selected forecasts with a small persistent last-good cache."""

    def __init__(self, cache_path: Path, session: Any = requests) -> None:
        self.cache_path = cache_path
        self.session = session
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": f"Caelus/{__version__} local-weather-dashboard", "Accept": "application/json"}

    def _read_cache(self, settings: AppSettings) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cache_needs_refresh = payload.get("cache_format") != CACHE_FORMAT or not isinstance(
                payload.get("days"), list
            )
            if cache_needs_refresh:
                payload["days"] = []
            updated = _parse_time(payload.get("updated_at"))
            same = payload.get("provider") == settings.forecast_provider and abs(float(payload["latitude"]) - settings.latitude) < 0.05 and abs(float(payload["longitude"]) - settings.longitude) < 0.05
            if updated and same:
                payload["cache_age_seconds"] = max(0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds())
                payload["cache_needs_refresh"] = cache_needs_refresh
                return payload
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None
        return None

    def _write_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.cache_path)

    def get(self, settings: AppSettings, *, force: bool = False, timeout_seconds: float = 8.0) -> dict[str, Any]:
        with self._lock:
            return self._get_locked(settings, force=force, timeout_seconds=timeout_seconds)

    def _get_locked(self, settings: AppSettings, *, force: bool, timeout_seconds: float) -> dict[str, Any]:
        provider = normalize_forecast_provider(settings.forecast_provider)
        if settings.latitude == 0.0 and settings.longitude == 0.0:
            return {"ok": False, "provider": provider, "reason": "location unavailable", "hours": []}
        cached = self._read_cache(settings)
        if cached and not force and not cached.get("cache_needs_refresh") and cached.get("cache_age_seconds", CACHE_SECONDS + 1) <= CACHE_SECONDS:
            cached["stale"] = False
            return cached
        try:
            rows = self._fetch(provider, settings, timeout_seconds)
            result = build_forecast(provider, rows, settings.timezone)
            if not result.get("ok"):
                raise ValueError(str(result.get("reason") or "empty forecast"))
            result.update(latitude=settings.latitude, longitude=settings.longitude, stale=False)
            self._write_cache(result)
            return result
        except Exception as exc:
            logger.warning("%s forecast failed: %s", provider, exc)
            if cached:
                cached["stale"] = True
                cached["reason"] = str(exc)
                return cached
            return {"ok": False, "provider": provider, "reason": str(exc), "hours": []}

    def _fetch(self, provider: str, settings: AppSettings, timeout_seconds: float) -> list[dict[str, Any]]:
        headers = self._headers()
        if provider == "met_no":
            response = self.session.get(MET_URL, params={"lat": settings.latitude, "lon": settings.longitude}, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            return normalize_met(response.json(), settings.timezone)
        if provider == "open_meteo":
            response = self.session.get(
                OPEN_METEO_URL,
                params={
                    "latitude": settings.latitude,
                    "longitude": settings.longitude,
                    "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,weather_code,cloud_cover,wind_speed_10m",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "timezone": settings.timezone or "auto",
                    "forecast_days": 7,
                },
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return normalize_open_meteo(response.json(), settings.timezone)
        points = self.session.get(
            NWS_POINTS_URL.format(latitude=settings.latitude, longitude=settings.longitude),
            headers=headers,
            timeout=timeout_seconds,
        )
        points.raise_for_status()
        properties = points.json().get("properties", {})
        hourly_url = properties.get("forecastHourly")
        if not hourly_url:
            raise ValueError("NWS forecast is available only for US locations")
        response = self.session.get(hourly_url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        return normalize_nws(response.json(), settings.timezone)
