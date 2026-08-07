import asyncio
import secrets
from dataclasses import fields, replace
from typing import Any, Dict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from caelus import __version__
from caelus.astronomy import astronomy_context
from caelus.data_logger import DataLogger
from caelus.forecast import build_decisions, normalize_forecast_provider
from caelus.location import resolve_ip_location
from caelus.settings import (
    ALLOWED_EXPORT_FORMATS,
    AppSettings,
    build_windy_iframe_url,
    normalize_theme,
    validate_gateway_url,
    validate_windy_iframe_url,
)


def register_routes(app: FastAPI) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Any:
        settings: AppSettings = app.state.settings
        data_logger: DataLogger = app.state.data_logger
        latest = await asyncio.to_thread(data_logger.get_latest) or {}
        forecast_service = getattr(app.state, "forecast_service", None)
        forecast = (
            await asyncio.to_thread(forecast_service.get, settings)
            if forecast_service is not None
            else {"ok": False, "provider": settings.forecast_provider, "hours": []}
        )
        return app.state.templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "version": __version__,
                "settings": settings,
                "latest": latest,
                "windy_iframe_url": build_windy_iframe_url(
                    settings.windy_iframe_url, settings.latitude, settings.longitude
                ),
                "csrf_token": app.state.csrf_token,
                "moon": astronomy_context(settings),
                "forecast": forecast,
                "decisions": build_decisions(forecast),
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
                candidate.poll_interval_seconds = max(
                    30, poll_interval_seconds if poll_interval_seconds is not None else candidate.poll_interval_seconds
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
        except ValueError as exc:
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

    @app.get("/api/astronomy")
    async def get_astronomy() -> Dict[str, Any]:
        return astronomy_context(app.state.settings)

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
        )
        content_type = "text/csv" if format == "csv" else "application/json"
        return Response(payload, media_type=content_type)

    @app.post("/poll")
    async def poll_gateway() -> Dict[str, Any]:
        reading = await asyncio.to_thread(app.state.poller.poll_once)
        if reading is None:
            return {"status": "error", "message": "gateway fetch failed"}
        return {"status": "ok", "reading": reading}
