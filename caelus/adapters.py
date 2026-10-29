"""Explicit weather adapter selection and the existing Ecowitt implementation."""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, cast

from caelus.gateway import EcowittGateway, map_gateway_reading, ws69_status
from caelus.observations import (
    AdapterStatus,
    ChannelCapability,
    METRIC_UNITS,
    Observation,
    RainPolicy,
    WeatherAdapter,
)
from caelus.settings import AppSettings


class EcowittAdapter:
    """Contain Ecowitt transport, parsing, identity and rain-counter policy."""

    def __init__(self, settings: AppSettings, gateway: Any = None) -> None:
        self.settings = settings
        self.gateway = gateway if gateway is not None else EcowittGateway(settings)

    @property
    def source_id(self) -> str:
        """Include the endpoint so manually changing a saved address resets counters."""
        identity = getattr(self.settings, "gateway_id", "")
        endpoint = getattr(self.settings, "gateway_url", "").rstrip("/")
        return f"ecowitt:{identity}:{endpoint}"

    def read(self) -> Observation | None:
        """Read and normalize through the canonical Ecowitt mapper."""
        raw = self.gateway.fetch()
        if not raw:
            return None
        now = datetime.now(timezone.utc)
        rain_source = getattr(self.settings, "gateway_rain_source", "traditional")
        observation = Observation(
            source_id=self.source_id,
            observed_at=now,
            received_at=now,
            measurements=map_gateway_reading(raw, rain_source=rain_source),
            rain=RainPolicy(
                kind="none" if rain_source == "none" else "daily",
                channel_id=rain_source,
                timezone=getattr(self.settings, "timezone", "UTC"),
                reset_hour=getattr(self.settings, "gateway_rain_reset_hour", 0),
            ),
        )
        return (
            observation
            if any(value is not None for value in observation.measurements.values())
            else None
        )

    def capabilities(self) -> tuple[ChannelCapability, ...]:
        """Declare parser-supported primary fields, not every discovered sensor's data."""
        return (
            ChannelCapability(
                "primary",
                tuple(
                    key
                    for key in METRIC_UNITS
                    if key not in {"feels_like", "rain_increment"}
                ),
            ),
        )

    def status(self) -> AdapterStatus:
        """Report connectivity separately from fresh weather and individual sensor health."""
        status = self.gateway.status()
        fresh = self.gateway.observation_is_fresh()
        sensors = []
        for sensor in status.get("inventory", []):
            reporting = fresh and sensor.get("signal", 0) > 0
            binary = ws69_status([sensor], online=reporting)
            sensors.append(
                {
                    "sensor_id": str(sensor.get("id", "")),
                    "name": sensor.get("name", "Sensor"),
                    "reporting": reporting,
                    "battery_status": binary["battery_status"],
                    "signal": sensor.get("signal"),
                }
            )
        batteries = [
            sensor["battery_status"] for sensor in sensors if sensor["reporting"]
        ]
        battery = (
            "LOW"
            if "LOW" in batteries
            else (
                "OK"
                if batteries and all(value == "OK" for value in batteries)
                else "UNKNOWN"
            )
        )
        return cast(
            AdapterStatus,
            {
                **status,
                "source_id": self.source_id,
                "connected": status.get("state") == "online"
                and status.get("enabled", False),
                "observation_fresh": fresh,
                "station": {"reporting": fresh, "battery_status": battery},
                "sensors": sensors,
                "capabilities": [asdict(channel) for channel in self.capabilities()],
            },
        )


def create_weather_adapter(settings: AppSettings, *, kind: str | None = None) -> WeatherAdapter:
    """Build the configured adapter; add new station families explicitly here."""
    selected = kind or settings.weather_adapter
    if selected == "ecowitt":
        return EcowittAdapter(settings)
    if selected == "acurite_usb":
        from caelus.acurite import AcuRiteUsbAdapter
        return AcuRiteUsbAdapter(settings)
    raise ValueError(f"Unsupported weather adapter: {selected}")
