from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

import caelus.routes as routes_module
from caelus import __version__
from caelus.astronomy import moon_phase_context
from caelus.routes import register_routes
from caelus.settings import AppSettings


class FakeDataLogger:
    def get_latest(self):
        return {"temperature": 0.0, "wind_speed": 0.0, "wind_dir": 0}

    def export_readings(self, max_days, format):
        return "[]" if format == "json" else "timestamp"


class FakePoller:
    def __init__(self, task=None) -> None:
        self.task = task

    def poll_once(self):
        return {"temperature": 0.0}


class FakeTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done

    def cancelled(self) -> bool:
        return False

    def exception(self):
        return RuntimeError("poller failed") if self._done else None


def make_app(task=None) -> FastAPI:
    app = FastAPI()
    app.state.templates = Jinja2Templates(
        directory=str(Path(__file__).resolve().parents[1] / "templates")
    )
    app.state.settings = AppSettings()
    app.state.data_logger = FakeDataLogger()
    app.state.poller = FakePoller(task)
    app.state.csrf_token = "test-token"
    register_routes(app)
    return app


def test_dashboard_displays_zero_values() -> None:
    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert 'class="temperature-number">0.0</span>' in response.text
    assert "0.0 mph" in response.text


def test_dashboard_includes_scene_themes_settings_modal_and_lunar_cycle() -> None:
    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert '<dialog class="settings-dialog" id="settingsDialog"' in response.text
    assert "data-settings-status" in response.text
    assert response.text.count("data-save-pane=") == 5
    assert "data-save-settings" not in response.text
    assert '<dialog class="forecast-dialog" id="forecastDialog"' in response.text
    assert "6-day forecast" in response.text
    assert f'class="brand-version">{__version__}</em>' in response.text
    for theme in ("garden", "island", "river", "desert"):
        assert f'name="theme" value="{theme}"' in response.text
    for phase in ("New moon", "First quarter", "Full moon", "Last quarter"):
        assert phase in response.text
    for heading in ("Current readings", "Today’s forecast", "Sunlight today", "Regional radar"):
        assert heading in response.text
    conditions_position = response.text.index('class="conditions-row"')
    map_position = response.text.index('class="map-row"')
    moon_position = response.text.index('class="glass-card lunar-header"')
    assert conditions_position < map_position < moon_position
    assert 'class="glass-card map-card full-width-map"' in response.text
    assert "Environmental decisions" not in response.text
    assert 'id="currentMoonDisk"' in response.text
    assert response.text.count("data-phase-moon") == 8
    assert "🌒" not in response.text
    assert "Observer-local orientation" in response.text
    assert "hours between sunrise and sunset" in response.text
    assert '<footer class="site-footer"><p>Created by Peace Hill Studios</p></footer>' in response.text
    assert "data-reset-windy" in response.text
    assert "data-windy-map" in response.text
    assert "forecast-range" not in response.text


def test_dashboard_tolerates_astronomy_payload_from_running_older_code(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "astronomy_context", lambda _settings: moon_phase_context())

    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert 'data-bright-limb-angle="0"' in response.text
    assert 'data-phase-index="4" data-illumination="100"' in response.text
    assert 'id="daylightDuration">—</h2>' in response.text


def test_health_reports_failed_poller() -> None:
    response = TestClient(make_app(FakeTask(done=True))).get("/healthz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_settings_requires_csrf_token() -> None:
    response = TestClient(make_app()).post(
        "/settings",
        data={
            "gateway_url": "http://192.168.1.100/weatherstation",
            "poll_interval_seconds": "300",
        },
    )

    assert response.status_code == 403


def test_settings_accepts_valid_values_with_csrf_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    app = make_app()

    response = TestClient(app).post(
        "/settings",
        data={
            "gateway_url": "http://192.168.1.10/weatherstation",
            "poll_interval_seconds": "60",
            "theme": "desert",
            "retention_days": "90",
            "export_format": "json",
            "windy_iframe_url": "https://embed.windy.com/embed2.html?lat=1",
            "csrf_token": "test-token",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert app.state.settings.gateway_url == "http://192.168.1.10/weatherstation"
    assert app.state.settings.theme == "desert"
    assert AppSettings.settings_path.exists()


def test_appearance_pane_saves_without_other_settings_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "settings_path", tmp_path / "settings.json")
    app = make_app()
    original_gateway = app.state.settings.gateway_url

    response = TestClient(app).post(
        "/settings",
        data={
            "settings_pane": "appearance",
            "theme": "river",
            "csrf_token": "test-token",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "pane": "appearance"}
    assert app.state.settings.theme == "river"
    assert app.state.settings.gateway_url == original_gateway
    assert AppSettings.load().theme == "river"


def test_settings_rejects_non_http_gateway_with_csrf_token() -> None:
    response = TestClient(make_app()).post(
        "/settings",
        data={
            "gateway_url": "file:///etc/passwd",
            "poll_interval_seconds": "300",
            "csrf_token": "test-token",
        },
    )

    assert response.status_code == 422
