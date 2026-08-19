import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SCENE_THEMES = {"garden", "island", "river", "desert"}
LEGACY_THEME_MAP = {"light": "garden", "dark": "river", "midnight": "island"}
ALLOWED_THEMES = SCENE_THEMES | set(LEGACY_THEME_MAP)
ALLOWED_EXPORT_FORMATS = {"csv", "json"}
ALLOWED_FORECAST_PROVIDERS = {"met_no", "open_meteo", "us"}
ALLOWED_METRIC_DISPLAY_STYLES = {"graph24hr", "graph6hr", "gauge"}


def normalize_theme(value: str) -> str:
    """Return a supported scene theme, migrating legacy palette names."""
    from caelus.theme_manager import is_custom_theme_selection

    if is_custom_theme_selection(value):
        return value
    if value not in ALLOWED_THEMES:
        raise ValueError("unsupported theme")
    return LEGACY_THEME_MAP.get(value, value)


def validate_gateway_url(value: str) -> str:
    """Validate a configurable HTTP(S) Ecowitt gateway URL."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("gateway URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError("gateway URL cannot contain credentials or a fragment")
    return value.strip()


def validate_windy_iframe_url(value: str) -> str:
    """Restrict the dashboard iframe to Windy's HTTPS embed endpoint."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "embed.windy.com"
        or parsed.path != "/embed2.html"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("Windy URL must use https://embed.windy.com/embed2.html")
    return value.strip()


def build_windy_iframe_url(value: str, latitude: float, longitude: float) -> str:
    """Center the supported Windy embed and enable its station marker."""
    validated = validate_windy_iframe_url(value)
    parsed = urlsplit(validated)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    coordinate = {"lat": f"{latitude:.4f}", "lon": f"{longitude:.4f}"}
    query.update(
        coordinate,
        detailLat=coordinate["lat"],
        detailLon=coordinate["lon"],
        marker="true",
        location="coordinates",
        type="map",
        overlay="radar",
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


@dataclass
class AppSettings:
    settings_path: ClassVar[Path] = Path(__file__).resolve().parent.parent / "data" / "settings.json"
    gateway_enabled: bool = True
    gateway_url: str = "http://192.168.1.100"
    gateway_id: str = ""
    gateway_model: str = ""
    gateway_inventory: list[dict[str, Any]] = field(default_factory=list)
    gateway_rain_source: str = "traditional"
    gateway_rain_reset_hour: int = 0
    poll_interval_seconds: int = 300
    location_name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    use_ip_location: bool = True
    timezone: str = "UTC"
    location_source: str = ""
    location_provider: str = ""
    forecast_provider: str = "met_no"
    theme: str = "garden"
    unit_system: str = "imperial"
    pressure_unit: str = "auto"
    metric_display_styles: dict[str, str] = field(default_factory=dict)
    retention_days: int = 366
    export_format: str = "csv"
    windy_iframe_url: str = "https://embed.windy.com/embed2.html"

    @classmethod
    def load(cls, theme_manager: Any | None = None) -> "AppSettings":
        cls.settings_path.parent.mkdir(parents=True, exist_ok=True)
        if not cls.settings_path.exists():
            return cls()
        try:
            with cls.settings_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise TypeError("settings document must be an object")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not load settings from %s: %s", cls.settings_path, exc)
            return cls()

        known_fields = {item.name for item in fields(cls)}
        unknown_fields = sorted(set(data) - known_fields)
        if unknown_fields:
            logger.warning("Ignoring unknown settings: %s", ", ".join(unknown_fields))

        settings = cls()
        for name in known_fields & set(data):
            try:
                setattr(settings, name, cls._validate_value(name, data[name]))
            except (TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid setting %s: %s", name, exc)
        # Older releases allowed pressure to override the unit preset. The
        # control no longer exists, so migrate all loaded values to automatic.
        settings.pressure_unit = "auto"
        if theme_manager is not None and str(settings.theme).startswith("custom:"):
            settings.theme = theme_manager.normalize_selection(settings.theme)
        return settings

    @staticmethod
    def _validate_value(name: str, value: Any) -> Any:
        if name == "gateway_url":
            return validate_gateway_url(str(value))
        if name == "windy_iframe_url":
            return validate_windy_iframe_url(str(value))
        if name == "theme":
            return normalize_theme(value)
        if name == "unit_system":
            if value not in {"imperial", "metric"}:
                raise ValueError("unsupported display unit system")
            return value
        if name == "pressure_unit":
            if value not in {"auto", "hpa", "inhg"}:
                raise ValueError("unsupported pressure display unit")
            return value
        if name == "metric_display_styles":
            if not isinstance(value, dict):
                raise TypeError("must be an object")
            result = {}
            for metric, style in value.items():
                if not isinstance(metric, str) or style not in ALLOWED_METRIC_DISPLAY_STYLES:
                    raise ValueError("unsupported metric display style")
                result[metric] = style
            return result
        if name == "export_format":
            if value not in ALLOWED_EXPORT_FORMATS:
                raise ValueError("unsupported export format")
            return value
        if name == "forecast_provider":
            if value not in ALLOWED_FORECAST_PROVIDERS:
                raise ValueError("unsupported weather forecast provider")
            return value
        if name in {"poll_interval_seconds", "retention_days", "gateway_rain_reset_hour"}:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("must be an integer")
            if name == "poll_interval_seconds":
                return min(max(60, value), 3600)
            if name == "gateway_rain_reset_hour":
                return min(max(0, value), 23)
            return min(max(30, value), 366)
        if name in {"latitude", "longitude"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("must be numeric")
            numeric = float(value)
            limit = 90 if name == "latitude" else 180
            if not -limit <= numeric <= limit:
                raise ValueError(f"must be between {-limit} and {limit}")
            return numeric
        if name in {"use_ip_location", "gateway_enabled"}:
            if not isinstance(value, bool):
                raise TypeError("must be a boolean")
            return value
        if name in {
            "location_name", "location_source", "location_provider", "gateway_id",
            "gateway_model",
            "unit_system", "pressure_unit",
        }:
            if not isinstance(value, str):
                raise TypeError("must be a string")
            return value
        if name == "gateway_inventory":
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise TypeError("must be a list of sensor records")
            return value
        if name == "gateway_rain_source":
            if value not in {"none", "traditional", "piezo"}:
                raise ValueError("unsupported Ecowitt rain source")
            return value
        if name == "timezone":
            if not isinstance(value, str):
                raise TypeError("must be a string")
            try:
                ZoneInfo(value)
            except Exception as exc:
                raise ValueError("unknown timezone") from exc
            return value
        return value

    def save(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        with self.settings_path.open("w", encoding="utf-8") as handle:
            json.dump(self.__dict__, handle, indent=2)
