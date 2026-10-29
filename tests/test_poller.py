import asyncio
import threading
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from caelus.gateway import map_gateway_reading
from caelus.adapters import EcowittAdapter
from caelus.rain import counter_identity
from caelus.observations import RainPolicy
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
    state.weather_adapter = EcowittAdapter(state.settings, state.gateway)
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


@pytest.mark.parametrize('failure', ['empty', 'fetch', 'get_latest', 'log_reading', 'prune_readings'])
def test_background_poller_recovers_from_gateway_and_storage_failures(failure):
    async def exercise():
        poller = make_poller()
        owner = poller.gateway if failure in {'empty', 'fetch'} else poller.data_logger
        method = 'fetch' if failure == 'empty' else failure
        original = getattr(owner, method)
        calls = 0

        def fail_once(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                if failure == 'empty':
                    return {}
                raise sqlite3.OperationalError('temporary failure')
            return original(*args)

        setattr(owner, method, fail_once)
        await poller.start()
        try:
            for _ in range(100):
                if calls >= 3:
                    break
                await asyncio.sleep(0.005)
        finally:
            await poller.stop()
        assert calls >= 3
        assert poller.data_logger.readings
        assert poller.task.exception() is None

    asyncio.run(exercise())


def test_fresh_process_recovery_persists_normalized_readings(monkeypatch, tmp_path):
    import requests
    from caelus import gateway as module
    from caelus.data_logger import DataLogger
    from caelus.settings import AppSettings

    class Session:
        @staticmethod
        def get(*args, **kwargs):
            raise requests.ConnectionError('No route to host')

    def recover(base, endpoint, params):
        if endpoint == 'get_livedata_info':
            return {'common_list': [
                {'id': '0x02', 'val': '10', 'unit': 'C'},
                {'id': '0x0B', 'val': '0 mph'},
            ]}
        return []

    monkeypatch.setattr(module, 'request_in_fresh_process', recover)
    settings = AppSettings(gateway_enabled=True, gateway_url='http://gw.local')
    data_logger = DataLogger(str(tmp_path / 'recovered.db'))
    state = SimpleNamespace(
        settings=settings, gateway=module.EcowittGateway(settings, session=Session),
        data_logger=data_logger,
    )
    state.weather_adapter = EcowittAdapter(settings, state.gateway)
    poller = GatewayPoller(SimpleNamespace(state=state))
    assert poller.poll_once() is None
    assert poller.poll_once() is None
    reading = poller.poll_once()
    assert reading['temperature'] == 50.0
    assert reading['wind_speed'] == 0.0
    stored = data_logger.get_latest()
    assert stored['temperature'] == 50.0
    assert stored['wind_speed'] == 0.0


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


def test_rain_counter_reset_boundary_is_checked_before_subtraction() -> None:
    poller = make_poller()
    poller.settings.timezone = "UTC"
    poller.settings.gateway_rain_reset_hour = 0
    reading = {"rain_total": 0.2}

    poller._add_rain_increment(
        reading,
        {"timestamp": "2026-08-12T23:59:00", "rain_total": 0.1},
        datetime(2026, 8, 13, 0, 1),
    )

    assert reading["rain_increment"] == 0.2


def test_overlapping_poll_requests_are_serialized() -> None:
    poller = make_poller()
    poller.gateway.fetch = lambda: {"rain": [{"id": "0x10", "val": "1.1 in"}]}
    poller.settings.gateway_rain_source = "traditional"
    poller.settings.timezone = "UTC"
    poller.settings.gateway_rain_reset_hour = 0
    poller.data_logger.previous = {
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "rain_total": 1.0,
        "rain_counter_id": counter_identity("ecowitt::", RainPolicy(kind="daily", channel_id="traditional")),
    }
    entered = threading.Event()
    release = threading.Event()

    def latest():
        if not entered.is_set():
            entered.set()
            release.wait(timeout=2)
        elif poller.data_logger.readings:
            timestamp, reading = poller.data_logger.readings[-1]
            return {"timestamp": timestamp.isoformat(), **reading}
        return poller.data_logger.previous

    poller.data_logger.get_latest = latest
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(poller.poll_once)
        assert entered.wait(timeout=2)
        second = pool.submit(poller.poll_once)
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert [reading["rain_increment"] for _, reading in poller.data_logger.readings] == [
        0.1,
        0.0,
    ]


@pytest.mark.parametrize('modern', [False, True])
def test_poll_persists_locally_derived_temperatures(tmp_path, modern):
    from caelus.data_logger import DataLogger

    poller = make_poller()
    poller.data_logger = DataLogger(str(tmp_path / 'weather.db'))
    if modern:
        payload = {'common_list': [
            {'id': '0x02', 'val': '20 F'},
            {'id': '0x07', 'val': '70%'},
            {'id': '0x0B', 'val': '15 mph'},
            {'id': '0x04', 'val': '99 F'},
        ]}
    else:
        payload = {'tempf': 20, 'hum': 70, 'windsp': 15}
    poller.gateway.fetch = lambda: payload
    reading = poller.poll_once()
    latest = poller.data_logger.get_latest()
    assert reading['feels_like'] == latest['feels_like'] == pytest.approx(5.89, abs=0.01)
    assert reading['wind_chill'] == latest['wind_chill'] == pytest.approx(6.22, abs=0.01)
    payload.clear()
    payload.update({'tempf': 90, 'hum': 70, 'windsp': 0})
    poller.poll_once()
    latest = poller.data_logger.get_latest()
    assert latest['feels_like'] == pytest.approx(102.75, abs=0.01)
    assert latest['wind_chill'] is None


def test_cool_humid_reading_records_apparent_temperature(tmp_path):
    from caelus.data_logger import DataLogger

    poller = make_poller()
    poller.data_logger = DataLogger(str(tmp_path / 'weather.db'))
    payload = {'tempf': 41, 'hum': 91, 'windsp': 0.2}
    poller.gateway.fetch = lambda: payload
    poller.poll_once()
    latest = poller.data_logger.get_latest()
    assert latest['feels_like'] == pytest.approx(38.40, abs=0.01)
    assert latest['wind_chill'] is None
    payload.pop('windsp')
    poller.poll_once()
    assert poller.data_logger.get_latest()['feels_like'] is None


def test_poll_derives_and_persists_heat_index_without_gateway_value(tmp_path):
    from caelus.data_logger import DataLogger

    poller = make_poller()
    poller.data_logger = DataLogger(str(tmp_path / 'weather.db'))
    payload = {'tempf': 90, 'hum': 70, 'windsp': 0}
    poller.gateway.fetch = lambda: payload
    reading = poller.poll_once()
    assert reading['heat_index'] == pytest.approx(105.92, abs=0.01)
    assert poller.data_logger.get_latest()['heat_index'] == reading['heat_index']
    payload['tempf'] = 41
    poller.poll_once()
    assert poller.data_logger.get_latest()['heat_index'] is None
