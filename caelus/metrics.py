"""Build display-ready 24-hour metric histories from Ecowitt readings."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    MetricSpec("humidity", "Outdoor relative humidity", "%", 0),
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

PINNED_METRIC_KEYS = ("temperature", "humidity", "wind_dir", "rain_total")
RAIN_METRIC_KEYS = {
    "rain_rate",
    "rain_increment",
    "rain_total",
    "rain_event",
    "rain_week",
    "rain_month",
    "rain_year",
    "rain_lifetime",
}


def metric_display_options() -> tuple[MetricSpec, ...]:
    """Return settings controls with the primary row pinned, then labels A–Z."""
    pinned_positions = {key: index for index, key in enumerate(PINNED_METRIC_KEYS)}
    return tuple(
        sorted(
            WEATHER_METRICS,
            key=lambda spec: (0, pinned_positions[spec.key])
            if spec.key in pinned_positions
            else (1, spec.label.casefold()),
        )
    )


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _sample_series(
    series: list[dict[str, Any]], limit: int = 289, *, value_key: str = "value"
) -> list[dict[str, Any]]:
    """Bound browser payload size while retaining endpoints and extrema."""
    if len(series) <= limit:
        return series
    last = len(series) - 1
    minimum_index = min(range(len(series)), key=lambda index: series[index][value_key])
    maximum_index = max(range(len(series)), key=lambda index: series[index][value_key])
    indices = {0, last, minimum_index, maximum_index}
    for index in range(limit):
        indices.add(round(index * last / (limit - 1)))
        if len(indices) >= limit:
            break
    return [series[index] for index in sorted(indices)]


def _series_stats(
    series: list[dict[str, Any]], spec: MetricSpec
) -> dict[str, Any] | None:
    """Calculate exact scalar or circular statistics for one metric series."""
    if not series:
        return None
    minimum = min(series, key=lambda point: point["value"])
    maximum = max(series, key=lambda point: point["value"])
    values = [point["value"] for point in series]
    if spec.key == "wind_dir":
        sine = sum(math.sin(math.radians(value)) for value in values)
        cosine = sum(math.cos(math.radians(value)) for value in values)
        if math.hypot(sine, cosine) < 1e-9:
            average = None
        else:
            average = round(math.degrees(math.atan2(sine, cosine)) % 360, spec.decimals)
            if average == 360:
                average = 0.0
        minimum_value = maximum_value = None
        minimum_at = maximum_at = None
    else:
        average = round(sum(values) / len(values), spec.decimals)
        minimum_value = round(minimum["value"], spec.decimals)
        minimum_at = minimum["timestamp"]
        maximum_value = round(maximum["value"], spec.decimals)
        maximum_at = maximum["timestamp"]
    return {
        "min": minimum_value,
        "min_at": minimum_at,
        "avg": average,
        "max": maximum_value,
        "max_at": maximum_at,
        "samples": len(series),
    }


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def build_24_hour_metric_cards(
    rows: Iterable[dict[str, Any]],
    unit_system: str = "imperial",
    pressure_unit: str = "hpa",
    observed_at: datetime | None = None,
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
                display_value = convert_value(
                    spec.key, value, unit_system, pressure_unit
                )
                series.append({
                    "timestamp": str(timestamp),
                    "value": max(0.0, display_value)
                    if spec.key in RAIN_METRIC_KEYS
                    else display_value,
                })
        if not series:
            continue
        latest_time = observed_at
        if latest_time is not None and latest_time.tzinfo is not None:
            latest_time = latest_time.astimezone(timezone.utc).replace(tzinfo=None)
        if latest_time is None:
            latest_time = max(
                (parsed for point in series if (parsed := _timestamp(point["timestamp"]))),
                default=None,
            )
        six_hour_cutoff = latest_time - timedelta(hours=6) if latest_time else None
        six_hour_series = [
            point
            for point in series
            if six_hour_cutoff is None
            or ((parsed := _timestamp(point["timestamp"])) is not None and parsed >= six_hour_cutoff)
        ]
        complete_stats = _series_stats(series, spec)
        cards.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit or display_unit_for(spec.key, unit_system, pressure_unit),
                "decimals": spec.decimals,
                "current": round(series[-1]["value"], spec.decimals),
                "series": _sample_series(series),
                "stats": complete_stats,
                "stats_by_hours": {
                    "6": _series_stats(six_hour_series, spec),
                    "24": complete_stats,
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
            "stats_by_hours": wind_speed_card["stats_by_hours"],
            "series": _sample_series(paired_wind_series, value_key="speed"),
        }
    display_positions = {
        spec.key: index for index, spec in enumerate(metric_display_options())
    }
    return sorted(cards, key=lambda card: display_positions[card["key"]])
