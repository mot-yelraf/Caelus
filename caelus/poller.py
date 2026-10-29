import asyncio
import logging
import threading
from datetime import datetime
from typing import Any

from fastapi import FastAPI

from caelus.observations import RainPolicy
from caelus.rain import add_rain_increment, process_rain, add_recorded_daily_rain
from caelus.metrics import calculate_barometric_pressure, calculate_feels_like, calculate_heat_index, calculate_wind_chill

logger = logging.getLogger(__name__)


class GatewayPoller:
    """Schedule normalized primary-station acquisition and shared persistence work."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.settings = app.state.settings
        self.gateway = getattr(app.state, "gateway", None)
        self.adapter = app.state.weather_adapter
        self.data_logger = app.state.data_logger
        self.task: asyncio.Task[Any] | None = None
        self.stop_event = asyncio.Event()
        self.schedule_event = asyncio.Event()
        self._poll_lock = getattr(app.state, "station_lock", None) or threading.RLock()

    async def start(self) -> None:
        if self.task is not None and not self.task.done():
            return
        self.stop_event.clear()
        self.schedule_event.clear()
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self.stop_event.set()
        self.schedule_event.set()
        if self.task is not None:
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.poll_once)
            except Exception:
                logger.exception("Gateway polling failed")
            while not self.stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self.schedule_event.wait(),
                        timeout=self.settings.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    break
                self.schedule_event.clear()

    def reset_schedule(self) -> None:
        """Restart the wait using the current polling interval."""
        self.schedule_event.set()

    def poll_once(self) -> dict[str, Any] | None:
        """Acquire, enrich, persist, and return one normalized adapter observation."""
        with self._poll_lock:
            observation = self.adapter.read()
            if observation is None:
                return None
            mapped = dict(observation.measurements)
            if not any(value is not None for value in mapped.values()):
                return None
            if observation.source_id.startswith("acurite:"):
                mapped["pressure"] = calculate_barometric_pressure(
                    mapped.get("indoor_absolute_pressure"), getattr(self.settings, "altitude_m", None)
                )
            mapped["feels_like"] = calculate_feels_like(
                mapped.get("temperature"), mapped.get("humidity"), mapped.get("wind_speed")
            )
            mapped["heat_index"] = calculate_heat_index(mapped.get("temperature"), mapped.get("humidity"))
            mapped["wind_chill"] = calculate_wind_chill(mapped.get("temperature"), mapped.get("wind_speed"))
            timestamp = observation.observed_at.replace(tzinfo=None)
            latest_reader = getattr(self.data_logger, "get_latest", None)
            latest = latest_reader() if callable(latest_reader) else None
            counter_id = process_rain(observation, latest)
            add_recorded_daily_rain(observation, latest)
            if "rain_total" in observation.measurements:
                mapped["rain_total"] = observation.measurements["rain_total"]
            if observation.measurements.get("rain_increment") is not None:
                mapped["rain_increment"] = observation.measurements["rain_increment"]
            mapped.update(
                source_id=observation.source_id,
                observed_at=observation.observed_at.isoformat(),
                received_at=observation.received_at.isoformat(),
                rain_counter_id=counter_id,
                rain_counter_value=observation.rain_counter,
                rain_counter_at=observation.rain_counter_at.isoformat() if observation.rain_counter_at else None,
            )
            self.data_logger.log_reading(timestamp, mapped)
            self.data_logger.prune_readings(self.settings.retention_days)
            return mapped

    def _add_rain_increment(
        self,
        reading: dict[str, Any],
        previous: dict[str, Any] | None,
        timestamp: datetime,
    ) -> None:
        """Compatibility entrypoint for daily rain processing; acquisition uses its policy."""
        add_rain_increment(reading, previous, timestamp, RainPolicy(
            kind="daily", timezone=getattr(self.settings, "timezone", "UTC"),
            reset_hour=getattr(self.settings, "gateway_rain_reset_hour", 0),
        ))
