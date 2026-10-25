"""Verify shared thermal calculations against paired provider fixture data."""
import json
from datetime import date
from pathlib import Path

import pytest

from caelus.forecast import _daily_detail, normalize_met, normalize_nws, normalize_open_meteo

PAYLOADS = json.loads((Path(__file__).parent / 'fixtures/thermal-forecasts.json').read_text())
NORMALIZERS = {'open_meteo': normalize_open_meteo, 'met_no': normalize_met, 'us': normalize_nws}


@pytest.mark.parametrize('provider', NORMALIZERS)
def test_all_providers_derive_hourly_values_and_daily_ranges(provider):
    rows = NORMALIZERS[provider](PAYLOADS[provider], 'UTC')
    assert [row['feels_like_f'] for row in rows] == [5.9, 38.4, 102.7]
    assert [row['wind_chill_f'] for row in rows] == [6.2, None, None]
    day = _daily_detail(rows, date(2026, 10, 26), 'UTC')
    assert day['feels_like_low_f'] == 5.9
    assert day['feels_like_high_f'] == 102.7
    assert day['feels_like_low_c'] == -14.5
    assert day['wind_chill_low_f'] == day['wind_chill_high_f'] == 6.2
    assert day['wind_chill_low_c'] == day['wind_chill_high_c'] == -14.3
    day = _daily_detail(rows[1:], date(2026, 10, 26), 'UTC')
    assert day['wind_chill_low_f'] is day['wind_chill_high_f'] is None


@pytest.mark.parametrize('provider', NORMALIZERS)
def test_missing_forecast_wind_does_not_become_calm_for_derived_values(provider):
    payload = json.loads(json.dumps(PAYLOADS[provider]))
    if provider == 'open_meteo':
        del payload['hourly']['wind_speed_10m']
    elif provider == 'met_no':
        for period in payload['properties']['timeseries']:
            del period['data']['instant']['details']['wind_speed']
    else:
        for period in payload['properties']['periods']:
            del period['windSpeed']
    rows = NORMALIZERS[provider](payload, 'UTC')
    assert all(row['feels_like_f'] is None and row['wind_chill_f'] is None for row in rows)
