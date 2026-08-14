"""Read and normalize Ecowitt gateway weather data."""

import math
import re
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Dict
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.exceptions import RequestException

from caelus.settings import AppSettings

REQUEST_TIMEOUT_SECONDS = 5
DISCOVERY_CACHE_SECONDS = 60
MAX_RESPONSE_BYTES = 512 * 1024
_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
_INVALID_SENSOR_IDS = {"FFFFFFFF", "FFFFFFFE"}


class EcowittGatewayError(RuntimeError):
    """Report an operator-visible Ecowitt validation or protocol failure."""


def normalize_gateway_base_url(value: Any) -> str:
    """Validate and normalize an Ecowitt read-only LAN API base URL."""
    raw = str(value or "").strip()
    if not raw:
        raise EcowittGatewayError("Ecowitt gateway URL is required.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise EcowittGatewayError("Ecowitt gateway URL is invalid.") from exc
    if parsed.scheme.lower() != "http":
        raise EcowittGatewayError("Ecowitt gateway URL must use plain HTTP.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise EcowittGatewayError(
            "Ecowitt gateway URL must contain a host and no credentials."
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise EcowittGatewayError(
            "Enter only the gateway base URL without a path, query, or fragment."
        )
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urlunsplit(("http", f"{host}:{port}" if port else host, "", "", ""))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "--"}:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        result = float(match.group(0))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _unit(item: dict[str, Any], value: Any) -> str:
    explicit = str(item.get("unit", "") or "").strip().lower()
    if explicit:
        return explicit.replace("°", "").replace(" ", "")
    text = str(value or "").strip().lower().replace("°", "")
    match = re.search(r"[a-z%/²0-9]+(?:\s*/\s*[a-z]+)?\s*$", text)
    return match.group(0).replace(" ", "") if match else ""


def _temperature_f(value: float, unit: str) -> float | None:
    if unit in {"f", "degf", "fahrenheit"}:
        return value
    if unit in {"c", "degc", "celsius"}:
        return value * 9.0 / 5.0 + 32.0
    return None


def _pressure_inhg(value: float, unit: str) -> float | None:
    if unit in {"inhg", "in/hg"}:
        return value
    if unit in {"hpa", "mbar", "mb"}:
        return value / 33.8638866667
    if unit == "pa":
        return value / 3386.38866667
    return None


def _wind_mph(value: float, unit: str) -> float | None:
    if unit in {"mph", "mi/h"}:
        return value
    if unit in {"m/s", "mps", "ms"}:
        return value * 2.2369362921
    if unit in {"km/h", "kph", "kmh"}:
        return value * 0.6213711922
    if unit in {"kn", "kt", "kts", "knot", "knots"}:
        return value * 1.150779448
    return None


def _rain_inches(value: float, unit: str, *, rate: bool = False) -> float | None:
    normalized_unit = unit.replace("hour", "h").replace("hr", "h")
    if rate:
        normalized_unit = normalized_unit.replace("/h", "")
    if normalized_unit in {"in", "inch", "inches"}:
        return value
    if normalized_unit in {"mm", "millimeter", "millimeters"}:
        return value / 25.4
    if normalized_unit == "cm":
        return value / 2.54
    return None


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("id", "") or "").strip().lower()


def _put_temperature(
    output: dict[str, Any], name: str, item: dict[str, Any], raw: Any
) -> None:
    value = _number(raw)
    converted = _temperature_f(value, _unit(item, raw)) if value is not None else None
    if converted is not None:
        output[name] = round(converted, 1)


def _parse_common(payload: dict[str, Any], output: dict[str, Any]) -> None:
    names = {
        "0x02": "temperature",
        "0x03": "dew_point",
        "0x04": "wind_chill",
        "0x05": "heat_index",
    }
    for item in payload.get("common_list") or []:
        if not isinstance(item, dict):
            continue
        item_id = _item_id(item)
        raw = item.get("val")
        value = _number(raw)
        if value is None:
            continue
        unit = _unit(item, raw)
        if item_id in names:
            _put_temperature(output, names[item_id], item, raw)
        elif item_id == "0x07":
            output["humidity"] = round(value, 1)
        elif item_id in {"0x08", "0x09"}:
            converted = _pressure_inhg(value, unit)
            if converted is not None:
                output["absolute_pressure" if item_id == "0x08" else "pressure"] = round(converted, 3)
        elif item_id == "0x0a":
            output["wind_dir"] = round(value) % 360
        elif item_id in {"0x0b", "0x0c", "0x19"}:
            converted = _wind_mph(value, unit)
            if converted is not None:
                name = {"0x0b": "wind_speed", "0x0c": "wind_gust", "0x19": "daily_max_wind"}[item_id]
                output[name] = round(converted, 1)
        elif item_id == "0x15":
            if unit in {"lux", "lx"}:
                output["light_intensity"] = round(value, 1)
            elif unit in {"klux", "klx"}:
                output["light_intensity"] = round(value * 1000.0, 1)
            elif unit in {"w/m2", "w/m²", "wm2"}:
                output["solar_radiation"] = round(value, 1)
        elif item_id == "0x17":
            output["uv"] = round(value, 1)


def _parse_rain(items: Any, output: dict[str, Any]) -> None:
    names = {
        "0x0d": "rain_event",
        "0x0e": "rain_rate",
        "0x10": "rain_total",
        "0x11": "rain_week",
        "0x12": "rain_month",
        "0x13": "rain_year",
        "0x14": "rain_lifetime",
    }
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = names.get(_item_id(item))
        raw = item.get("val")
        value = _number(raw)
        if not name or value is None:
            continue
        converted = _rain_inches(value, _unit(item, raw), rate=name == "rain_rate")
        if converted is not None:
            output[name] = round(converted, 2 if name == "rain_rate" else 3)


def _parse_gateway_indoor(payload: dict[str, Any], output: dict[str, Any]) -> None:
    item = next((value for value in payload.get("wh25") or [] if isinstance(value, dict)), None)
    if not item:
        return
    _put_temperature(output, "indoor_temperature", item, item.get("intemp"))
    humidity = _number(item.get("inhumi"))
    if humidity is not None:
        output["indoor_humidity"] = round(humidity, 1)
    for field, name in (("abs", "indoor_absolute_pressure"), ("rel", "indoor_pressure")):
        value = _number(item.get(field))
        if value is None:
            continue
        converted = _pressure_inhg(value, _unit({}, item.get(field)))
        if converted is not None:
            output[name] = round(converted, 3)


def normalize_ecowitt_livedata(
    payload: dict[str, Any], *, rain_source: str = "traditional"
) -> dict[str, Any]:
    """Normalize a GW1100 live-data response into Caelus metric names."""
    if not isinstance(payload, dict):
        return {}
    output: dict[str, Any] = {}
    _parse_common(payload, output)
    rain_items = None if rain_source == "none" else payload.get(
        "piezoRain" if rain_source == "piezo" else "rain"
    )
    _parse_rain(rain_items, output)
    _parse_gateway_indoor(payload, output)
    return output


def normalize_sensor_inventory(page_payloads: list[Any]) -> list[dict[str, Any]]:
    """Merge inventory pages while filtering disabled and sentinel sensors."""
    inventory: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for payload in page_payloads:
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            sensor_id = str(item.get("id", "") or "").strip().upper().removeprefix("0X")
            signal = int(_number(item.get("signal")) or 0)
            registered = str(item.get("idst", "1") or "1").strip() != "0"
            if (
                not sensor_id
                or sensor_id in _INVALID_SENSOR_IDS
                or not registered
                or (sensor_id == "0" and signal <= 0)
            ):
                continue
            sensor_type = str(item.get("type", "") or "").strip()
            if (sensor_type, sensor_id) in seen:
                continue
            seen.add((sensor_type, sensor_id))
            inventory.append(
                {
                    "id": sensor_id,
                    "type": sensor_type,
                    "family": str(item.get("img", "") or "").strip(),
                    "name": str(item.get("name", "") or "").strip() or "Ecowitt sensor",
                    "battery": str(item.get("batt", "") or "").strip(),
                    "signal": signal,
                    "registered": True,
                    "firmware": str(item.get("version", "") or "").strip(),
                }
            )
    return inventory


def normalized_gateway_id(mac: Any) -> str:
    """Build a stable gateway identity from an Ecowitt MAC address."""
    compact = re.sub(r"[^0-9a-fA-F]", "", str(mac or ""))
    if len(compact) != 12:
        raise EcowittGatewayError("Gateway did not return a valid MAC address.")
    return f"ecowitt-{compact.lower()}"


def rain_source_from_totals(payload: Any) -> str:
    """Return the authoritative traditional, piezo, or disabled rain source."""
    priority = str(payload.get("rainFallPriority", "") if isinstance(payload, dict) else "").strip()
    return {"0": "none", "1": "traditional", "2": "piezo"}.get(priority, "traditional")


def rain_reset_hour_from_totals(payload: Any) -> int:
    """Return the configured local rain-day reset hour."""
    try:
        value = int(str(payload.get("rstRainDay", "0") if isinstance(payload, dict) else "0"))
    except (TypeError, ValueError):
        value = 0
    return max(0, min(23, value))


def _optional_int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def map_gateway_reading(reading: Dict[str, Any], *, rain_source: str = "traditional") -> Dict[str, Any]:
    """Map either modern JSON or legacy Ecowitt data to stable Caelus names."""
    if any(key in reading for key in ("common_list", "rain", "piezoRain", "wh25")):
        return normalize_ecowitt_livedata(reading, rain_source=rain_source)
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
    """Discover and poll one Ecowitt gateway over its read-only LAN API."""

    def __init__(self, settings: AppSettings, session: Any = requests) -> None:
        self.settings = settings
        self.session = session
        self.last_status: dict[str, Any] = {
            "state": "disabled" if not settings.gateway_enabled else "waiting",
            "label": "Ecowitt polling disabled" if not settings.gateway_enabled else "Waiting for Ecowitt gateway",
            "last_error": "",
            "last_success": "",
        }
        self._discovery_cache: tuple[float, dict[str, Any]] | None = None

    def _request(self, base_url: str, endpoint: str, **params: Any) -> Any:
        try:
            response = self.session.get(
                f"{base_url}/{endpoint}",
                params=params or None,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise EcowittGatewayError(f"Gateway request failed for {endpoint}.") from exc
        content = getattr(response, "content", b"")
        if len(content) > MAX_RESPONSE_BYTES:
            raise EcowittGatewayError(f"Gateway response for {endpoint} was unexpectedly large.")
        try:
            return response.json()
        except ValueError as exc:
            raise EcowittGatewayError(f"Gateway returned invalid JSON for {endpoint}.") from exc

    def discover(self, gateway_url: Any) -> dict[str, Any]:
        """Validate a gateway and return its safe identity and sensor inventory."""
        base_url = normalize_gateway_base_url(gateway_url)
        version = self._request(base_url, "get_version")
        network = self._request(base_url, "get_network_info")
        page1 = self._request(base_url, "get_sensors_info", page=1)
        page2 = self._request(base_url, "get_sensors_info", page=2)
        live = self._request(base_url, "get_livedata_info")
        rain_totals = self._request(base_url, "get_rain_totals")
        if not isinstance(version, dict) or not isinstance(network, dict) or not isinstance(live, dict):
            raise EcowittGatewayError("Gateway response schema is not supported.")
        platform = str(version.get("platform", "") or "").strip().lower()
        if platform and platform != "ecowitt":
            raise EcowittGatewayError("The device does not identify itself as an Ecowitt gateway.")
        inventory = normalize_sensor_inventory([page1, page2])
        live_sections = {key for key, value in live.items() if isinstance(value, list) and value}
        for sensor in inventory:
            sensor["reporting"] = bool(
                live_sections.intersection({"common_list", "rain", "piezoRain", "wh25"})
            )
        rain_source = rain_source_from_totals(rain_totals)
        result = {
            "ok": True,
            "gateway_url": base_url,
            "gateway_id": normalized_gateway_id(network.get("mac")),
            "gateway_model": str(version.get("version", "") or "Ecowitt Gateway").strip(),
            "inventory": inventory,
            "rain_source": rain_source,
            "rain_reset_hour": rain_reset_hour_from_totals(rain_totals),
            "live_metric_count": len(normalize_ecowitt_livedata(live, rain_source=rain_source)),
        }
        self._discovery_cache = (monotonic(), deepcopy(result))
        self.last_status.update(
            state="online",
            label="Ecowitt gateway reachable",
            last_error="",
            last_success=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            gateway_id=result["gateway_id"],
            gateway_model=result["gateway_model"],
            inventory=inventory,
        )
        return result

    def discover_for_save(self, gateway_url: Any) -> dict[str, Any]:
        """Reuse a recent server-validated discovery when saving its gateway."""
        base_url = normalize_gateway_base_url(gateway_url)
        if self._discovery_cache is not None:
            discovered_at, discovery = self._discovery_cache
            if (
                discovery.get("gateway_url") == base_url
                and monotonic() - discovered_at <= DISCOVERY_CACHE_SECONDS
            ):
                return deepcopy(discovery)
        return self.discover(base_url)

    def status(self) -> dict[str, Any]:
        """Return safe configured and runtime gateway status."""
        return {
            **self.last_status,
            "enabled": self.settings.gateway_enabled,
            "gateway_url": self.settings.gateway_url,
            "gateway_id": self.settings.gateway_id,
            "gateway_model": self.settings.gateway_model,
            "inventory": self.settings.gateway_inventory,
            "poll_interval_seconds": self.settings.poll_interval_seconds,
        }

    def fetch(self) -> Dict[str, Any]:
        """Fetch one modern JSON or legacy query-string gateway payload."""
        if not self.settings.gateway_enabled:
            self.last_status.update(state="disabled", label="Ecowitt polling disabled")
            return {}
        parsed = urlsplit(self.settings.gateway_url)
        try:
            if parsed.path not in {"", "/"}:
                response = self.session.get(self.settings.gateway_url, timeout=10)
                response.raise_for_status()
                reading = self._parse_legacy_response(response.text)
            else:
                base_url = normalize_gateway_base_url(self.settings.gateway_url)
                reading = self._request(base_url, "get_livedata_info")
                if not isinstance(reading, dict):
                    raise EcowittGatewayError("Gateway live-data response schema is not supported.")
            self.last_status.update(
                state="online",
                label="Receiving Ecowitt weather data",
                last_error="",
                last_success=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
            return reading
        except (RequestException, EcowittGatewayError) as exc:
            self.last_status.update(state="offline", label="Ecowitt gateway unavailable", last_error=str(exc))
            return {}

    def _parse_legacy_response(self, payload: str) -> Dict[str, Any]:
        values: dict[str, Any] = {}
        for item in payload.strip().split("&"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            if value:
                values[key] = self._cast_legacy_value(key, value)
        return values

    @staticmethod
    def _cast_legacy_value(key: str, value: str) -> Any:
        numeric_keys = {
            "winddir", "windgust", "windsp", "windspeed", "tempf", "tempinf",
            "hum", "hum_in", "uv", "solarradiation", "baromin", "rainrate",
            "hourlyrainin", "dailyrainin",
        }
        if key in numeric_keys:
            try:
                return float(value)
            except ValueError:
                pass
        return value
