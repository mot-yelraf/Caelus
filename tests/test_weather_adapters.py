"""Exercise the normalized acquisition contract without station hardware or network."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from threading import RLock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from caelus.adapters import EcowittAdapter, create_weather_adapter
from caelus.data_logger import DataLogger
from caelus.gateway import EcowittGateway, map_gateway_reading
from caelus.observations import ChannelCapability, Observation, RainPolicy
from caelus.poller import GatewayPoller
from caelus.rain import counter_identity, process_rain
from caelus.routes import register_routes
from caelus.settings import AppSettings
from caelus.station import EcowittStationSetup

UTC = timezone.utc
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/weather-adapters.json").read_text()
)


class SecondStationAdapter:
    """A normalized adapter with no Ecowitt transport, discovery, or payload keys."""

    def __init__(self, observation):
        self.observation = observation

    def read(self):
        return self.observation

    def capabilities(self):
        return (ChannelCapability("primary", tuple(self.observation.measurements)),)

    def status(self):
        return {
            "source_id": self.observation.source_id,
            "connected": True,
            "observation_fresh": True,
            "station": {"reporting": True, "battery_status": "UNKNOWN"},
            "sensors": [],
        }


def sample(values, *, source="station-a", at=NOW, rain=None):
    return Observation(
        source, at, NOW + timedelta(minutes=1), values, rain or RainPolicy()
    )


def poller_for(tmp_path, adapter):
    app = FastAPI()
    app.state.settings = AppSettings()
    app.state.station_lock = RLock()
    app.state.data_logger = DataLogger(str(tmp_path / "station.db"))
    app.state.weather_adapter = adapter
    app.state.poller = GatewayPoller(app)
    app.state.csrf_token = "test-token"
    register_routes(app)
    return app


@pytest.mark.parametrize(
    "payload", ["ecowitt_metric", "ecowitt_legacy", "second_station"]
)
def test_adapter_contract_reuses_persistence_and_display(tmp_path, payload):
    if payload == "second_station":
        adapter = SecondStationAdapter(sample(FIXTURES[payload]))
    else:
        gateway = SimpleNamespace(fetch=lambda: FIXTURES[payload])
        adapter = EcowittAdapter(AppSettings(), gateway)
    app = poller_for(tmp_path, adapter)
    result = app.state.poller.poll_once()
    latest = app.state.data_logger.get_latest()
    assert latest["temperature"] == result["temperature"] == 68
    assert latest["wind_speed"] == latest["wind_dir"] == 0
    assert latest["humidity"] == 65
    assert latest["pressure"] == pytest.approx(29.919, abs=0.002)
    assert latest["feels_like"] is not None
    response = TestClient(app).get("/api/readings/current")
    assert response.status_code == 200
    assert response.json()["reading"]["temperature"] == 68


def test_device_and_receipt_times_are_distinct_and_utc_storage_is_compatible(tmp_path):
    local = timezone(timedelta(hours=-6))
    observation = sample(
        {"temperature": 32}, at=datetime(2026, 10, 28, 6, tzinfo=local)
    )
    app = poller_for(tmp_path, SecondStationAdapter(observation))
    app.state.poller.poll_once()
    row = app.state.data_logger.get_latest()
    assert row["timestamp"] == "2026-10-28T12:00:00"
    assert row["observed_at"] == NOW.isoformat()
    assert row["received_at"] == (NOW + timedelta(minutes=1)).isoformat()
    assert row["source_id"] == "station-a"
    assert "source_id" not in observation.measurements


@pytest.mark.parametrize("field", ["observed_at", "received_at"])
def test_naive_observation_times_are_rejected(field):
    values = dict(
        source_id="station", observed_at=NOW, received_at=NOW, measurements={}
    )
    values[field] = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        Observation(**values)


@pytest.mark.parametrize(
    "bad", ["broken", float("inf"), float("-inf"), float("nan"), True, []]
)
def test_invalid_legacy_and_normalized_metrics_are_unavailable(bad):
    assert map_gateway_reading({"tempf": bad})["temperature"] is None
    assert sample({"temperature": bad, "wind_speed": 0}).measurements == {
        "temperature": None,
        "wind_speed": 0,
    }


def test_unknown_metrics_do_not_silently_enter_storage(caplog):
    assert sample({"temperature": 0, "vendor_unknown": 1}).measurements == {
        "temperature": 0
    }
    assert "vendor_unknown" in caplog.text


def test_empty_and_all_invalid_observations_are_not_persisted(tmp_path):
    adapter = SecondStationAdapter(sample({"temperature": "bad"}))
    app = poller_for(tmp_path, adapter)
    assert app.state.poller.poll_once() is None
    adapter.observation = None
    assert app.state.poller.poll_once() is None
    assert app.state.data_logger.get_latest() is None


def test_generic_status_capabilities_and_optional_setup(tmp_path):
    adapter = SecondStationAdapter(sample({"temperature": 0, "wind_speed": 0}))
    client = TestClient(poller_for(tmp_path, adapter))
    assert client.get("/api/station/status").json() == adapter.status()
    assert client.get("/api/ecowitt/status").json() == adapter.status()
    assert client.get("/api/station/capabilities").json() == {
        "channels": [
            {
                "channel_id": "primary",
                "metrics": ["temperature", "wind_speed"],
                "primary": True,
            }
        ],
        "units": {"temperature": "degF", "wind_speed": "mph"},
    }
    response = client.post("/api/ecowitt/discover", json={"csrf_token": "test-token"})
    assert response.status_code == 409
    assert client.post("/api/ecowitt/discover", json={}).status_code == 403


@pytest.mark.parametrize(
    "kind,field", [("daily", "rain_total"), ("lifetime", "rain_lifetime")]
)
def test_rain_counter_survives_poller_restart(tmp_path, kind, field):
    policy = RainPolicy(kind=kind)
    app = poller_for(tmp_path, SecondStationAdapter(sample({field: 1}, rain=policy)))
    assert app.state.poller.poll_once().get("rain_increment") is None
    app.state.weather_adapter.observation = sample(
        {field: 1.2}, at=NOW + timedelta(minutes=2), rain=policy
    )
    app.state.poller = GatewayPoller(app)
    assert app.state.poller.poll_once()["rain_increment"] == 0.2
    assert app.state.data_logger.get_latest()["rain_increment"] == 0.2


@pytest.mark.parametrize(
    "change", ["source", "channel", "kind", "reset", "timezone", "legacy"]
)
def test_rain_counter_changes_never_produce_false_rain(change):
    old = RainPolicy(kind="daily")
    previous = {
        "timestamp": NOW.isoformat(),
        "rain_total": 1,
        "rain_lifetime": 1,
        "rain_counter_id": counter_identity("station-a", old),
    }
    policy = old
    source = "station-a"
    if change == "source":
        source = "station-b"
    if change == "channel":
        policy = RainPolicy(kind="daily", channel_id="other-gauge")
    if change == "kind":
        policy = RainPolicy(kind="lifetime")
    if change == "reset":
        policy = RainPolicy(kind="daily", reset_hour=9)
    if change == "timezone":
        policy = RainPolicy(kind="daily", timezone="America/Denver")
    if change == "legacy":
        previous.pop("rain_counter_id")
    observation = sample(
        {"rain_total": 10, "rain_lifetime": 10},
        source=source,
        at=NOW + timedelta(minutes=1),
        rain=policy,
    )
    process_rain(observation, previous)
    assert "rain_increment" not in observation.measurements


@pytest.mark.parametrize("kind", ["daily", "lifetime", "interval", "none"])
def test_adapter_supplied_rain_increment_is_preserved(kind):
    policy = RainPolicy(kind=kind)
    observation = sample({"rain_increment": 0.05, "rain_total": 10}, rain=policy)
    previous = {
        "timestamp": (NOW - timedelta(minutes=1)).isoformat(),
        "rain_total": 1,
        "rain_counter_id": counter_identity("station-a", policy),
    }
    process_rain(observation, previous)
    assert observation.measurements["rain_increment"] == 0.05


@pytest.mark.parametrize("kind,expected", [("daily", 0.2), ("lifetime", 0)])
def test_daily_and_lifetime_reset_semantics_differ(kind, expected):
    policy = RainPolicy(kind=kind)
    observation = sample(
        {"rain_total": 0.2, "rain_lifetime": 0.2}, at=NOW.replace(hour=0), rain=policy
    )
    previous = {
        "timestamp": (NOW.replace(hour=0) - timedelta(minutes=1)).isoformat(),
        "rain_total": 1,
        "rain_lifetime": 1,
        "rain_counter_id": counter_identity("station-a", policy),
    }
    process_rain(observation, previous)
    assert observation.measurements["rain_increment"] == expected


def test_nonforward_counter_sample_does_not_produce_increment():
    policy = RainPolicy(kind="daily")
    observation = sample({"rain_total": 10}, rain=policy)
    previous = {
        "timestamp": NOW.isoformat(),
        "rain_total": 1,
        "rain_counter_id": counter_identity("station-a", policy),
    }
    process_rain(observation, previous)
    assert "rain_increment" not in observation.measurements


@pytest.mark.parametrize("family", ["wh69", "wh51", "unknown"])
def test_ecowitt_station_freshness_is_independent_of_sensor_family(family):
    settings = AppSettings()
    gateway = EcowittGateway(settings)
    gateway.last_status.update(
        state="online",
        last_success=datetime.now(UTC).isoformat(),
        inventory=[{"id": "123", "family": family, "signal": 3, "battery": "0"}],
    )
    adapter = EcowittAdapter(settings, gateway)
    status = adapter.status()
    assert status["station"]["reporting"] is True
    assert status["sensors"][0]["reporting"] is True
    assert status["station"]["battery_status"] == (
        "OK" if family == "wh69" else "UNKNOWN"
    )
    gateway.last_status["last_success"] = "2000-01-01T00:00:00+00:00"
    status = adapter.status()
    assert status["connected"] is True
    assert status["observation_fresh"] is False
    assert status["station"] == {"reporting": False, "battery_status": "UNKNOWN"}
    assert status["sensors"][0]["reporting"] is False
    settings.gateway_enabled = False
    assert adapter.status()["connected"] is False


def test_live_weather_does_not_require_inventory():
    gateway = EcowittGateway(AppSettings())
    gateway.last_status.update(
        state="online", last_success=datetime.now(UTC).isoformat(), inventory=[]
    )
    status = EcowittAdapter(gateway.settings, gateway).status()
    assert status["station"] == {"reporting": True, "battery_status": "UNKNOWN"}


def test_ecowitt_capabilities_do_not_claim_discovered_channels_are_parsed():
    adapter = EcowittAdapter(
        AppSettings(gateway_inventory=[{"id": "probe", "family": "wh51"}])
    )
    assert len(adapter.capabilities()) == 1
    assert adapter.capabilities()[0].channel_id == "primary"
    assert "soil_moisture" not in adapter.capabilities()[0].metrics


def test_factory_defaults_and_unknown_selection(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    AppSettings.settings_path.write_text(
        '{"weather_adapter": "missing", "latitude": 40}'
    )
    settings = AppSettings.load()
    assert settings.latitude == 40
    assert isinstance(create_weather_adapter(settings), EcowittAdapter)
    assert "weather_adapter" in caplog.text
    settings.weather_adapter = "missing"
    with pytest.raises(ValueError, match="Unsupported weather adapter"):
        create_weather_adapter(settings)


def test_failed_setup_save_does_not_change_live_settings(monkeypatch):
    settings = AppSettings()
    gateway = EcowittGateway(settings)
    setup = EcowittStationSetup(settings, gateway)

    def fail(self):
        raise OSError("disk unavailable")

    monkeypatch.setattr(AppSettings, "save", fail)
    with pytest.raises(OSError):
        setup.disable()
    assert settings.gateway_enabled is True
    assert gateway.last_status["state"] == "waiting"


def test_metadata_migration_preserves_historical_rows(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "historical.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE readings (timestamp TEXT PRIMARY KEY, wind_speed REAL, wind_dir INTEGER, wind_gust REAL, rain_rate REAL, rain_total REAL, temperature REAL, humidity REAL, uv REAL, solar_radiation REAL, pressure REAL, indoor_temperature REAL, indoor_humidity REAL)"
        )
        connection.execute(
            "INSERT INTO readings(timestamp, temperature) VALUES (?, ?)",
            ("2026-10-28T12:00:00", 68),
        )
        connection.commit()
    row = DataLogger(str(path)).get_latest()
    assert row["temperature"] == 68
    assert row["timestamp"] == "2026-10-28T12:00:00"
    assert all(
        row[key] is None
        for key in ("source_id", "observed_at", "received_at", "rain_counter_id")
    )


def test_app_can_inject_adapter_without_ecowitt_setup(tmp_path, monkeypatch):
    from caelus import app as module

    (tmp_path / "static").mkdir()
    monkeypatch.setattr(module, "BASE_DIR", tmp_path / "caelus")
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "data/settings.json")
    adapter = SecondStationAdapter(sample({"temperature": 68}))
    app = module.create_app(weather_adapter=adapter)
    assert app.state.poller.adapter is adapter
    assert app.state.station_setup is None
    assert not hasattr(app.state, "gateway")
    assert app.state.poller.poll_once()["temperature"] == 68
    assert TestClient(app).get("/api/station/status").json() == adapter.status()


def test_failed_setup_save_preserves_all_shared_values(monkeypatch):
    settings = AppSettings()
    before = settings.__dict__.copy()
    setup = EcowittStationSetup(settings, EcowittGateway(settings))
    discovery = dict(
        gateway_url="http://other.local",
        gateway_id="new-source",
        gateway_model="GW1100",
        inventory=[],
        rain_source="piezo",
        rain_reset_hour=9,
    )

    def fail(self):
        raise OSError("disk unavailable")

    monkeypatch.setattr(AppSettings, "save", fail)
    with pytest.raises(OSError):
        setup.save(discovery, 60)
    assert settings.__dict__ == before


def test_setup_changes_wait_for_inflight_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release, saving = Event(), Event(), Event()
    settings = AppSettings(gateway_url="http://old.local")

    def fetch():
        entered.set()
        assert release.wait(timeout=2)
        return {"tempf": 68}

    adapter = EcowittAdapter(settings, SimpleNamespace(fetch=fetch))
    app = poller_for(tmp_path, adapter)
    setup = EcowittStationSetup(settings, adapter.gateway, app.state.station_lock)
    discovery = dict(
        gateway_url="http://new.local",
        gateway_id="new-source",
        gateway_model="GW1100",
        inventory=[],
        rain_source="traditional",
        rain_reset_hour=0,
    )

    def save():
        saving.set()
        setup.save(discovery, 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        poll = pool.submit(app.state.poller.poll_once)
        try:
            assert entered.wait(timeout=2)
            write = pool.submit(save)
            assert saving.wait(timeout=2)
            assert settings.gateway_url == "http://old.local"
        finally:
            release.set()
        row = poll.result(timeout=2)
        write.result(timeout=2)
    assert row["source_id"] == "ecowitt::http://old.local"
    assert settings.gateway_url == "http://new.local"
