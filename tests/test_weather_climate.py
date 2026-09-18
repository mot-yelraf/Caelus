"""Verify archive aggregation, persistence and non-blocking station-local selection."""

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import threading

import pytest

from caelus import weather_climate as climate
from caelus.settings import AppSettings

END = date(2026, 9, 13)


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setattr(climate, "latest_history_date", lambda: END)
    days = [climate.START + timedelta(days=i) for i in range((END - climate.START).days + 1)]
    return {"daily_units": climate.WeatherClimateService.expected_units, "daily": {
        "time": [day.isoformat() for day in days],
        "temperature_2m_mean": [day.year - 1990 for day in days],
        "relative_humidity_2m_mean": [50] * len(days),
        "wind_speed_10m_mean": [0] * len(days),
        "rain_sum": [4 if day.year % 2 == 0 else 0 for day in days],
    }}


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.fail = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.fail:
            raise OSError("offline")
        return self

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def settings():
    return AppSettings(latitude=40, longitude=-105, timezone="America/Denver")


def test_calendar_averages_and_leap_samples(history):
    result = climate.summarize_weather_history(history, END)
    assert len(result) == 366
    assert result['09-13']['samples'] == 36
    assert result['09-14']['samples'] == 35
    assert result['09-13']['temperature_c'] == 18.5
    assert result['09-13']['rain_mm'] == 2
    assert result['02-29']['samples'] == 9
    assert result['09-13']['wind_kmh'] == 0


@pytest.mark.parametrize('field,value', [('rain_sum', None), ('rain_sum', -1),
    ('relative_humidity_2m_mean', 101), ('wind_speed_10m_mean', True),
    ('temperature_2m_mean', float('nan'))])
def test_invalid_values_rejected(history, field, value):
    history['daily'][field][10] = value
    with pytest.raises(ValueError):
        climate.summarize_weather_history(history, END)


def test_duplicate_dates_rejected(history):
    history['daily']['time'][10] = history['daily']['time'][9]
    with pytest.raises(ValueError):
        climate.summarize_weather_history(history, END)


def test_cache_timezone_reuse_outage_and_location_change(history, tmp_path):
    async def run():
        session = Session(history)
        path = tmp_path / 'climate.json'
        service = climate.WeatherClimateService(path, session)
        station = settings()
        assert service.snapshot(station)['status'] == 'warming'
        await service.task
        utc = datetime(2026, 9, 19, 1, tzinfo=timezone.utc)
        result = service.snapshot(station, now=utc)
        assert result['date'] == '2026-09-18'
        assert 'calendar_averages' not in result
        assert service.snapshot(station, now=utc + timedelta(hours=8))['date'] == '2026-09-19'
        assert session.calls[0][1]['params']['models'] == 'era5'
        restored = climate.WeatherClimateService(path, session)
        restored.snapshot(station)
        await restored.task
        assert restored.snapshot(station, now=utc)['averages'] == result['averages']
        assert len(session.calls) == 1
        # Refresh failure retains last-good data with an explicit stale state.
        climate.latest_history_date = lambda: END + timedelta(days=1)
        session.fail = True
        restored.next_check = 0
        restored.snapshot(station)
        await restored.task
        assert restored.snapshot(station)['stale'] is True
        station.longitude = -104
        assert restored.snapshot(station)['status'] == 'warming'
        await restored.task
        assert restored.snapshot(station)['status'] == 'unavailable'
        await service.close()
        await restored.close()
    asyncio.run(run())


def test_publication_tail_units_and_corrupt_cache(history, tmp_path):
    session = Session(history)
    service = climate.WeatherClimateService(tmp_path / 'climate.json', session)
    location = {'latitude': 40, 'longitude': -105, 'timezone': 'America/Denver'}
    for field in climate.VARIABLES:
        history['daily'][field][-2:] = [None, None]
    result = service._fetch(location, END)
    assert result['end_date'] == '2026-09-11'
    assert result['requested_end_date'] == END.isoformat()
    service._write_cache(result)
    assert service._read_cache(location) == result
    result['calendar_averages']['09-18']['samples'] = 0
    service._write_cache(result)
    assert service._read_cache(location) is None
    for invalid in ['[]', '{broken', json.dumps({'cache_format': 99})]:
        service.cache_path.write_text(invalid)
        assert service._read_cache(location) is None
    history['daily']['rain_sum'][-8:] = [None] * 8
    with pytest.raises(ValueError, match='week'):
        service._fetch(location, END)
    history['daily_units'] = {}
    with pytest.raises(ValueError, match='units'):
        service._fetch(location, END)


def test_inflight_location_change_cannot_publish_old_averages(history, tmp_path):
    async def run():
        started, release = threading.Event(), threading.Event()
        service = climate.WeatherClimateService(tmp_path / 'climate.json', Session(history))
        fetch = service._fetch
        def delayed(location, end):
            started.set()
            release.wait(timeout=5)
            return fetch(location, end)
        service._fetch = delayed
        station = settings()
        service.snapshot(station)
        await asyncio.to_thread(started.wait, 5)
        old_task = service.task
        station.longitude = -104
        assert service.snapshot(station)['status'] == 'warming'
        release.set()
        await old_task
        assert service.payload['status'] == 'warming'
        service.snapshot(station)
        await service.task
        assert service.snapshot(station)['location']['longitude'] == -104
        await service.close()
    asyncio.run(run())


def test_shutdown_cancels_background_task_without_publishing(tmp_path):
    async def run():
        service = climate.WeatherClimateService(tmp_path / 'climate.json')
        entered = asyncio.Event()
        async def pending(location):
            entered.set()
            await asyncio.Event().wait()
        service._load = pending
        service.snapshot(settings())
        await entered.wait()
        await service.close()
        assert service.task.cancelled()
        assert not service.cache_path.exists()
    asyncio.run(run())


def test_location_change_during_cache_write_refreshes_without_hour_delay(history, tmp_path):
    async def run():
        service = climate.WeatherClimateService(tmp_path / 'climate.json', Session(history))
        started, release = threading.Event(), threading.Event()
        write = service._write_cache
        def delayed(payload):
            started.set()
            release.wait(timeout=5)
            write(payload)
        service._write_cache = delayed
        station = settings()
        service.snapshot(station)
        await asyncio.to_thread(started.wait, 5)
        old_task = service.task
        station.timezone = 'UTC'
        assert service.snapshot(station)['status'] == 'warming'
        release.set()
        await old_task
        assert service.next_check == 0
        service.snapshot(station)
        assert service.task is not old_task
        await service.task
        assert service.snapshot(station)['location']['timezone'] == 'UTC'
        await service.close()
    asyncio.run(run())
