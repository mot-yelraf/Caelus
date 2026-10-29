"""Protocol-derived gateway compatibility tests; no physical hardware is required."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from caelus.adapters import EcowittAdapter
from caelus.data_logger import DataLogger
from caelus.gateway import EcowittGateway, gateway_family, normalize_ecowitt_livedata
from caelus.poller import GatewayPoller
from caelus.routes import register_routes
from caelus.settings import AppSettings
from caelus.station import EcowittStationSetup

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/ecowitt-http-gateways.json").read_text()
)["gateways"]


class FixtureResponse:
    def __init__(self, payload):
        self.payload = deepcopy(payload)
        self.content = json.dumps(payload).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FixtureSession:
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []

    def get(self, url, params=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, params))
        payload = {
            "get_version": self.fixture["version"],
            "get_network_info": self.fixture["network"],
            "get_livedata_info": self.fixture["live"],
            "get_rain_totals": self.fixture["rain_totals"],
        }
        if endpoint == "get_sensors_info":
            return FixtureResponse(self.fixture["inventory"][params["page"] - 1])
        return FixtureResponse(payload[endpoint])


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture["family"])
def test_gateway_discovery_setup_polling_persistence_and_api(
    fixture, tmp_path, monkeypatch
):
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    settings = AppSettings()
    session = FixtureSession(fixture)
    gateway = EcowittGateway(settings, session=session)
    adapter = EcowittAdapter(settings, gateway)
    app = FastAPI()
    app.state.settings = settings
    app.state.gateway = gateway
    app.state.weather_adapter = adapter
    app.state.station_setup = EcowittStationSetup(settings, gateway)
    app.state.data_logger = DataLogger(str(tmp_path / "weather.db"))
    app.state.poller = GatewayPoller(app)
    app.state.csrf_token = "test-token"
    register_routes(app)
    client = TestClient(app)
    url = "http://" + fixture["network"]["ethIP"]
    discovery = client.post(
        "/api/ecowitt/discover", json={"gateway_url": url, "csrf_token": "test-token"}
    )
    assert discovery.status_code == 200
    result = discovery.json()
    assert result["gateway_family"] == fixture["family"]
    assert result["gateway_model"].startswith(fixture["family"])
    assert len(result["inventory"]) == sum(len(page) for page in fixture["inventory"])
    assert all(
        sensor["reporting"] == (sensor["signal"] > 0) for sensor in result["inventory"]
    )
    assert "not-public" not in discovery.text
    assert "private-network" not in discovery.text
    saved = client.post(
        "/api/ecowitt/save",
        json={
            "gateway_url": url,
            "csrf_token": "test-token",
            "poll_interval_seconds": 60,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["initial_reading_stored"] is True
    assert settings.gateway_url == url
    assert settings.gateway_rain_source == (
        "piezo" if fixture["family"] == "GW3000" else "traditional"
    )
    assert AppSettings.load().gateway_model == result["gateway_model"]
    row = app.state.data_logger.get_latest()
    for key, expected in fixture["expected"].items():
        assert row[key] == pytest.approx(expected, abs=0.001), key
    assert row["source_id"].startswith("ecowitt:ecowitt-")
    assert row["feels_like"] is not None
    status = client.get("/api/station/status").json()
    assert status["gateway_family"] == fixture["family"]
    assert status["observation_fresh"] is True
    assert status["station"]["reporting"] is True  # WH80/WH90, not a WS69 array.
    assert status["station"]["battery_status"] == "UNKNOWN"
    assert "not-public" not in json.dumps(status)
    assert client.get("/api/readings/current").json()["reading"]["temperature"] == 68
    assert "ch_soil" not in row and "ch_aisle" not in row
    assert {name for name, _ in session.calls} == {
        "get_version",
        "get_network_info",
        "get_sensors_info",
        "get_livedata_info",
        "get_rain_totals",
    }


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Version: GW2000B_V2.1.4", "GW2000"),
        ("GW3000C_V1.0.0", "GW3000"),
        ("GW1100A_V2.3.1", "GW1100"),
        ("GW1200A_V1.0.0", "GW1200"),
        ("gw2000", "GW2000"),
        ("GW30000_V1", ""),
        ("GW1000_V1", ""),
        ("other-device", ""),
    ],
)
def test_gateway_family_recognition(label, expected):
    assert gateway_family(label) == expected


def test_common_list_indoor_and_rain_fields_preserve_zero():
    payload = {
        "common_list": [
            {"id": "0x01", "val": "0 C"},
            {"id": "0x06", "val": "0%"},
            {"id": "0x0E", "val": "0 mm/Hr"},
            {"id": "0x10", "val": "25.4 mm"},
        ]
    }
    result = normalize_ecowitt_livedata(payload)
    assert result == {
        "indoor_temperature": 32,
        "indoor_humidity": 0,
        "rain_rate": 0,
        "rain_total": 1,
    }
    assert "rain_total" not in normalize_ecowitt_livedata(payload, rain_source="piezo")
    assert "rain_total" not in normalize_ecowitt_livedata(payload, rain_source="none")


def test_explicit_indoor_and_rain_sections_take_precedence():
    payload = {
        "common_list": [
            {"id": "0x01", "val": "10 C"},
            {"id": "0x06", "val": "70%"},
            {"id": "0x10", "val": "25.4 mm"},
        ],
        "wh25": [{"intemp": "20 C", "inhumi": "50%"}],
        "rain": [{"id": "0x10", "val": "50.8 mm"}],
        "piezoRain": [{"id": "0x10", "val": "76.2 mm"}],
    }
    result = normalize_ecowitt_livedata(payload)
    assert result["indoor_temperature"] == 68
    assert result["indoor_humidity"] == 50
    assert result["rain_total"] == 2
    assert normalize_ecowitt_livedata(payload, rain_source="piezo")["rain_total"] == 3


def test_mmhg_pressure_units_normalize_in_both_live_sections():
    result = normalize_ecowitt_livedata(
        {
            "common_list": [{"id": "0x09", "val": "760", "unit": "mmHg"}],
            "wh25": [{"rel": "760 mmHg", "abs": "750 mmHg"}],
        }
    )
    assert result["pressure"] == result["indoor_pressure"] == 29.921
    assert result["indoor_absolute_pressure"] == 29.528
