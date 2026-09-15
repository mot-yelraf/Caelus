"""Portable Sensorius artwork and forecast contract regression cases."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import caelus.forecast as forecast
from caelus.settings import AppSettings

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / 'tests/fixtures/forecast-contract-v1.json').read_text())


def test_authoritative_asset_hashes():
    directory = ROOT / 'static/weather-glyphs'
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert len(list(directory.glob('*.svg'))) == 9
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('case', CONTRACT['wmo'])
def test_wmo_contract(case):
    assert forecast._wmo_condition(case['code']) == case['condition']


@pytest.mark.parametrize('case', CONTRACT['met'])
def test_met_contract(case):
    assert forecast._met_condition(case['symbol']) == case['condition']


@pytest.mark.parametrize('case', CONTRACT['hourly'])
def test_hourly_contract(case):
    assert forecast._hour_icon_key(case, {}) == case['expected']


@pytest.mark.parametrize('case', CONTRACT['solar'])
def test_solar_contract(case):
    assert forecast._hour_icon_key({'condition': 'Clear', 'time': case['time']},
                                  {**case, 'timezone': 'UTC'}) == case['expected']


def test_normalizers_preserve_daylight():
    rows = forecast.normalize_open_meteo({'hourly': {
        'time': ['2026-09-15T00:00', '2026-09-15T12:00'],
        'temperature_2m': [60, 70], 'weather_code': [0, 2], 'is_day': [0, 1],
    }}, 'UTC')
    assert [row['is_day'] for row in rows] == [False, True]
    rows = forecast.normalize_nws({'properties': {'periods': [{
        'startTime': '2026-09-15T00:00:00Z', 'temperature': 60,
        'shortForecast': 'Clear', 'isDaytime': False,
    }]}}, 'UTC')
    assert rows[0]['is_day'] is False
    rows = forecast.normalize_met({'properties': {'timeseries': [{
        'time': '2026-09-15T00:00:00Z', 'data': {
            'instant': {'details': {'air_temperature': 15}},
            'next_1_hours': {'summary': {'symbol_code': 'partlycloudy_night'}},
        },
    }]}}, 'UTC')
    assert rows[0]['symbol'] == 'partlycloudy_night'
    assert forecast._hour_icon_key(rows[0], {}) == 'partly-cloudy-night'


def test_windows_daily_ties_and_daytime_artwork(monkeypatch):
    now = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(forecast, 'datetime', Clock)
    times = [(now - timedelta(hours=2) + timedelta(hours=i)).isoformat() for i in range(24 * 8)]
    rows = forecast.normalize_open_meteo({'hourly': {
        'time': times, 'temperature_2m': [60] * len(times),
        'weather_code': [2 if i % 2 else 0 for i in range(len(times))],
        'is_day': [0] * len(times),
    }}, 'UTC')
    result = forecast.build_forecast('open_meteo', list(reversed(rows)), 'UTC')
    assert result['hours'][0]['time'] == times[1]
    assert len(result['hours']) == 24
    assert [day['date'] for day in result['days']] == [f'2026-09-{day}' for day in range(16, 22)]
    assert all(day['icon_key'] == 'sunny' for day in result['days'])
    assert result['hours'][0]['icon_key'] == 'partly-cloudy-night'
    assert result['days'][0]['condition'] == 'Clear'


def test_legacy_offline_cache_uses_local_artwork(tmp_path):
    settings = AppSettings(latitude=40, longitude=-105, timezone='America/Denver')
    cache = tmp_path / 'forecast.json'
    cache.write_text(json.dumps({
        'ok': True, 'provider': settings.forecast_provider, 'cache_format': 7,
        'latitude': 40, 'longitude': -105, 'updated_at': datetime.now(timezone.utc).isoformat(),
        'condition': 'Rain', 'icon': '🌧️', 'days': [],
        'hours': [{'time': '2026-09-15T00:00:00-06:00', 'condition': 'Clear', 'icon': '☀️'}],
    }))
    service = forecast.ForecastService(cache)
    def offline(*args):
        raise OSError('offline')
    service._fetch = offline
    result = service.get(settings)
    assert result['stale'] is True
    assert result['icon_key'] == 'rain'
    assert result['hours'][0]['icon_key'] == 'clear-night'
