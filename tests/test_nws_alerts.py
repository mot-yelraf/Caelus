"""Deterministic NWS alert selection, caching, and dashboard regression tests."""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import caelus.forecast as forecast
from caelus.settings import AppSettings
from test_routes import make_app

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/nws-alerts.json').read_text())
NOW = datetime(2026, 9, 28, 20, 5, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    state = [NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state[0].astimezone(tz)

    monkeypatch.setattr(forecast, 'datetime', Clock)
    return state


def test_normalization_preserves_official_text_and_future_onset_watch():
    result = forecast.normalize_nws_alerts(FIXTURE, NOW)
    assert len(result) == 1  # Effective now, even though onset is later.
    for key in ('event', 'description', 'instruction', 'headline', 'areaDesc'):
        assert result[0][key] == FIXTURE['features'][0]['properties'][key]


@pytest.mark.parametrize('changes', [
    {'status': 'Test'}, {'status': 'Exercise'}, {'messageType': 'Cancel'},
    {'severity': 'Moderate'}, {'severity': 'Unknown'}, {'category': ['Safety']},
    {'effective': '2026-09-28T21:00:00Z'}, {'expires': NOW.isoformat()},
    {'ends': NOW.isoformat()}, {'expires': None}, {'expires': 'broken'},
    {'effective': '2026-09-28T20:00:00'},
])
def test_ineligible_alerts_are_ignored(changes):
    payload = copy.deepcopy(FIXTURE)
    payload['features'][0]['properties'].update(changes)
    assert forecast.normalize_nws_alerts(payload, NOW) == []


def test_extreme_alerts_sort_first():
    payload = copy.deepcopy(FIXTURE)
    extreme = copy.deepcopy(payload['features'][0])
    extreme['properties'].update(severity='Extreme', event='Tornado Warning')
    payload['features'].append(extreme)
    assert [a['event'] for a in forecast.normalize_nws_alerts(payload, NOW)] == [
        'Tornado Warning', 'Severe Thunderstorm Warning',
    ]


class Session:
    def __init__(self):
        self.calls = []
        self.payload = copy.deepcopy(FIXTURE)
        self.offline = False
        self.us = True

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.offline:
            raise OSError('offline')
        payload = self.payload if url == forecast.NWS_ALERTS_URL else {
            'properties': {'forecastHourly': 'https://api.weather.gov/test'} if self.us else {},
        }

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return Response()


def service_with_forecast(tmp_path):
    session = Session()
    service = forecast.ForecastService(tmp_path / 'forecast.json', session)
    # Isolate forecast network I/O while retaining the service's alert integration.
    service._get_locked = lambda settings, **kwargs: {
        'ok': True, 'provider': settings.forecast_provider, 'hours': [], 'summary': 'Clear',
    }
    return service, session


def test_alert_refresh_is_independent_and_cancellation_clears_cache(tmp_path, clock):
    service, session = service_with_forecast(tmp_path)
    settings = AppSettings(forecast_provider='us', latitude=40, longitude=-105)
    assert service.get(settings)['alerts']
    assert session.calls[-1][1]['params'] == {'point': '40.0000,-105.0000'}
    assert service.get(settings, force=True)['alerts']
    assert len(session.calls) == 2
    clock[0] += timedelta(seconds=60)
    session.payload = {'features': []}
    assert service.get(settings)['alerts'] == []
    assert len(session.calls) == 3
    assert service._alerts['payload'] == {'features': []}


def test_alerts_refresh_while_hourly_forecast_remains_cached(tmp_path, clock):
    session = Session()
    service = forecast.ForecastService(tmp_path / 'forecast.json', session)
    fetched = []

    def fetch(*args):
        fetched.append(True)
        return forecast.normalize_nws({'properties': {'periods': [{
            'startTime': NOW.isoformat(), 'temperature': 70, 'shortForecast': 'Clear',
        }]}}, 'UTC')

    service._fetch = fetch
    settings = AppSettings(forecast_provider='us', latitude=40, longitude=-105)
    assert service.get(settings)['alerts']
    clock[0] += timedelta(minutes=1)
    session.payload = {'features': []}
    result = service.get(settings)
    assert result['ok'] and result['alerts'] == []
    assert len(fetched) == 1


def test_outage_keeps_only_unexpired_alerts_and_survives_restart(tmp_path, clock):
    service, session = service_with_forecast(tmp_path)
    settings = AppSettings(forecast_provider='us', latitude=40, longitude=-105)
    service.get(settings)
    service = forecast.ForecastService(service.cache_path, session)
    clock[0] += timedelta(minutes=1)
    session.offline = True
    cached = service._get_alerts(settings, timeout_seconds=1)
    assert cached['alerts'] and cached['alerts_stale']
    count = len(session.calls)
    service._get_alerts(settings, timeout_seconds=1)
    assert len(session.calls) == count  # Failed fetches are throttled too.
    clock[0] = NOW + timedelta(hours=1)
    assert service._get_alerts(settings, timeout_seconds=1)['alerts'] == []


def test_provider_and_exact_location_isolation(tmp_path, clock):
    service, session = service_with_forecast(tmp_path)
    settings = AppSettings(forecast_provider='met_no', latitude=40, longitude=-105)
    assert service.get(settings)['alerts'] == []
    assert session.calls == []
    settings.forecast_provider = 'us'
    assert service.get(settings)['alerts']
    settings.latitude += 0.001  # Forecast cache tolerance must not apply to alerts.
    session.offline = True
    assert service.get(settings)['alerts'] == []
    settings.forecast_provider = 'open_meteo'
    assert service.get(settings)['alerts'] == []


def test_non_us_location_never_fetches_alerts(tmp_path, clock):
    service, session = service_with_forecast(tmp_path)
    session.us = False
    settings = AppSettings(forecast_provider='us', latitude=51, longitude=0)
    assert service.get(settings)['alerts'] == []
    assert all(url != forecast.NWS_ALERTS_URL for url, _ in session.calls)


def test_malformed_response_does_not_erase_last_good_alerts(tmp_path, clock):
    service, session = service_with_forecast(tmp_path)
    settings = AppSettings(forecast_provider='us', latitude=40, longitude=-105)
    service.get(settings)
    session.payload = {'unexpected': []}
    clock[0] += timedelta(minutes=1)
    result = service.get(settings)
    assert result['alerts'] and result['alerts_stale']


def test_alerts_available_when_hourly_forecast_fails(tmp_path, clock):
    service, _ = service_with_forecast(tmp_path)
    service._get_locked = lambda *args, **kwargs: {'ok': False, 'provider': 'us', 'hours': []}
    result = service.get(AppSettings(forecast_provider='us', latitude=40, longitude=-105))
    assert not result['ok'] and result['alerts']


def test_dashboard_replaces_today_and_escapes_official_text():
    app = make_app()
    app.state.settings.forecast_provider = 'us'
    alerts = forecast.normalize_nws_alerts(FIXTURE, NOW)
    alerts[0]['instruction'] = '<script>alert(1)</script>'

    class Forecast:
        def get(self, *args, **kwargs):
            return {'ok': False, 'provider': 'us', 'hours': [], 'alerts': alerts}

    app.state.forecast_service = Forecast()
    client = TestClient(app)
    html = client.get('/').text
    assert 'data-today-forecast hidden' in html
    assert 'Severe Thunderstorm Warning' in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    assert client.get('/api/forecast').json()['alerts'] == alerts
    alerts.clear()
    assert 'data-today-forecast hidden' not in client.get('/').text
