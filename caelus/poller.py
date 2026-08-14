import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI

from caelus.gateway import map_gateway_reading

logger = logging.getLogger(__name__)


class GatewayPoller:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.settings = app.state.settings
        self.gateway = app.state.gateway
        self.data_logger = app.state.data_logger
        self.task: asyncio.Task[Any] | None = None
        self.stop_event = asyncio.Event()
        self.schedule_event = asyncio.Event()

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
        """Fetch, persist, and return one normalized gateway reading."""
        reading = self.gateway.fetch()
        if not reading:
            return None

        mapped = map_gateway_reading(
            reading,
            rain_source=getattr(self.settings, "gateway_rain_source", "traditional"),
        )
        if not mapped:
            return None
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
        latest_reader = getattr(self.data_logger, "get_latest", None)
        latest = latest_reader() if callable(latest_reader) else None
        self._add_rain_increment(mapped, latest, timestamp)
        self.data_logger.log_reading(timestamp, mapped)
        self.data_logger.prune_readings(self.settings.retention_days)
        return mapped

    def _add_rain_increment(
        self,
        reading: dict[str, Any],
        previous: dict[str, Any] | None,
        timestamp: datetime,
    ) -> None:
        """Calculate interval rain without treating a daily counter as rainfall."""
        current = reading.get("rain_total")
        prior = previous.get("rain_total") if previous else None
        if current is None or prior is None:
            return
        try:
            current_total = float(current)
            prior_total = float(prior)
        except (TypeError, ValueError):
            return
        if current_total >= prior_total:
            reading["rain_increment"] = round(current_total - prior_total, 3)
            return

        crossed_reset = False
        try:
            prior_time = datetime.fromisoformat(str(previous.get("timestamp")))
            if prior_time.tzinfo is None:
                prior_time = prior_time.replace(tzinfo=timezone.utc)
            current_time = timestamp.replace(tzinfo=timezone.utc)
            local_timezone = ZoneInfo(getattr(self.settings, "timezone", "UTC"))
            prior_local = prior_time.astimezone(local_timezone)
            current_local = current_time.astimezone(local_timezone)
            reset_hour = int(getattr(self.settings, "gateway_rain_reset_hour", 0))
            reset = prior_local.replace(
                hour=max(0, min(23, reset_hour)), minute=0, second=0, microsecond=0
            )
            if reset <= prior_local:
                reset += timedelta(days=1)
            crossed_reset = reset <= current_local
        except (TypeError, ValueError):
            pass
        reading["rain_increment"] = round(current_total, 3) if crossed_reset else 0.0
