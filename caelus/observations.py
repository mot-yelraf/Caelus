"""Hardware-independent observations in Caelus's existing storage units."""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, TypedDict

logger = logging.getLogger(__name__)

# These are storage semantics, independent of the user's display-unit selection.
METRIC_UNITS = {
    **dict.fromkeys(
        (
            "temperature",
            "indoor_temperature",
            "dew_point",
            "wind_chill",
            "heat_index",
            "feels_like",
        ),
        "degF",
    ),
    **dict.fromkeys(("wind_speed", "wind_gust", "daily_max_wind"), "mph"),
    **dict.fromkeys(
        (
            "pressure",
            "absolute_pressure",
            "indoor_pressure",
            "indoor_absolute_pressure",
        ),
        "inHg",
    ),
    **dict.fromkeys(
        (
            "rain_total",
            "rain_increment",
            "rain_event",
            "rain_week",
            "rain_month",
            "rain_year",
            "rain_lifetime",
        ),
        "in",
    ),
    "rain_rate": "in/h",
    "humidity": "%",
    "indoor_humidity": "%",
    "wind_dir": "degree",
    "uv": "index",
    "solar_radiation": "W/m2",
    "light_intensity": "lux",
}


def validate_measurements(values: dict[str, Any]) -> dict[str, float | None]:
    """Keep known finite numeric metrics; missing and invalid values are unavailable."""
    result = {}
    for key, value in values.items():
        if key not in METRIC_UNITS:
            logger.warning("Ignoring unknown observation metric %s", key)
            continue
        if value is None:
            result[key] = None
            continue
        try:
            number = float(value)
            if isinstance(value, bool) or not math.isfinite(number):
                raise ValueError("not a finite measurement")
        except (TypeError, ValueError, OverflowError):
            logger.warning("Ignoring invalid observation metric %s", key)
            result[key] = None
            continue
        result[key] = number
    return result


def utc_time(value: datetime) -> datetime:
    """Require an aware device/receipt timestamp and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Observation timestamps must include a timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RainPolicy:
    """Describe a counter's scope; rain_total always retains its daily meaning."""

    kind: Literal["daily", "lifetime", "rolling", "interval", "none"] = "none"
    channel_id: str = "primary"
    timezone: str = "UTC"
    reset_hour: int = 0
    modulus: float | None = None

    def __post_init__(self) -> None:
        from zoneinfo import ZoneInfo

        if self.kind not in {"daily", "lifetime", "rolling", "interval", "none"}:
            raise ValueError("Unsupported rain policy")
        if not self.channel_id or not 0 <= self.reset_hour <= 23:
            raise ValueError("Invalid rain channel or reset hour")
        if self.kind == "rolling" and (self.modulus is None or not math.isfinite(self.modulus) or self.modulus <= 0):
            raise ValueError("A rolling counter requires a positive finite modulus")
        ZoneInfo(self.timezone)


@dataclass(frozen=True)
class ChannelCapability:
    """Describe a measurement channel, separate from sensor inventory discovery."""

    channel_id: str
    metrics: tuple[str, ...]
    primary: bool = True


@dataclass
class Observation:
    """One primary-station sample; pressure is relative unless explicitly absolute.

    Rain totals describe their named periods, rain_increment the elapsed interval,
    and wind_dir degrees clockwise from true north. None/missing means unavailable.
    """

    source_id: str
    observed_at: datetime
    received_at: datetime
    measurements: dict[str, Any]
    rain: RainPolicy = field(default_factory=RainPolicy)
    rain_counter: float | None = None
    rain_counter_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("An observation requires a stable source identity")
        self.observed_at = utc_time(self.observed_at)
        self.received_at = utc_time(self.received_at)
        self.measurements = validate_measurements(self.measurements)
        if self.rain_counter is not None:
            if isinstance(self.rain_counter, bool) or not math.isfinite(self.rain_counter) or self.rain_counter < 0:
                raise ValueError("Invalid raw rain counter")
            if self.rain_counter_at is None:
                raise ValueError("Raw rain counters require a sample timestamp")
            self.rain_counter_at = utc_time(self.rain_counter_at)


class StationHealth(TypedDict):
    """Dashboard health independent of gateway vendor or sensor family."""

    reporting: bool
    battery_status: Literal["OK", "LOW", "UNKNOWN"]


class SensorHealth(TypedDict):
    """Per-sensor health; signal retains the adapter's native scale."""

    sensor_id: str
    name: str
    reporting: bool
    battery_status: Literal["OK", "LOW", "UNKNOWN"]
    signal: float | None


class AdapterStatus(TypedDict):
    """Required generic status fields; adapters may add safe device diagnostics."""

    source_id: str
    connected: bool
    observation_fresh: bool
    station: StationHealth
    sensors: list[SensorHealth]


class WeatherAdapter(Protocol):
    """Read bounded, synchronous normalized samples; return None on unavailable data.

    Discovery is optional and is not part of this acquisition contract. Status
    returns safe public diagnostics, source connectivity, freshness and sensor health.
    status() and capabilities() read local state only and must never perform I/O.
    """

    def read(self) -> Observation | None: ...
    def capabilities(self) -> tuple[ChannelCapability, ...]: ...
    def status(self) -> AdapterStatus: ...
