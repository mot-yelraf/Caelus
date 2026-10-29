"""Wire independent station histories and acquisition lifecycles at one location."""

from builtins import BaseExceptionGroup
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from caelus.adapters import create_weather_adapter
from caelus.data_logger import DataLogger
from caelus.poller import GatewayPoller


class StationSettings:
    """Expose the correct persistence interval while retaining shared live settings."""

    def __init__(self, settings: Any, key: str) -> None:
        self.settings, self.key = settings, key

    @property
    def poll_interval_seconds(self) -> int:
        if self.key == "davis_vue":
            return self.settings.davis_poll_interval_seconds
        if self.key in {"acurite_usb", "wmr100_usb"}:
            return getattr(self.settings, f"{self.key.removesuffix('_usb')}_poll_interval_seconds")
        return self.settings.poll_interval_seconds

    def __getattr__(self, name):
        return getattr(self.settings, name)


@dataclass
class StationRuntime:
    """One source's adapter, logger, and persistence poller; no cross-source merging."""

    key: str
    name: str
    adapter: Any
    data_logger: DataLogger
    poller: GatewayPoller


def build_stations(app, data_dir) -> dict[str, StationRuntime]:
    """Preserve the original Ecowitt database and allocate independent USB station histories."""
    settings = app.state.settings
    stations = {}
    for key, name, logger in (
        ("ecowitt", "Ecowitt", app.state.data_logger),
        (
            "acurite_usb",
            "AcuRite",
            DataLogger(str(data_dir / "acurite.db")),
        ),
        ("wmr100_usb", "Oregon Scientific", DataLogger(str(data_dir / "wmr100.db"))),
        ("davis_vue", "Davis Vantage Vue", DataLogger(str(data_dir / "davis.db"))),
    ):
        adapter = create_weather_adapter(settings, kind=key)
        state = SimpleNamespace(
            settings=StationSettings(settings, key),
            weather_adapter=adapter,
            data_logger=logger,
            station_lock=app.state.station_lock,
        )
        if key == "ecowitt":
            state.gateway = adapter.gateway
        poller = GatewayPoller(SimpleNamespace(state=state))
        stations[key] = StationRuntime(key, name, adapter, logger, poller)
    return stations


async def start_station(runtime: StationRuntime) -> None:
    """Start an adapter's optional sampler before its history poller."""
    start = getattr(runtime.adapter, "start", None)
    if start is not None:
        await start()
    try:
        await runtime.poller.start()
    except BaseException:
        stop = getattr(runtime.adapter, "stop", None)
        if stop is not None:
            await stop()
        raise


async def stop_station(runtime: StationRuntime) -> None:
    """Drain persistence before stopping the optional bounded sampler."""
    try:
        await runtime.poller.stop()
    finally:
        stop = getattr(runtime.adapter, "stop", None)
        if stop is not None:
            await stop()


async def stop_stations(runtimes) -> None:
    """Attempt every station's cleanup even when one adapter fails to stop."""
    errors = []
    for runtime in reversed(runtimes):
        try:
            await stop_station(runtime)
        except BaseException as exc:
            errors.append(exc)
    if errors:
        raise BaseExceptionGroup("Station shutdown failed", errors)
