"""Exercise console-family selection through shared protocol decoding and settings."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from caelus.acurite import AcuRiteUsbAdapter
from caelus.acurite_models import console_profile
from caelus.data_logger import DataLogger
from caelus.poller import GatewayPoller
from caelus.settings import AppSettings
from test_acurite import FakeTransport, packet
from test_stations import app as _station_fixture


@pytest.fixture
def station_app(tmp_path, monkeypatch):
    return _station_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "model,manual_mode",
    [
        ("01536", False),
        ("01025", True),
        ("01035", True),
        ("01036", True),
        ("01525", True),
        ("02032", True),
    ],
)
@pytest.mark.parametrize(
    "calibration,hpa", [("console_hp03", 763.77734375), ("console_linear", 1013.25)]
)
def test_each_family_reuses_reports_without_guessing_pressure_layout(
    tmp_path, model, manual_mode, calibration, hpa
):
    settings = AppSettings(acurite_enabled=True, acurite_model=model)
    transport = FakeTransport()
    transport.reports[2] = packet(calibration)
    adapter = AcuRiteUsbAdapter(settings, transport)
    logger = DataLogger(str(tmp_path / "acurite.db"))
    poller = GatewayPoller(
        SimpleNamespace(
            state=SimpleNamespace(
                settings=settings, weather_adapter=adapter, data_logger=logger
            )
        )
    )
    adapter.sample_once()
    result = poller.poll_once()
    stored = logger.get_latest()
    assert stored["temperature"] == result["temperature"] == 68
    assert stored["humidity"] == 65
    assert stored["indoor_absolute_pressure"] * 33.8638866667 == pytest.approx(hpa)
    status = adapter.status()
    assert status["configured_model"] == model
    assert status["requires_mode4_selection"] is manual_mode
    assert status["station"]["reporting"] is True
    if manual_mode:
        assert "Select USB MODE or PC CONNECT MODE 4" in status["usb_mode_help"]
    else:
        assert "automatically" in status["usb_mode_help"]


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("01536-RX", "01536"),
        ("06056", "01536"),
        ("06006", "01036"),
        ("01092", "01036"),
        ("02032C", "02032"),
        ("02033", "02032"),
        ("01093", "02032"),
        ("06037", "02032"),
    ],
)
def test_known_console_aliases_normalize(alias, canonical):
    assert console_profile(alias.lower()).key == canonical
    assert AppSettings._validate_value("acurite_model", alias) == canonical


def test_invalid_model_load_preserves_other_configuration(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(AppSettings, "settings_path", path)
    path.write_text(
        json.dumps(
            {
                "acurite_model": "unsupported",
                "acurite_poll_interval_seconds": 120,
                "acurite_enabled": True,
            }
        )
    )
    settings = AppSettings.load()
    assert settings.acurite_model == "01536"
    assert settings.acurite_poll_interval_seconds == 120
    assert settings.acurite_enabled is True
    assert "Ignoring invalid setting acurite_model" in caplog.text


@pytest.mark.parametrize("model", ["01025", "01035", "01036", "01525", "02032"])
def test_station_model_settings_round_trip_without_touching_ecowitt(station_app, model):
    client = TestClient(station_app)
    before = (station_app.state.settings.gateway_enabled, station_app.state.settings.gateway_url)
    response = client.post(
        "/api/stations/acurite_usb/settings",
        json={
            "csrf_token": "test-token",
            "enabled": False,
            "model": model,
            "usb_serial": "",
            "poll_interval_seconds": 60,
        },
    )
    assert response.status_code == 200
    assert station_app.state.settings.acurite_model == AppSettings.load().acurite_model == model
    assert (
        station_app.state.settings.gateway_enabled,
        station_app.state.settings.gateway_url,
    ) == before
    assert (
        client.get("/api/station/status?station=acurite_usb").json()["configured_model"]
        == model
    )


def test_unknown_model_does_not_partially_save_station(station_app):
    before = station_app.state.settings.__dict__.copy()
    response = TestClient(station_app).post(
        "/api/stations/acurite_usb/settings",
        json={
            "csrf_token": "test-token",
            "enabled": False,
            "model": "unsupported",
            "usb_serial": "different",
            "poll_interval_seconds": 180,
        },
    )
    assert response.status_code == 422
    assert station_app.state.settings.__dict__ == before


def test_legacy_station_save_keeps_selected_family(station_app):
    station_app.state.settings.acurite_model = "01035"
    response = TestClient(station_app).post(
        "/api/stations/acurite_usb/settings",
        json={
            "csrf_token": "test-token",
            "enabled": False,
            "usb_serial": "",
            "poll_interval_seconds": 60,
        },
    )
    assert response.status_code == 200
    assert station_app.state.settings.acurite_model == "01035"
