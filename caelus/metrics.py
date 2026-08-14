"""Build display-ready 24-hour metric histories from Ecowitt readings."""

import math
from dataclasses import dataclass
from typing import Any, Iterable

from caelus.units import convert_value, display_unit_for


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    decimals: int = 1


WEATHER_METRICS = (
    MetricSpec("temperature", "Outdoor temperature", ""),
    MetricSpec("dew_point", "Dew point", ""),
    MetricSpec("wind_chill", "Wind chill", ""),
    MetricSpec("heat_index", "Heat index", ""),
    MetricSpec("humidity", "Outdoor humidity", "%", 0),
    MetricSpec("pressure", "Relative pressure", ""),
    MetricSpec("absolute_pressure", "Absolute pressure", ""),
    MetricSpec("wind_speed", "Wind speed", ""),
    MetricSpec("wind_gust", "Wind gust", ""),
    MetricSpec("daily_max_wind", "Daily maximum wind", ""),
    MetricSpec("wind_dir", "Wind direction", "°", 0),
    MetricSpec("uv", "UV index", "", 1),
    MetricSpec("solar_radiation", "Solar radiation", "W/m²", 0),
    MetricSpec("light_intensity", "Light intensity", "lux", 0),
    MetricSpec("rain_rate", "Rain rate", "", 2),
    MetricSpec("rain_increment", "Rain interval", "", 2),
    MetricSpec("rain_total", "Rain today", "", 2),
    MetricSpec("rain_event", "Rain event", "", 2),
    MetricSpec("rain_week", "Rain this week", "", 2),
    MetricSpec("rain_month", "Rain this month", "", 2),
    MetricSpec("rain_year", "Rain this year", "", 2),
    MetricSpec("rain_lifetime", "Lifetime rain", "", 2),
    MetricSpec("indoor_temperature", "Indoor temperature", ""),
    MetricSpec("indoor_humidity", "Indoor humidity", "%", 0),
    MetricSpec("indoor_pressure", "Gateway relative pressure", ""),
    MetricSpec("indoor_absolute_pressure", "Gateway absolute pressure", ""),
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


def build_24_hour_metric_cards(
    rows: Iterable[dict[str, Any]], unit_system: str = "imperial", pressure_unit: str = "hpa"
) -> list[dict[str, Any]]:
    """Return cards only for weather metrics containing valid numeric data."""
    readings = list(rows)
    cards: list[dict[str, Any]] = []
    for spec in WEATHER_METRICS:
        series = []
        for reading in readings:
            value = _finite_number(reading.get(spec.key))
            timestamp = reading.get("timestamp")
            if value is not None and timestamp:
                series.append({
                    "timestamp": str(timestamp),
                    "value": convert_value(spec.key, value, unit_system, pressure_unit),
                })
        if not series:
            continue
        minimum = min(series, key=lambda point: point["value"])
        maximum = max(series, key=lambda point: point["value"])
        average = sum(point["value"] for point in series) / len(series)
        cards.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit or display_unit_for(spec.key, unit_system, pressure_unit),
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

    cards_by_key = {card["key"]: card for card in cards}
    wind_direction_card = cards_by_key.get("wind_dir")
    wind_speed_card = cards_by_key.get("wind_speed")
    if wind_direction_card is not None and wind_speed_card is not None:
        paired_wind_series = []
        for reading in readings:
            direction = _finite_number(reading.get("wind_dir"))
            speed = _finite_number(reading.get("wind_speed"))
            timestamp = reading.get("timestamp")
            if direction is None or speed is None or not timestamp:
                continue
            paired_wind_series.append(
                {
                    "timestamp": str(timestamp),
                    "direction": round(direction) % 360,
                    "speed": convert_value("wind_speed", speed, unit_system, pressure_unit),
                }
            )
        wind_direction_card["wind_speed"] = {
            "current": wind_speed_card["current"],
            "unit": wind_speed_card["unit"],
            "decimals": wind_speed_card["decimals"],
            "stats": wind_speed_card["stats"],
            "series": _sample_series(paired_wind_series),
        }
    return cards
