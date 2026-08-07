import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

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

    async def start(self) -> None:
        if self.task is not None and not self.task.done():
            return
        self.stop_event.clear()
        self.task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self.stop_event.set()
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
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=self.settings.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    def poll_once(self) -> dict[str, Any] | None:
        """Fetch, persist, and return one normalized gateway reading."""
        reading = self.gateway.fetch()
        if not reading:
            return None

        mapped = map_gateway_reading(reading)
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
        self.data_logger.log_reading(timestamp, mapped)
        self.data_logger.prune_readings(self.settings.retention_days)
        return mapped
