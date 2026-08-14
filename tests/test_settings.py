import json

import pytest

from caelus.settings import (
    AppSettings,
    build_windy_iframe_url,
    normalize_theme,
    validate_gateway_url,
    validate_windy_iframe_url,
)


def test_load_preserves_known_values_and_ignores_unknown_fields(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"theme": "dark", "future_setting": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(AppSettings, "settings_path", settings_path)

    settings = AppSettings.load()

    assert settings.theme == "river"
    assert settings.poll_interval_seconds == 300
    assert settings.unit_system == "imperial"
    assert settings.pressure_unit == "hpa"


def test_load_invalid_json_returns_defaults(tmp_path, monkeypatch, caplog) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(AppSettings, "settings_path", settings_path)

    settings = AppSettings.load()

    assert settings == AppSettings()
    assert "Could not load settings" in caplog.text


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://user:pass@example.test/weather", "not-a-url"],
)
def test_gateway_url_rejects_unsafe_or_invalid_values(url) -> None:
    with pytest.raises(ValueError):
        validate_gateway_url(url)


def test_windy_url_is_restricted_to_the_expected_embed() -> None:
    assert validate_windy_iframe_url("https://embed.windy.com/embed2.html?lat=1")
    with pytest.raises(ValueError):
        validate_windy_iframe_url("https://example.test/embed2.html")


def test_windy_url_is_centered_and_marked_at_station_coordinates() -> None:
    url = build_windy_iframe_url(
        "https://embed.windy.com/embed2.html?overlay=wind&zoom=7",
        32.77008,
        -108.28033,
    )

    assert "lat=32.7701" in url
    assert "lon=-108.2803" in url
    assert "detailLat=32.7701" in url
    assert "detailLon=-108.2803" in url
    assert "marker=true" in url
    assert "overlay=radar" in url


def test_legacy_themes_migrate_to_scene_themes() -> None:
    assert normalize_theme("light") == "garden"
    assert normalize_theme("dark") == "river"
    assert normalize_theme("midnight") == "island"


def test_invalid_timezone_is_ignored_during_load(tmp_path, monkeypatch, caplog) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"timezone":"Mars/Olympus","forecast_provider":"open_meteo"}', encoding="utf-8")
    monkeypatch.setattr(AppSettings, "settings_path", settings_path)

    settings = AppSettings.load()

    assert settings.timezone == "UTC"
    assert settings.forecast_provider == "open_meteo"
    assert "Ignoring invalid setting timezone" in caplog.text


def test_ecowitt_configuration_round_trips_sensor_inventory(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(AppSettings, "settings_path", settings_path)
    settings = AppSettings(
        gateway_enabled=True,
        gateway_url="http://gw1100.local",
        gateway_id="ecowitt-e8db840f1543",
        gateway_model="GW1100A_V2.3.1",
        gateway_inventory=[{"id": "E8", "name": "7-in-1", "signal": 3}],
        gateway_rain_source="traditional",
        gateway_rain_reset_hour=9,
        poll_interval_seconds=120,
    )

    settings.save()
    restored = AppSettings.load()

    assert restored.gateway_id == "ecowitt-e8db840f1543"
    assert restored.gateway_inventory[0]["name"] == "7-in-1"
    assert restored.gateway_rain_reset_hour == 9
    assert restored.poll_interval_seconds == 120
