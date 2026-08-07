import asyncio
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


def test_zero_gateway_values_are_preserved() -> None:
    reading = map_gateway_reading({"windsp": 0.0, "winddir": 0.0})

    assert reading["wind_speed"] == 0.0
    assert reading["wind_dir"] == 0
