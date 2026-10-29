"""Keep simultaneous stations, settings and browser selections independent."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from caelus.data_logger import DataLogger
from caelus.routes import register_routes
from caelus.settings import AppSettings
from caelus.station import EcowittStationSetup
from caelus.stations import build_stations, start_station, stop_station
from test_acurite import FakeTransport


@pytest.fixture
def app(tmp_path, monkeypatch):
    from threading import RLock

    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    app = FastAPI()
    app.state.settings = AppSettings(acurite_enabled=True, use_ip_location=False)
    app.state.data_logger = DataLogger(str(tmp_path / "caelus.db"))
    app.state.station_lock = RLock()
    app.state.stations = build_stations(app, tmp_path)
    ecowitt = app.state.stations["ecowitt"]
    acurite = app.state.stations["acurite_usb"]
    ecowitt.adapter.gateway.fetch = lambda: {"tempf": 90, "hum": 50, "windsp": 0}
    acurite.adapter.transport = FakeTransport()
    app.state.weather_adapter = ecowitt.adapter
    app.state.gateway = ecowitt.adapter.gateway
    app.state.station_setup = EcowittStationSetup(
        app.state.settings, app.state.gateway, app.state.station_lock
    )
    app.state.poller = ecowitt.poller
    app.state.csrf_token = "test-token"
    app.state.templates = Jinja2Templates(
        directory=str(Path(__file__).resolve().parents[1] / "templates")
    )
    register_routes(app)
    ecowitt.poller.poll_once()
    acurite.adapter.sample_once()
    acurite.poller.poll_once()
    return app


def test_simultaneous_sources_keep_current_readings_exports_and_graphs_separate(app):
    client = TestClient(app)
    for key, expected in [("ecowitt", 90), ("acurite_usb", 68), ("ecowitt", 90)]:
        assert (
            client.get("/api/readings/current", params={"station": key}).json()[
                "reading"
            ]["temperature"]
            == expected
        )
        exported = client.get(
            "/export", params={"station": key, "format": "json"}
        ).json()
        assert len(exported) == 1 and exported[0]["temperature"] == expected
        assert (
            client.get("/api/metrics/24h", params={"station": key}).status_code == 200
        )
        assert (
            client.get(
                "/api/metrics/range", params={"station": key, "hours": 6}
            ).status_code
            == 200
        )
    assert app.state.stations["ecowitt"].data_logger.db_path.name == "caelus.db"
    assert app.state.stations["acurite_usb"].data_logger.db_path.name == "acurite.db"
    assert (
        client.get("/api/station/status?station=acurite_usb").json()["station"][
            "reporting"
        ]
        is True
    )
    assert (
        client.get("/api/ecowitt/status?station=acurite_usb")
        .json()["source_id"]
        .startswith("ecowitt:")
    )
    assert client.get("/api/readings/current?station=missing").status_code == 404
    assert client.get("/api/station/status?station=missing").status_code == 404
    assert len(client.get("/api/stations").json()["stations"]) == 4


def test_dashboard_selection_is_explicit_and_exports_stay_in_selected_station(app):
    client = TestClient(app)
    response = client.get("/?station=acurite_usb")
    assert response.status_code == 200
    assert 'data-station-key="acurite_usb"' in response.text
    assert 'value="acurite_usb" selected' in response.text
    assert "format=csv&amp;station=acurite_usb" in response.text
    assert 'data-station-card="ecowitt"' in response.text
    assert 'data-station-card="acurite_usb"' in response.text
    assert 'data-station-key="ecowitt"' in client.get("/?station=ecowitt").text
    # Two tabs never share a global active-station setting or browser cookie.
    assert (
        client.get("/api/readings/current?station=acurite_usb").json()["reading"][
            "temperature"
        ]
        == 68
    )


def test_each_station_connection_saves_its_own_fields_atomically(app):
    client = TestClient(app)
    response = client.post(
        "/api/stations/acurite_usb/settings",
        json={
            "csrf_token": "test-token",
            "enabled": False,
            "usb_serial": "console-1",
            "poll_interval_seconds": 120,
            "gateway_url": "http://ignored.local",
        },
    )
    assert response.status_code == 200
    assert app.state.settings.acurite_enabled is False
    assert app.state.settings.acurite_poll_interval_seconds == 120
    assert app.state.settings.gateway_enabled is True
    assert app.state.settings.gateway_url == "http://192.168.1.100"
    assert app.state.settings.poll_interval_seconds == 300
    assert AppSettings.load().acurite_usb_serial == "console-1"
    before = app.state.settings.__dict__.copy()
    response = client.post(
        "/api/stations/acurite_usb/settings",
        json={
            "csrf_token": "test-token",
            "enabled": True,
            "usb_serial": "changed",
            "poll_interval_seconds": 0,
        },
    )
    assert response.status_code == 422
    assert app.state.settings.__dict__ == before
    # Disabled stations retain their separate stored history.
    assert (
        client.get("/api/readings/current?station=acurite_usb").json()["reading"][
            "temperature"
        ]
        == 68
    )
    response = client.post(
        "/api/stations/ecowitt/settings",
        json={
            "csrf_token": "test-token",
            "enabled": False,
            "gateway_url": "http://192.0.2.1",
            "poll_interval_seconds": 180,
        },
    )
    assert response.status_code == 200
    assert app.state.settings.poll_interval_seconds == 180
    assert app.state.settings.acurite_poll_interval_seconds == 120
    assert (
        client.post(
            "/api/stations/acurite_usb/settings", json={"enabled": True}
        ).status_code
        == 403
    )


def test_station_lifecycles_are_independent(app):
    async def exercise():
        runtimes = list(app.state.stations.values())
        # Use fake transport for Ecowitt status as well as measurements.
        app.state.settings.gateway_enabled = False
        for runtime in runtimes:
            await start_station(runtime)
        try:
            for runtime in runtimes:
                assert (
                    runtime.poller.task is not None and not runtime.poller.task.done()
                )
            assert runtimes[1].adapter.task is not None
        finally:
            for runtime in reversed(runtimes):
                await asyncio.wait_for(stop_station(runtime), timeout=1)
        assert all(runtime.poller.task.done() for runtime in runtimes)
        assert runtimes[1].adapter.task.done()

    asyncio.run(exercise())


def test_health_check_tracks_requested_station(app):
    class Task:
        def __init__(self, done):
            self.finished = done

        def done(self):
            return self.finished

        def cancelled(self):
            return False

        def exception(self):
            return None

    app.state.stations["ecowitt"].poller.task = Task(False)
    app.state.stations["acurite_usb"].poller.task = Task(True)
    client = TestClient(app)
    assert client.get("/healthz?station=ecowitt").status_code == 200
    assert client.get("/healthz?station=acurite_usb").status_code == 503


def test_existing_ecowitt_history_survives_station_wiring(tmp_path):
    logger = DataLogger(str(tmp_path / "caelus.db"))
    logger.log_reading(
        datetime.now(timezone.utc).replace(tzinfo=None), {"temperature": 45}
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=AppSettings(), data_logger=logger, station_lock=None
        )
    )
    stations = build_stations(app, tmp_path)
    assert stations["ecowitt"].data_logger.get_latest()["temperature"] == 45
    assert stations["acurite_usb"].data_logger.get_latest() is None


def test_all_station_cleanup_is_attempted_after_one_failure():
    from caelus.stations import stop_stations

    calls = []

    class Poller:
        async def stop(self):
            calls.append("poller")

    class Adapter:
        async def stop(self):
            calls.append("adapter")
            raise OSError("cleanup failure")

    class HealthyAdapter:
        async def stop(self):
            calls.append("healthy")

    runtimes = [
        SimpleNamespace(poller=Poller(), adapter=HealthyAdapter()),
        SimpleNamespace(poller=Poller(), adapter=Adapter()),
    ]

    async def exercise():
        with pytest.raises(BaseExceptionGroup):
            await stop_stations(runtimes)

    from builtins import BaseExceptionGroup

    asyncio.run(exercise())
    assert calls == ["poller", "adapter", "poller", "healthy"]


def test_wmr100_settings_current_exports_and_independent_history(app):
    from test_wmr100 import FakeTransport as WmrTransport
    settings = app.state.settings
    runtime = app.state.stations["wmr100_usb"]
    client = TestClient(app)
    assert client.post("/api/stations/wmr100_usb/settings", json={"enabled": True}).status_code == 403
    before = settings.__dict__.copy()
    invalid = client.post("/api/stations/wmr100_usb/settings", json={
        "csrf_token": "test-token", "enabled": True, "model": "WMR200",
        "poll_interval_seconds": 60})
    assert invalid.status_code == 422 and settings.__dict__ == before
    response = client.post("/api/stations/wmr100_usb/settings", json={
        "csrf_token": "test-token", "enabled": True, "model": "wmr100n",
        "usb_serial": "oregon", "poll_interval_seconds": 120,
        "acurite_enabled": False})
    assert response.status_code == 200
    assert settings.wmr100_model == "WMR100N" and settings.acurite_enabled
    assert settings.wmr100_poll_interval_seconds == runtime.poller.settings.poll_interval_seconds == 120
    assert AppSettings.load().wmr100_enabled
    runtime.adapter.transport = WmrTransport()
    runtime.adapter.sample_once()
    runtime.poller.poll_once()
    assert runtime.data_logger.db_path.name == "wmr100.db"
    assert client.get("/api/readings/current?station=wmr100_usb").json()["reading"]["temperature"] == 58.1
    assert client.get("/export?format=json&station=wmr100_usb").json()[0]["temperature"] == 58.1
    assert client.get("/api/readings/current?station=ecowitt").json()["reading"]["temperature"] == 90
    assert client.get("/api/readings/current?station=acurite_usb").json()["reading"]["temperature"] == 68
    html = client.get("/?station=wmr100_usb").text
    assert 'data-station-card="wmr100_usb"' in html and 'value="wmr100_usb" selected' in html
    assert "Recorded rain today" in html
    assert client.get("/api/station/capabilities?station=wmr100_usb").json()["units"]["wind_gust"] == "mph"
    response = client.post("/api/stations/wmr100_usb/settings", json={
        "csrf_token": "test-token", "enabled": False, "poll_interval_seconds": 120})
    assert response.status_code == 200
    assert runtime.adapter.read() is None
    assert runtime.data_logger.get_latest()["temperature"] == 58.1


def test_davis_settings_history_exports_and_atomic_validation(app):
    from dataclasses import replace
    from test_davis import FakeTransport as DavisTransport, snapshot
    client = TestClient(app)
    runtime = app.state.stations["davis_vue"]
    settings = app.state.settings
    assert client.post("/api/stations/davis_vue/settings", json={"enabled": True}).status_code == 403
    before = settings.__dict__.copy()
    for changes in ({"port": ""}, {"port": "socket://host:22222"}, {"port": "/dev/test-vue", "baud_rate": 115200},
                    {"port": "/dev/test-vue", "baud_rate": True}):
        reply = client.post("/api/stations/davis_vue/settings", json={
            "csrf_token": "test-token", "enabled": True, "poll_interval_seconds": 120, **changes})
        assert reply.status_code == 422 and settings.__dict__ == before
    response = client.post("/api/stations/davis_vue/settings", json={
        "csrf_token": "test-token", "enabled": True, "port": "/dev/test-vue", "baud_rate": 19200,
        "poll_interval_seconds": 120, "acurite_enabled": False})
    assert response.status_code == 200
    assert settings.davis_enabled and settings.acurite_enabled
    assert runtime.poller.settings.poll_interval_seconds == 120
    restored = AppSettings.load()
    assert restored.davis_port == "/dev/test-vue" and restored.davis_baud_rate == 19200
    assert restored.davis_poll_interval_seconds == 120
    runtime.adapter.transport = DavisTransport()
    runtime.adapter.sample_once()
    runtime.adapter.transport.current = replace(snapshot(102), values={**snapshot().values, "temperature": 64.2})
    runtime.adapter.sample_once()
    runtime.poller.poll_once()
    assert runtime.data_logger.db_path.name == "davis.db"
    assert client.get("/api/readings/current?station=davis_vue").json()["reading"]["temperature"] == 64.2
    assert client.get("/export?format=json&station=davis_vue").json()[0]["temperature"] == 64.2
    assert client.get("/api/station/status?station=davis_vue").json()["observation_fresh"]
    assert client.get("/api/station/capabilities?station=davis_vue").json()["units"]["wind_gust"] == "mph"
    html = client.get("/?station=davis_vue").text
    assert 'data-station-card="davis_vue"' in html and 'value="davis_vue" selected' in html
    assert 'format=csv&amp;station=davis_vue' in html
    assert client.get("/api/readings/current?station=ecowitt").json()["reading"]["temperature"] == 90
    assert client.get("/api/readings/current?station=acurite_usb").json()["reading"]["temperature"] == 68
    response = client.post("/api/stations/davis_vue/settings", json={
        "csrf_token": "test-token", "enabled": False, "poll_interval_seconds": 120})
    assert response.status_code == 200 and not settings.davis_enabled
    assert runtime.adapter.read() is None
    assert runtime.data_logger.get_latest()["temperature"] == 64.2
