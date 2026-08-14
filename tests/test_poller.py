import asyncio
from datetime import datetime
from types import SimpleNamespace

from caelus.gateway import map_gateway_reading
from caelus.poller import GatewayPoller


class FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return {"windsp": 0.0, "winddir": 0.0, "tempf": 32.0}


class FakeDataLogger:
    def __init__(self) -> None:
        self.readings = []

    def log_reading(self, timestamp, reading) -> None:
        self.readings.append((timestamp, reading))

    def get_latest(self):
        return None

    def prune_readings(self, retention_days) -> None:
        pass


def make_poller(interval: float = 0.01) -> GatewayPoller:
    state = SimpleNamespace(
        settings=SimpleNamespace(
            poll_interval_seconds=interval,
            retention_days=30,
        ),
        gateway=FakeGateway(),
        data_logger=FakeDataLogger(),
    )
    return GatewayPoller(SimpleNamespace(state=state))


def test_background_poller_repeats_and_stops_cleanly() -> None:
    async def exercise() -> None:
        poller = make_poller()
        await poller.start()
        for _ in range(100):
            if poller.gateway.calls >= 2:
                break
            await asyncio.sleep(0.005)
        await poller.stop()

        assert poller.gateway.calls >= 2
        assert poller.task is not None
        assert poller.task.done()
        assert poller.task.exception() is None

    asyncio.run(exercise())


def test_reset_schedule_applies_a_changed_interval_immediately() -> None:
    async def exercise() -> None:
        poller = make_poller(interval=10)
        await poller.start()
        for _ in range(100):
            if poller.gateway.calls >= 1:
                break
            await asyncio.sleep(0.005)

        poller.settings.poll_interval_seconds = 0.01
        poller.reset_schedule()
        for _ in range(100):
            if poller.gateway.calls >= 2:
                break
            await asyncio.sleep(0.005)
        await poller.stop()

        assert poller.gateway.calls >= 2

    asyncio.run(exercise())


def test_zero_gateway_values_are_preserved() -> None:
    reading = map_gateway_reading({"windsp": 0.0, "winddir": 0.0})

    assert reading["wind_speed"] == 0.0
    assert reading["wind_dir"] == 0


def test_daily_rain_counter_is_stored_separately_from_interval_rain() -> None:
    poller = make_poller()
    reading = {"rain_total": 1.5}

    poller._add_rain_increment(
        reading,
        {"timestamp": "2026-08-12T12:00:00", "rain_total": 1.25},
        datetime(2026, 8, 12, 13, 0),
    )

    assert reading["rain_total"] == 1.5
    assert reading["rain_increment"] == 0.25


def test_unexplained_rain_counter_reset_is_conservative() -> None:
    poller = make_poller()
    reading = {"rain_total": 0.1}

    poller._add_rain_increment(
        reading,
        {"timestamp": "2026-08-12T12:00:00", "rain_total": 1.25},
        datetime(2026, 8, 12, 13, 0),
    )

    assert reading["rain_increment"] == 0.0
