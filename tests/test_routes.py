from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

import caelus.routes as routes_module
from caelus import __version__
from caelus.astronomy import moon_phase_context
from caelus.routes import format_observation_time, register_routes
from caelus.settings import AppSettings


class FakeDataLogger:
    def get_latest(self):
        return {"temperature": 0.0, "wind_speed": 0.0, "wind_dir": 0}

    def export_readings(self, max_days, format, unit_system=None, pressure_unit="auto"):
        return "[]" if format == "json" else "timestamp"

    def get_readings_since(self, cutoff):
        return []


class FakePoller:
    def __init__(self, task=None) -> None:
        self.task = task
        self.poll_calls = 0
        self.schedule_resets = 0

    def poll_once(self):
        self.poll_calls += 1
        return {"temperature": 0.0}

    def reset_schedule(self):
        self.schedule_resets += 1


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
    assert 'data-reading-field="temperature">0.0</span>' in response.text
    assert "0.0 mph" in response.text


def test_observation_time_is_local_without_seconds_or_offset() -> None:
    assert (
        format_observation_time("2026-08-12T12:35:15.584178", "America/Denver")
        == "Aug 12, 2026 · 6:35 AM"
    )
    assert (
        format_observation_time(
            "2026-08-12T06:35:15.584178-06:00", "America/Denver"
        )
        == "Aug 12, 2026 · 6:35 AM"
    )


def test_dashboard_renders_local_observation_time() -> None:
    app = make_app()
    app.state.settings.timezone = "America/Denver"
    app.state.data_logger.get_latest = lambda: {
        "timestamp": "2026-08-12T06:35:15.584178-06:00",
        "temperature": 70.0,
    }

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert (
        '<time datetime="2026-08-12T06:35:15.584178-06:00">'
        "Aug 12, 2026 · 6:35 AM</time>"
    ) in response.text


def test_current_reading_api_uses_configured_refresh_interval() -> None:
    app = make_app()
    app.state.settings.poll_interval_seconds = 120
    app.state.settings.timezone = "America/Denver"
    app.state.data_logger.get_latest = lambda: {
        "timestamp": "2026-08-12T12:35:15",
        "temperature": 71.5,
    }

    response = TestClient(app).get("/api/readings/current")

    assert response.status_code == 200
    assert response.json() == {
        "reading": {
            "timestamp": "2026-08-12T12:35:15",
            "temperature": 71.5,
        },
        "latest_observation_time": "Aug 12, 2026 · 6:35 AM",
        "poll_interval_seconds": 120,
        "display_units": {
            "temperature": "°F",
            "pressure": "inHg",
            "wind_speed": "mph",
            "wind_gust": "mph",
            "rain_total": "in",
        },
    }


def test_gateway_relative_pressure_follows_display_unit_preset() -> None:
    app = make_app()
    app.state.data_logger.get_latest = lambda: {
        "timestamp": "2026-08-12T12:35:15",
        "pressure": None,
        "indoor_pressure": 29.708,
    }
    client = TestClient(app)

    dashboard = client.get("/")
    current = client.get("/api/readings/current")

    assert 'data-reading-field="pressure"' in dashboard.text
    assert ">29.7 inHg</strong>" in dashboard.text
    assert current.json()["reading"]["pressure"] == 29.7

def test_dashboard_refresh_timers_follow_station_and_forecast_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")

    assert 'fetch("/api/readings/current", {cache: "no-store"})' in script
    assert 'fetch("/api/ecowitt/status", {cache: "no-store"})' in script
    assert 'label.textContent = online ? "Online"' in script
    assert "window.setInterval(refreshEcowittDashboard, safeSeconds * 1000)" in script
    assert 'fetch("/api/forecast?force=true", {cache: "no-store"})' in script
    assert "nextHour.setMinutes(60, 1, 0)" in script
    assert "window.setInterval(refreshAstronomy, 5 * 60 * 1000)" in script


def test_dashboard_includes_scene_themes_settings_modal_and_lunar_cycle() -> None:
    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert '<dialog class="settings-dialog" id="settingsDialog"' in response.text
    assert "data-settings-status" in response.text
    assert response.text.count("data-save-pane=") == 4
    assert "data-ecowitt-discover" in response.text
    assert "data-ecowitt-save" in response.text
    assert "data-ecowitt-disable" in response.text
    assert "no Nodus sensors or switches are supported" in response.text
    assert "data-save-settings" not in response.text
    assert '<dialog class="forecast-dialog" id="forecastDialog"' in response.text
    assert '<dialog class="graph-dialog" id="graphDialog"' in response.text
    assert "data-open-graph" in response.text
    assert 'href="#moon"' not in response.text
    assert 'href="#conditions"' not in response.text
    assert 'href="#map"' not in response.text
    assert response.text.count("data-graph-hours=") == 8
    assert response.text.count("data-graph-metric") == 26
    assert "data-render-graph" not in response.text
    assert "6-day forecast" in response.text
    assert f'class="brand-version">{__version__}</em>' in response.text
    assert 'class="brand-mark" src="/static/icons/caelus-weather-compass-titled.png"' in response.text
    assert '<span class="brand-mark">C</span>' not in response.text
    for theme in ("garden", "island", "river", "desert"):
        assert f'name="theme" value="{theme}"' in response.text
    for phase in ("New moon", "First quarter", "Full moon", "Last quarter"):
        assert phase in response.text
    for heading in ("Current readings", "Today’s forecast", "Sunlight today", "Regional radar"):
        assert heading in response.text
    conditions_position = response.text.index('class="conditions-row"')
    sensor_position = response.text.index('class="weather-history"')
    map_position = response.text.index('class="map-row"')
    moon_position = response.text.index('class="glass-card lunar-header"')
    assert conditions_position < sensor_position < map_position < moon_position
    assert 'class="glass-card map-card full-width-map"' in response.text
    assert "Environmental decisions" not in response.text
    assert 'id="currentMoonDisk"' in response.text
    assert response.text.count("data-phase-moon") == 8
    assert "🌒" not in response.text
    assert "Observer-local orientation" in response.text
    assert 'id="northPoleDaylight"' in response.text
    assert 'id="southPoleDaylight"' in response.text
    assert 'id="nextSeasonHeading"' in response.text
    assert 'id="nextEclipseHeading"' in response.text
    assert 'id="nextEclipseList"' in response.text
    assert (
        "No visible eclipses for the next 12 months" in response.text
        or "Eclipse calculations unavailable · rerun the Caelus installer" in response.text
        or "lunar eclipse" in response.text
        or "Solar eclipse" in response.text
    )
    assert 'id="daylightHours"' not in response.text
    assert '<footer class="site-footer"><p>Created By Peace Hill Studios</p></footer>' in response.text
    assert "data-reset-windy" in response.text
    assert "data-windy-map" in response.text
    assert "data-windy-interaction" in response.text
    assert "data-windy-guard" in response.text
    assert "Click to interact with map" in response.text
    assert "overlay=radar" in response.text
    assert "data-weather-history" in response.text
    assert "24-hour sensor metrics" in response.text
    assert "data-sensor-online-status" in response.text
    assert "data-sensor-online-label" in response.text
    assert "data-hourly-carousel" not in response.text
    assert "forecast-range" not in response.text


def test_dashboard_pages_hourly_forecast_in_groups_of_eight() -> None:
    app = make_app()
    app.state.forecast_service = type(
        "FakeForecastService",
        (),
        {
            "get": staticmethod(
                lambda _settings: {
                    "ok": True,
                    "provider": "open_meteo",
                    "provider_label": "Open-Meteo",
                    "condition": "Clear",
                    "icon": "☀️",
                    "high_f": 80,
                    "low_f": 55,
                    "precip_probability": 37,
                    "precip_label": "Rain chance",
                    "hours": [
                        {
                            "label": f"{index:02d}:00",
                            "icon": "☀️",
                            "temperature_f": 60 + index,
                            "precip_probability": 0,
                            "precip_label": "Rain chance",
                        }
                        for index in range(24)
                    ],
                    "days": [
                        {
                            "date": "2026-08-13",
                            "label": "Thu Aug 13",
                            "icon": "🌧️",
                            "summary": "Cloudy early, snow afternoon",
                            "high_f": 80,
                            "low_f": 55,
                            "high_c": 26.7,
                            "low_c": 12.8,
                            "humidity_low": 30,
                            "humidity_high": 70,
                            "precip_probability": 42,
                            "precip_label": "Snow chance",
                            "wind_descriptor": "light/moderate",
                            "wind_low_mps": 1,
                            "wind_high_mps": 4,
                            "wind_low_mph": 2,
                            "wind_high_mph": 9,
                        }
                    ],
                }
            )
        },
    )()

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.text.count("data-hourly-index=") == 24
    assert 'data-hourly-index="7"' in response.text
    assert 'data-hourly-index="8" hidden' in response.text
    assert 'data-hourly-previous aria-label="Show previous forecast hour" hidden' in response.text
    assert "data-hourly-next" in response.text
    assert "Hours 1–8 of 24" in response.text
    assert "<strong>37%</strong> Rain chance" in response.text
    assert "0% rain chance" in response.text
    assert "42% snow chance" in response.text
    assert "<dt>Snow chance</dt><dd>42%</dd>" in response.text
    assert "PoP" not in response.text
    assert "0.0 mm" not in response.text


def test_24_hour_metrics_endpoint_returns_only_valid_stored_metrics() -> None:
    app = make_app()
    app.state.settings.timezone = "America/Denver"
    app.state.data_logger.get_readings_since = lambda _cutoff: [
        {
            "timestamp": "2026-08-12T12:00:00",
            "temperature": 68.0,
            "humidity": None,
            "wind_speed": 0.0,
        },
        {
            "timestamp": "2026-08-12T13:00:00",
            "temperature": 72.0,
            "humidity": None,
            "wind_speed": 4.0,
        },
    ]

    response = TestClient(app).get("/api/metrics/24h")

    assert response.status_code == 200
    payload = response.json()
    assert payload["timezone"] == "America/Denver"
    assert [metric["key"] for metric in payload["metrics"]] == [
        "temperature",
        "wind_speed",
    ]
    assert payload["metrics"][0]["stats"] == {
        "min": 68.0,
        "min_at": "2026-08-12T12:00:00",
        "avg": 70.0,
        "max": 72.0,
        "max_at": "2026-08-12T13:00:00",
        "samples": 2,
    }


def test_ecowitt_discovery_save_status_and_disable_routes(tmp_path, monkeypatch) -> None:
    class FakeGateway:
        def __init__(self, settings):
            self.settings = settings
            self.last_status = {"state": "waiting", "label": "Waiting"}

        def discover(self, gateway_url):
            assert gateway_url == "http://gw1100.local"
            return {
                "ok": True,
                "gateway_url": gateway_url,
                "gateway_id": "ecowitt-e8db840f1543",
                "gateway_model": "GW1100A_V2.3.1",
                "inventory": [{"id": "E8", "name": "7-in-1", "signal": 3}],
                "rain_source": "traditional",
                "rain_reset_hour": 9,
                "live_metric_count": 12,
            }

        def status(self):
            return {
                **self.last_status,
                "enabled": self.settings.gateway_enabled,
                "gateway_url": self.settings.gateway_url,
            }

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(AppSettings, "settings_path", settings_path)
    app = make_app()
    app.state.gateway = FakeGateway(app.state.settings)
    client = TestClient(app)
    request = {
        "gateway_url": "http://gw1100.local",
        "csrf_token": "test-token",
    }

    discovered = client.post("/api/ecowitt/discover", json=request)
    assert discovered.status_code == 200
    assert discovered.json()["inventory"][0]["name"] == "7-in-1"

    saved = client.post(
        "/api/ecowitt/save",
        json={**request, "poll_interval_seconds": 120},
    )
    assert saved.status_code == 200
    assert app.state.settings.gateway_id == "ecowitt-e8db840f1543"
    assert app.state.settings.poll_interval_seconds == 120
    assert settings_path.exists()
    assert saved.json()["initial_reading_stored"] is True
    assert app.state.poller.poll_calls == 1
    assert app.state.poller.schedule_resets == 1

    status = client.get("/api/ecowitt/status")
    assert status.json()["enabled"] is True

    disabled = client.post(
        "/api/ecowitt/disable", json={"csrf_token": "test-token"}
    )
    assert disabled.status_code == 200
    assert app.state.settings.gateway_enabled is False


def test_ecowitt_mutations_require_csrf() -> None:
    app = make_app()
    app.state.gateway = object()

    response = TestClient(app).post(
        "/api/ecowitt/discover", json={"gateway_url": "http://gw1100.local"}
    )

    assert response.status_code == 403


def test_dashboard_tolerates_astronomy_payload_from_running_older_code(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "astronomy_context", lambda _settings: moon_phase_context())

    response = TestClient(make_app()).get("/")

    assert response.status_code == 200
    assert 'data-bright-limb-angle="0"' in response.text
    assert 'data-phase-index="4" data-illumination="100"' in response.text
    assert 'id="daylightDuration">—</h2>' in response.text


def test_sunlight_card_layout_and_refresh_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert ".daylight-times dd { order: -1;" in css
    assert "--daylight-title-color: var(--accent);" in css
    assert "--daylight-data-color: var(--ink);" in css
    assert "--daylight-status-color: var(--warm);" in css
    assert "border: 1px solid var(--daylight-track-color);" in css
    assert "border-bottom: 1px solid var(--daylight-horizon-color);" in css
    assert "--daylight-track-color: #765000;" in css
    assert "color: var(--daylight-sun-color);" in css
    assert "--daylight-sun-color: #d96f00;" in css
    assert "bottom: calc(var(--sun-rise, 0) * 5rem);" in css
    assert "transform: translate(-50%, 50%);" in css
    assert "Math.sqrt(1 - horizontalOffset ** 2)" in script
    assert "function formatSolarTime(value)" in script
    assert 'moon.north_pole_daylight ?? "—"' in script
    assert 'moon.next_season_label ?? "—"' in script
    assert "moon.next_eclipses" in script
    assert "moon.eclipse_calculation_available" in script


def test_current_reading_hero_reserves_space_for_precise_values() -> None:
    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: 7rem minmax(0, 1fr);" in css
    assert ".reading-hero .temperature-number { font-size: clamp(4rem, 6vw, 6rem); }" in css
    assert "min-width: 0; text-align: left; white-space: nowrap;" in css


def test_sunny_beach_and_daylight_desert_theme_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")

    assert "Sunny Beach" in template
    assert "Ocean Island" not in template
    assert "sunny-beach.webp" in css
    assert "desert-clear.webp" in css
    assert ".theme-desert .glass-card:not(.lunar-header)" in css
    assert (root / "static" / "backgrounds" / "sunny-beach.webp").is_file()
    assert (root / "static" / "backgrounds" / "desert-clear.webp").is_file()
    assert not (root / "static" / "backgrounds" / "island.webp").exists()
    assert not (root / "static" / "backgrounds" / "desert.webp").exists()


def test_metric_display_style_settings_contract() -> None:
    response = TestClient(make_app()).get("/")
    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")

    assert "Pressure unit" not in response.text
    assert 'data-metric-style-key="temperature"' in response.text
    assert "data-all-metric-styles" in response.text
    assert "<span>All metrics</span>" in response.text
    assert ">24Hr Graph</option>" in response.text
    assert ">6Hr Graph</option>" in response.text
    assert ">Gauge</option>" in response.text
    assert ".metric-style-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert ".metric-style-bulk { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert response.text.count('class="appearance-section"') == 3
    assert "<strong>Theme</strong>" in response.text
    assert "<strong>Units</strong>" in response.text
    assert "<strong>Display Style</strong>" in response.text
    assert 'class="appearance-pane-footer"' in response.text
    assert ".appearance-pane-scroll" in css
    assert '.appearance-section summary::before { content: "▶";' in css
    assert '.appearance-section[open] summary::before { content: "▼";' in css
    assert ".appearance-section summary::after" not in css
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    assert "function updateAllMetricStyles()" in script
    assert 'allMetricStyles?.addEventListener("change"' in script


def test_settings_label_and_metric_expansion_contract() -> None:
    response = TestClient(make_app()).get("/")
    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")

    assert "System Settings" not in response.text
    assert "> Settings</button>" in response.text
    assert 'data-toggle-weather-metrics aria-expanded="false"' in response.text
    assert 'aria-controls="weatherMetricGrid"' in response.text
    assert "card.hidden = !expanded && index >= 4" in script
    assert 'window.localStorage.getItem(expansionStorageKey) === "true"' in script
    assert "storeExpansionState(expanded)" in script
    assert 'icon.textContent = expanded ? "▼" : "▶"' in script
    assert response.text.index("data-toggle-weather-metrics") < response.text.index("24-hour sensor metrics")


def test_primary_metric_display_style_defaults() -> None:
    response = TestClient(make_app()).get("/")
    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")

    assert '<span>Outdoor relative humidity</span>' in response.text
    assert "metric.key === \"rain_total\" ? \"gauge\" : \"graph24hr\"" in script
    primary_positions = [
        response.text.index(f'data-metric-style-key="{key}"')
        for key in ("temperature", "humidity", "wind_dir", "rain_total")
    ]
    first_remaining_position = response.text.index('data-metric-style-key="absolute_pressure"')
    assert primary_positions == sorted(primary_positions)
    assert primary_positions[-1] < first_remaining_position
    humidity_control = response.text[primary_positions[1]:primary_positions[2]]
    rain_control = response.text[primary_positions[3]:first_remaining_position]
    assert '<option value="graph24hr" selected>24Hr Graph</option>' in humidity_control
    assert '<option value="gauge" selected>Gauge</option>' in rain_control


def test_map_interaction_gate_and_metric_graph_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")

    assert 'windyGuard.addEventListener("click"' in script
    assert 'windyInteraction.addEventListener("mouseleave"' in script
    assert 'event.key === "Escape"' in script
    assert 'fetch("/api/metrics/24h"' in script
    assert "function drawMetricGraph(" in script
    assert "const height = 230;" in script
    assert ".weather-metric-graph { display: block; width: 100%; height: 230px;" in css
    assert "const rollingStart = generatedTime - (hours * 60 * 60 * 1000)" in script
    assert "const start = Math.max(rollingStart, points[0].time)" in script
    assert "const end = latestTime > start ? latestTime : start + 1" in script
    assert "const yTickCount = 4;" in script
    assert "context.fillText(formatAxisValue(tickValue), left - 8, tickY);" in script
    assert "points.reduce((sum, point) => sum + point.value, 0) / points.length" in script
    assert "`AVG ${metricValue(average, metric.decimals, metric.unit)}`" in script
    assert "function drawWindRose(" in script
    assert '`${hours}-hour Wind-Rose`' in script
    assert '{maximum: 5, label: "0–5"' in script
    assert "function drawMetricGauge(" in script
    assert "rain_total: 100" in script
    assert "rain_week: 300" in script
    assert "rain_month: 500" in script
    assert "rain_year: 1500" in script
    assert "Math.max(1500, Math.ceil(observedMaxMm / 500) * 500)" in script
    assert '["#d9f2ff", "#a9dcf5", "#6abce5", "#2c8fca", "#0d4f91"]' in script
    assert "Math.max(0, rawValue)" in script
    assert "function drawCompassGauge(" in script
    assert 'displayStyle === "graph24hr" ? "graph6hr"' in script
    assert "wind-rose-controls" not in script
    assert ".windy-map-interaction.is-active .windy-map-guard" in css
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert ".wind-rose-controls" in css


def test_full_screen_metric_graph_range_api_accepts_only_supported_windows() -> None:
    client = TestClient(make_app())

    response = client.get("/api/metrics/range?hours=696")

    assert response.status_code == 200
    assert response.json()["hours"] == 696
    assert client.get("/api/metrics/range?hours=2").status_code == 422


def test_full_screen_graph_enforces_four_metric_axes_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    script = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    css = (root / "static" / "styles.css").read_text(encoding="utf-8")

    assert '<h2 id="graphDialogTitle">Caelus Graphum</h2>' in template
    assert "Full-Screen Graph" not in template
    assert "if (selected.length > 4)" in script
    assert '"A maximum of four metrics can be graphed."' in script
    assert 'const side = index < 2 ? "left" : "right";' in script
    assert "plotLeft - sideIndex * 62" in script
    assert "plotRight + sideIndex * 62" in script
    assert "function drawFullScreenGraph(" in script
    assert "earliestDataTime > requestedStartTime" in script
    assert "const endTime = startTime + requestedDuration;" in script
    assert script.count("renderSelectedFullGraph();") == 3
    assert "let fullGraphRequestSequence = 0;" in script
    assert "requestSequence !== fullGraphRequestSequence" in script
    assert "if (graphDialog?.open && renderedGraphPayload)" in script
    assert "renderSelectedFullGraph({silent: true})" in script
    assert "data-close-graph" in (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "data-render-graph" not in (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "grid-template-columns: clamp(17rem, 19vw, 20rem) minmax(0, 1fr)" in css
    assert ".graph-controls-footer" not in css


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
            "unit_system": "metric",
            "metric_display_styles": '{"temperature":"gauge","humidity":"graph6hr"}',
            "csrf_token": "test-token",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "pane": "appearance"}
    assert app.state.settings.theme == "river"
    assert app.state.settings.unit_system == "metric"
    assert app.state.settings.pressure_unit == "auto"
    assert app.state.settings.metric_display_styles == {
        "temperature": "gauge", "humidity": "graph6hr"
    }
    assert app.state.settings.gateway_url == original_gateway
    assert AppSettings.load().theme == "river"
    assert AppSettings.load().unit_system == "metric"
    assert AppSettings.load().pressure_unit == "auto"
    assert AppSettings.load().metric_display_styles["temperature"] == "gauge"


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
