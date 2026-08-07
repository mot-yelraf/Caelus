import requests
from requests.exceptions import RequestException
from typing import Any, Dict

from caelus.settings import AppSettings


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def map_gateway_reading(reading: Dict[str, Any]) -> Dict[str, Any]:
    """Map an Ecowitt payload to Caelus's stable metric names."""
    wind_speed = reading.get("windsp")
    if wind_speed is None:
        wind_speed = reading.get("windspeed")
    return {
        "wind_speed": wind_speed,
        "wind_dir": _optional_int(reading.get("winddir")),
        "wind_gust": reading.get("windgust"),
        "rain_rate": reading.get("rainrate"),
        "rain_total": reading.get("dailyrainin"),
        "temperature": reading.get("tempf"),
        "humidity": reading.get("hum"),
        "uv": reading.get("uv"),
        "solar_radiation": reading.get("solarradiation"),
        "pressure": reading.get("baromin"),
        "indoor_temperature": reading.get("tempinf"),
        "indoor_humidity": reading.get("hum_in"),
    }


class EcowittGateway:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def fetch(self) -> Dict[str, Any]:
        try:
            response = requests.get(self.settings.gateway_url, timeout=10)
            response.raise_for_status()
            return self._parse_response(response.text)
        except RequestException:
            return {}

    def _parse_response(self, payload: str) -> Dict[str, Any]:
        values = {}
        for item in payload.strip().split("&"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            if value == "":
                continue
            values[key] = self._cast_value(key, value)
        return values

    def _cast_value(self, key: str, value: str) -> Any:
        if key in {"winddir", "windgust", "windsp", "windspeed", "tempf", "tempinf", "hum", "hum_in", "uv", "solarradiation", "baromin", "rainrate", "hourlyrainin", "dailyrainin"}:
            try:
                return float(value)
            except ValueError:
                return value
        return value
