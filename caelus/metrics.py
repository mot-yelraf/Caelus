"""Build display-ready 24-hour metric histories from Ecowitt readings."""

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    decimals: int = 1


WEATHER_METRICS = (
    MetricSpec("temperature", "Outdoor temperature", "°F"),
    MetricSpec("dew_point", "Dew point", "°F"),
    MetricSpec("wind_chill", "Wind chill", "°F"),
    MetricSpec("heat_index", "Heat index", "°F"),
    MetricSpec("humidity", "Outdoor humidity", "%", 0),
    MetricSpec("pressure", "Relative pressure", "inHg", 2),
    MetricSpec("absolute_pressure", "Absolute pressure", "inHg", 2),
    MetricSpec("wind_speed", "Wind speed", "mph"),
    MetricSpec("wind_gust", "Wind gust", "mph"),
    MetricSpec("daily_max_wind", "Daily maximum wind", "mph"),
    MetricSpec("wind_dir", "Wind direction", "°", 0),
    MetricSpec("uv", "UV index", "", 1),
    MetricSpec("solar_radiation", "Solar radiation", "W/m²", 0),
    MetricSpec("light_intensity", "Light intensity", "lux", 0),
    MetricSpec("rain_rate", "Rain rate", "in/hr", 2),
    MetricSpec("rain_increment", "Rain interval", "in", 2),
    MetricSpec("rain_total", "Rain today", "in", 2),
    MetricSpec("rain_event", "Rain event", "in", 2),
    MetricSpec("rain_week", "Rain this week", "in", 2),
    MetricSpec("rain_month", "Rain this month", "in", 2),
    MetricSpec("rain_year", "Rain this year", "in", 2),
    MetricSpec("rain_lifetime", "Lifetime rain", "in", 2),
    MetricSpec("indoor_temperature", "Indoor temperature", "°F"),
    MetricSpec("indoor_humidity", "Indoor humidity", "%", 0),
    MetricSpec("indoor_pressure", "Indoor relative pressure", "inHg", 2),
    MetricSpec("indoor_absolute_pressure", "Indoor absolute pressure", "inHg", 2),
)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _sample_series(series: list[dict[str, Any]], limit: int = 289) -> list[dict[str, Any]]:
    """Bound browser payload size while retaining both ends of a series."""
    if len(series) <= limit:
        return series
    last = len(series) - 1
    indices = sorted({round(index * last / (limit - 1)) for index in range(limit)})
    return [series[index] for index in indices]


def build_24_hour_metric_cards(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return cards only for weather metrics containing valid numeric data."""
    readings = list(rows)
    cards: list[dict[str, Any]] = []
    for spec in WEATHER_METRICS:
        series = []
        for reading in readings:
            value = _finite_number(reading.get(spec.key))
            timestamp = reading.get("timestamp")
            if value is not None and timestamp:
                series.append({"timestamp": str(timestamp), "value": value})
        if not series:
            continue
        minimum = min(series, key=lambda point: point["value"])
        maximum = max(series, key=lambda point: point["value"])
        average = sum(point["value"] for point in series) / len(series)
        cards.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "decimals": spec.decimals,
                "current": round(series[-1]["value"], spec.decimals),
                "series": _sample_series(series),
                "stats": {
                    "min": round(minimum["value"], spec.decimals),
                    "min_at": minimum["timestamp"],
                    "avg": round(average, spec.decimals),
                    "max": round(maximum["value"], spec.decimals),
                    "max_at": maximum["timestamp"],
                    "samples": len(series),
                },
            }
        )
    return cards
