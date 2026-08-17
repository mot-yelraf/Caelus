import asyncio
import json
import secrets
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from caelus import __version__
from caelus.astronomy import astronomy_context
from caelus.data_logger import DataLogger
from caelus.forecast import build_decisions, normalize_forecast_provider
from caelus.gateway import EcowittGatewayError
from caelus.location import resolve_ip_location
from caelus.metrics import build_24_hour_metric_cards, metric_display_options
from caelus.settings import (
    ALLOWED_EXPORT_FORMATS,
    AppSettings,
    build_windy_iframe_url,
    normalize_theme,
    validate_gateway_url,
    validate_windy_iframe_url,
)
from caelus.units import convert_reading, display_unit_for

GRAPH_RANGE_HOURS = {1, 6, 12, 24, 72, 168, 336, 696}
FAVICON_SVG = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "icons"
    / "caelus-weather-compass.svg"
).read_text(encoding="utf-8")
FAVICON_PNG = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "icons"
    / "caelus-favicon-32.png"
).read_bytes()
FAVICON_ICO = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "icons"
    / "caelus-favicon.ico"
).read_bytes()


def format_observation_time(value: Any, timezone_name: str) -> str:
    """Format a stored observation timestamp in the configured local time."""
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        local = observed.astimezone(ZoneInfo(timezone_name))
    except (KeyError, TypeError, ValueError):
        return "just now"
    date_text = f"{local.strftime('%b')} {local.day}, {local.year}"
    time_text = local.strftime("%I:%M %p").lstrip("0")
    return f"{date_text} · {time_text}"


def reading_for_display(
    reading: dict[str, Any] | None,
    unit_system: str = "imperial",
    pressure_unit: str = "hpa",
) -> dict[str, Any]:
    """Convert one normalized reading into configured display units."""
    result = convert_reading(reading, unit_system, pressure_unit)
    for field in ("temperature", "dew_point", "wind_chill", "heat_index", "indoor_temperature", "wind_speed", "wind_gust", "daily_max_wind", "pressure", "absolute_pressure", "indoor_pressure", "indoor_absolute_pressure"):
        if isinstance(result.get(field), (int, float)):
            result[field] = round(float(result[field]), 1)
    for field in ("rain_rate", "rain_total", "rain_event", "rain_week", "rain_month", "rain_year", "rain_lifetime", "rain_increment"):
        if isinstance(result.get(field), (int, float)):
            result[field] = round(float(result[field]), 2)
    return result


def register_routes(app: FastAPI) -> None:
    @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
    async def favicon_ico(request: Request) -> Response:
        """Serve the multi-size Caelus icon for conventional favicon probes."""
        return Response(
            content=b"" if request.method == "HEAD" else FAVICON_ICO,
            media_type="image/x-icon",
        )

    @app.api_route(
        "/caelus-favicon.png", methods=["GET", "HEAD"], include_in_schema=False
    )
    async def favicon_png(request: Request) -> Response:
        """Serve the Safari-compatible Caelus PNG favicon."""
        return Response(
            content=b"" if request.method == "HEAD" else FAVICON_PNG,
            media_type="image/png",
        )

    @app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route(
        "/caelus-favicon.svg", methods=["GET", "HEAD"], include_in_schema=False
    )
    async def favicon_svg(request: Request) -> Response:
        """Serve the cache-distinct Caelus SVG favicon."""
        return Response(
            content="" if request.method == "HEAD" else FAVICON_SVG,
            media_type="image/svg+xml",
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Any:
        settings: AppSettings = app.state.settings
        data_logger: DataLogger = app.state.data_logger
        latest = reading_for_display(
            await asyncio.to_thread(data_logger.get_latest),
            settings.unit_system,
            settings.pressure_unit,
        )
        forecast_service = getattr(app.state, "forecast_service", None)
        forecast = (
            await asyncio.to_thread(forecast_service.get, settings)
            if forecast_service is not None
            else {"ok": False, "provider": settings.forecast_provider, "hours": []}
        )
        moon = await asyncio.to_thread(astronomy_context, settings)
        return app.state.templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "version": __version__,
                "settings": settings,
                "latest": latest,
                "latest_observation_time": format_observation_time(
                    latest.get("timestamp"), settings.timezone
                ),
                "windy_iframe_url": build_windy_iframe_url(
                    settings.windy_iframe_url, settings.latitude, settings.longitude
                ),
                "csrf_token": app.state.csrf_token,
                "moon": moon,
                "forecast": forecast,
                "decisions": build_decisions(forecast),
                "display_units": {
                    field: display_unit_for(field, settings.unit_system, settings.pressure_unit)
                    for field in ("temperature", "pressure", "wind_speed", "wind_gust", "rain_total")
                },
                "metric_display_options": metric_display_options(),
            },
        )

    @app.get("/healthz")
    async def healthz() -> Response:
        task = app.state.poller.task
        if task is None or task.done():
            detail = "poller is not running"
            if task is not None and task.cancelled():
                detail = "poller was cancelled"
            elif task is not None and task.exception() is not None:
                detail = f"poller failed: {task.exception()}"
            return JSONResponse(
                {"status": "degraded", "detail": detail},
                status_code=503,
            )
        return JSONResponse({"status": "ok"})

    @app.post("/settings")
    async def save_settings(
        settings_pane: str = Form("all"),
        gateway_url: str | None = Form(None),
        poll_interval_seconds: int | None = Form(None),
        location_name: str | None = Form(None),
        latitude: float | None = Form(None),
        longitude: float | None = Form(None),
        use_ip_location: bool | None = Form(None),
        timezone_name: str | None = Form(None),
        forecast_provider: str | None = Form(None),
        theme: str | None = Form(None),
        unit_system: str | None = Form(None),
        metric_display_styles: str | None = Form(None),
        retention_days: int | None = Form(None),
        export_format: str | None = Form(None),
        windy_iframe_url: str | None = Form(None),
        csrf_token: str = Form(""),
    ) -> Response:
        if not secrets.compare_digest(csrf_token, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        allowed_panes = {"all", "station", "location", "forecast", "appearance", "data-map"}
        if settings_pane not in allowed_panes:
            raise HTTPException(status_code=422, detail="unknown settings pane")

        settings: AppSettings = app.state.settings
        candidate = replace(settings)
        try:
            if settings_pane in {"all", "station"}:
                candidate.gateway_url = validate_gateway_url(gateway_url or candidate.gateway_url)
                candidate.poll_interval_seconds = min(
                    3600,
                    max(
                        60,
                        poll_interval_seconds
                        if poll_interval_seconds is not None
                        else candidate.poll_interval_seconds,
                    ),
                )
            if settings_pane in {"all", "location"}:
                next_latitude = candidate.latitude if latitude is None else latitude
                next_longitude = candidate.longitude if longitude is None else longitude
                if not -90 <= next_latitude <= 90:
                    raise ValueError("latitude must be between -90 and 90")
                if not -180 <= next_longitude <= 180:
                    raise ValueError("longitude must be between -180 and 180")
                previous_coordinates = (candidate.latitude, candidate.longitude)
                candidate.location_name = candidate.location_name if location_name is None else location_name
                candidate.latitude = next_latitude
                candidate.longitude = next_longitude
                if use_ip_location is not None:
                    candidate.use_ip_location = use_ip_location
                candidate.timezone = AppSettings._validate_value(
                    "timezone", timezone_name or candidate.timezone
                )
                if (next_latitude, next_longitude) != previous_coordinates:
                    candidate.location_source = "manual"
                    candidate.location_provider = ""
            if settings_pane in {"all", "forecast"}:
                candidate.forecast_provider = normalize_forecast_provider(
                    forecast_provider or candidate.forecast_provider
                )
            if settings_pane in {"all", "appearance"}:
                candidate.theme = normalize_theme(theme or candidate.theme)
                candidate.unit_system = AppSettings._validate_value(
                    "unit_system", unit_system or candidate.unit_system
                )
                # Retained internally for compatibility with older settings;
                # pressure now follows the selected display-unit preset.
                candidate.pressure_unit = "auto"
                if metric_display_styles is not None:
                    candidate.metric_display_styles = AppSettings._validate_value(
                        "metric_display_styles", json.loads(metric_display_styles)
                    )
            if settings_pane in {"all", "data-map"}:
                next_export = export_format or candidate.export_format
                if next_export not in ALLOWED_EXPORT_FORMATS:
                    raise ValueError("unsupported export format")
                candidate.retention_days = min(
                    max(30, retention_days if retention_days is not None else candidate.retention_days), 366
                )
                candidate.export_format = next_export
                candidate.windy_iframe_url = validate_windy_iframe_url(
                    windy_iframe_url or candidate.windy_iframe_url
                )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        for item in fields(AppSettings):
            setattr(settings, item.name, getattr(candidate, item.name))
        await asyncio.to_thread(settings.save)
        if settings_pane != "all":
            return JSONResponse({"ok": True, "pane": settings_pane})
        return RedirectResponse(url="/", status_code=303)

    @app.post("/api/location/detect")
    async def detect_location(csrf_token: str = Form("")) -> Response:
        if not secrets.compare_digest(csrf_token, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        settings: AppSettings = app.state.settings
        settings.use_ip_location = True
        result = await asyncio.to_thread(
            resolve_ip_location,
            settings,
            force=True,
            persist=True,
        )
        return JSONResponse(result, status_code=200 if result.get("ok") else 503)

    async def ecowitt_json(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON request") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        if not secrets.compare_digest(
            str(payload.get("csrf_token") or ""), app.state.csrf_token
        ):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        return payload

    @app.get("/api/ecowitt/status")
    async def ecowitt_status() -> Dict[str, Any]:
        gateway = getattr(app.state, "gateway", None)
        if gateway is None:
            return {"enabled": False, "state": "unavailable", "label": "Gateway service unavailable"}
        return gateway.status()

    @app.post("/api/ecowitt/discover")
    async def ecowitt_discover(request: Request) -> Response:
        payload = await ecowitt_json(request)
        try:
            result = await asyncio.to_thread(
                app.state.gateway.discover, payload.get("gateway_url")
            )
        except EcowittGatewayError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse(result)

    @app.post("/api/ecowitt/save")
    async def ecowitt_save(request: Request) -> Response:
        payload = await ecowitt_json(request)
        try:
            interval = int(payload.get("poll_interval_seconds", 300))
        except (TypeError, ValueError):
            return JSONResponse(
                {"ok": False, "error": "Poll interval must be a whole number of seconds."},
                status_code=422,
            )
        if not 60 <= interval <= 3600:
            return JSONResponse(
                {"ok": False, "error": "Poll interval must be between 60 and 3600 seconds."},
                status_code=422,
            )
        try:
            discover_for_save = getattr(
                app.state.gateway, "discover_for_save", app.state.gateway.discover
            )
            discovery = await asyncio.to_thread(
                discover_for_save, payload.get("gateway_url")
            )
        except EcowittGatewayError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

        settings: AppSettings = app.state.settings
        candidate = replace(settings)
        candidate.gateway_enabled = True
        candidate.gateway_url = discovery["gateway_url"]
        candidate.gateway_id = discovery["gateway_id"]
        candidate.gateway_model = discovery["gateway_model"]
        candidate.gateway_inventory = discovery["inventory"]
        candidate.gateway_rain_source = discovery["rain_source"]
        candidate.gateway_rain_reset_hour = discovery["rain_reset_hour"]
        candidate.poll_interval_seconds = interval
        for item in fields(AppSettings):
            setattr(settings, item.name, getattr(candidate, item.name))
        await asyncio.to_thread(settings.save)
        initial_reading = await asyncio.to_thread(app.state.poller.poll_once)
        reset_schedule = getattr(app.state.poller, "reset_schedule", None)
        if callable(reset_schedule):
            reset_schedule()
        return JSONResponse(
            {
                **discovery,
                "poll_interval_seconds": interval,
                "initial_reading_stored": initial_reading is not None,
            }
        )

    @app.post("/api/ecowitt/disable")
    async def ecowitt_disable(request: Request) -> Response:
        await ecowitt_json(request)
        app.state.settings.gateway_enabled = False
        await asyncio.to_thread(app.state.settings.save)
        app.state.gateway.last_status.update(
            state="disabled", label="Ecowitt polling disabled", last_error=""
        )
        return JSONResponse({"ok": True, "enabled": False})

    @app.get("/api/astronomy")
    async def get_astronomy() -> Dict[str, Any]:
        return await asyncio.to_thread(astronomy_context, app.state.settings)

    @app.get("/api/readings/current")
    async def get_current_reading() -> Dict[str, Any]:
        """Return the latest stored Ecowitt reading for dashboard refreshes."""
        settings: AppSettings = app.state.settings
        latest = reading_for_display(
            await asyncio.to_thread(app.state.data_logger.get_latest),
            settings.unit_system,
            settings.pressure_unit,
        )
        return {
            "reading": latest,
            "latest_observation_time": format_observation_time(
                latest.get("timestamp"), settings.timezone
            ),
            "poll_interval_seconds": settings.poll_interval_seconds,
            "display_units": {
                field: display_unit_for(field, settings.unit_system, settings.pressure_unit)
                for field in ("temperature", "pressure", "wind_speed", "wind_gust", "rain_total")
            },
        }

    @app.get("/api/metrics/24h")
    async def get_24_hour_metrics() -> Dict[str, Any]:
        """Return valid Ecowitt metric series and statistics for the last day."""
        observed_at = datetime.now(timezone.utc)
        rows = await asyncio.to_thread(
            app.state.data_logger.get_readings_since,
            observed_at - timedelta(hours=24),
        )
        return {
            "hours": 24,
            "generated_at": observed_at.replace(microsecond=0).isoformat(),
            "timezone": app.state.settings.timezone,
            "metrics": build_24_hour_metric_cards(
                rows,
                app.state.settings.unit_system,
                app.state.settings.pressure_unit,
            ),
        }

    @app.get("/api/metrics/range")
    async def get_metric_range(hours: int = 24) -> Dict[str, Any]:
        """Return display-ready metric series for a supported graph window."""
        if hours not in GRAPH_RANGE_HOURS:
            raise HTTPException(status_code=422, detail="unsupported graph range")
        observed_at = datetime.now(timezone.utc)
        rows = await asyncio.to_thread(
            app.state.data_logger.get_readings_since,
            observed_at - timedelta(hours=hours),
        )
        return {
            "hours": hours,
            "generated_at": observed_at.replace(microsecond=0).isoformat(),
            "timezone": app.state.settings.timezone,
            "metrics": build_24_hour_metric_cards(
                rows,
                app.state.settings.unit_system,
                app.state.settings.pressure_unit,
            ),
        }

    @app.get("/api/forecast")
    async def get_forecast(force: bool = False) -> Dict[str, Any]:
        forecast_service = getattr(app.state, "forecast_service", None)
        if forecast_service is None:
            return {"ok": False, "reason": "forecast service unavailable"}
        return await asyncio.to_thread(forecast_service.get, app.state.settings, force=force)

    @app.get("/export")
    async def export_data(format: str = "csv") -> Response:
        settings: AppSettings = app.state.settings
        data_logger: DataLogger = app.state.data_logger
        if format not in ALLOWED_EXPORT_FORMATS:
            raise HTTPException(status_code=422, detail="unsupported export format")
        payload = await asyncio.to_thread(
            data_logger.export_readings,
            settings.retention_days,
            format,
            settings.unit_system,
            settings.pressure_unit,
        )
        content_type = "text/csv" if format == "csv" else "application/json"
        return Response(payload, media_type=content_type)

    @app.post("/poll")
    async def poll_gateway() -> Dict[str, Any]:
        reading = await asyncio.to_thread(app.state.poller.poll_once)
        if reading is None:
            return {"status": "error", "message": "gateway fetch failed"}
        return {"status": "ok", "reading": reading}
