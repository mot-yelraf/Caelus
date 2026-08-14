"""Convert normalized Caelus readings into operator-selected display units."""

from typing import Any

INHG_TO_HPA = 33.8638866667
MPH_TO_KMH = 1.609344
INCH_TO_MM = 25.4

TEMPERATURE_FIELDS = {
    "temperature", "dew_point", "wind_chill", "heat_index", "indoor_temperature"
}
WIND_FIELDS = {"wind_speed", "wind_gust", "daily_max_wind"}
RAIN_FIELDS = {
    "rain_total", "rain_event", "rain_week", "rain_month", "rain_year",
    "rain_lifetime", "rain_increment",
}
PRESSURE_FIELDS = {
    "pressure", "absolute_pressure", "indoor_pressure", "indoor_absolute_pressure"
}


def pressure_display_unit(unit_system: str, pressure_unit: str) -> str:
    """Resolve the pressure override or preset default."""
    if pressure_unit in {"hpa", "inhg"}:
        return pressure_unit
    return "hpa" if unit_system == "metric" else "inhg"


def display_unit_for(field: str, unit_system: str, pressure_unit: str) -> str:
    """Return the selected display unit for a normalized reading field."""
    if field in TEMPERATURE_FIELDS:
        return "°C" if unit_system == "metric" else "°F"
    if field in WIND_FIELDS:
        return "km/h" if unit_system == "metric" else "mph"
    if field == "rain_rate":
        return "mm/hr" if unit_system == "metric" else "in/hr"
    if field in RAIN_FIELDS:
        return "mm" if unit_system == "metric" else "in"
    if field in PRESSURE_FIELDS:
        return "hPa" if pressure_display_unit(unit_system, pressure_unit) == "hpa" else "inHg"
    return ""


def convert_value(field: str, value: Any, unit_system: str, pressure_unit: str) -> Any:
    """Convert one normalized value while preserving unavailable data."""
    if value is None or isinstance(value, bool):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if unit_system == "metric":
        if field in TEMPERATURE_FIELDS:
            number = (number - 32.0) * 5.0 / 9.0
        elif field in WIND_FIELDS:
            number *= MPH_TO_KMH
        elif field == "rain_rate" or field in RAIN_FIELDS:
            number *= INCH_TO_MM
    if field in PRESSURE_FIELDS and pressure_display_unit(unit_system, pressure_unit) == "hpa":
        number *= INHG_TO_HPA
    return number


def convert_reading(reading: dict[str, Any] | None, unit_system: str, pressure_unit: str) -> dict[str, Any]:
    """Return a display-only copy of one normalized reading."""
    result = dict(reading or {})
    for field in TEMPERATURE_FIELDS | WIND_FIELDS | RAIN_FIELDS | PRESSURE_FIELDS | {"rain_rate"}:
        if field in result:
            result[field] = convert_value(field, result[field], unit_system, pressure_unit)
    if result.get("pressure") is None and result.get("indoor_pressure") is not None:
        result["pressure"] = result["indoor_pressure"]
    return result
