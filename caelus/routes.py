import asyncio
import json
import logging
import secrets
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from caelus import __version__
from caelus.acurite_models import CONSOLE_PROFILES, console_profile
from caelus.wmr100 import MODELS as WMR100_MODELS
from caelus.davis import BAUD_RATES as DAVIS_BAUD_RATES
from caelus.astronomy import astronomy_context
from caelus.data_logger import DataLogger
from caelus.forecast import build_decisions, normalize_forecast_provider
from caelus.gateway import EcowittGatewayError
from caelus.station import EcowittStationSetup, save_settings_changes
from caelus.observations import METRIC_UNITS
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
from caelus.theme_manager import (
    MAX_THEME_IMAGES,
    MAX_UPLOAD_BYTES,
    ThemeManager,
    ThemeValidationError,
    is_custom_theme_selection,
)

GRAPH_RANGE_HOURS = {1, 6, 12, 24, 72, 168, 336, 696}
logger = logging.getLogger(__name__)
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

APPLE_TOUCH_ICON = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "icons"
    / "caelus-apple-touch-icon.png"
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
    for field in ("temperature", "feels_like", "dew_point", "wind_chill", "heat_index", "indoor_temperature", "wind_speed", "wind_gust", "daily_max_wind", "pressure", "absolute_pressure", "indoor_pressure", "indoor_absolute_pressure"):
        if isinstance(result.get(field), (int, float)):
            result[field] = round(float(result[field]), 1)
    for field in ("rain_rate", "rain_total", "rain_event", "rain_week", "rain_month", "rain_year", "rain_lifetime", "rain_increment"):
        if isinstance(result.get(field), (int, float)):
            result[field] = round(float(result[field]), 2)
    return result


def register_routes(app: FastAPI) -> None:
    def station_runtime(request: Request, key: str | None = None):
        """Resolve station selection per request, never through mutable global UI state."""
        stations = getattr(app.state, "stations", {})
        if stations:
            selected = key or request.query_params.get("station", app.state.settings.weather_adapter)
            if selected not in stations:
                raise HTTPException(status_code=404, detail="Unknown weather station")
            return stations[selected]
        return SimpleNamespace(key="", name="Weather station", data_logger=app.state.data_logger,
                               poller=app.state.poller, adapter=getattr(app.state, "weather_adapter", None))

    def theme_manager() -> ThemeManager:
        manager = getattr(app.state, "theme_manager", None)
        if not isinstance(manager, ThemeManager):
            manager = ThemeManager(AppSettings.settings_path.parent)
            app.state.theme_manager = manager
        return manager

    @app.api_route("/apple-touch-icon.png", methods=["GET", "HEAD"], include_in_schema=False)
    async def apple_touch_icon(request: Request) -> Response:
        """Serve the 180-pixel Caelus icon for Safari Home Screen installation."""
        return Response(
            content=b"" if request.method == "HEAD" else APPLE_TOUCH_ICON,
            media_type="image/png",
        )

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
        runtime = station_runtime(request)
        data_logger: DataLogger = runtime.data_logger
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
        manager = theme_manager()
        custom_theme_styles = {
            image["selection"]: manager.style_attribute(
                manager.style_values(image["selection"])
            )
            for theme in manager.list_themes()
            for image in theme["images"]
        }
        return app.state.templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "version": __version__,
                "settings": settings,
                "latest": latest,
                "station": (await ecowitt_status(request)).get("station", {}),
                "active_station": runtime.key,
                "active_station_name": runtime.name,
                "station_interval": runtime.poller.settings.poll_interval_seconds if hasattr(runtime.poller, "settings") else settings.poll_interval_seconds,
                "acurite_profiles": CONSOLE_PROFILES,
                "wmr100_models": WMR100_MODELS,
                "davis_baud_rates": DAVIS_BAUD_RATES,
                "acurite_profile": console_profile(settings.acurite_model),
                "available_stations": [{"key": item.key, "name": item.name} for item in getattr(app.state, "stations", {}).values()],
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
                    for field in ("temperature", "feels_like", "wind_chill", "pressure", "indoor_absolute_pressure", "wind_speed", "wind_gust", "rain_total")
                },
                "metric_display_options": metric_display_options(),
                "custom_themes": manager.list_themes(),
                "theme_palettes": manager.palettes(),
                "custom_theme_styles": custom_theme_styles,
                "active_theme_style": custom_theme_styles.get(settings.theme, ""),
            },
        )

    @app.get("/api/themes")
    async def list_custom_themes() -> Response:
        """List registered custom themes and fixed palette choices."""
        manager = theme_manager()
        return JSONResponse({"ok": True, "themes": manager.list_themes(), "palettes": manager.palettes()})

    @app.post("/api/themes")
    async def create_custom_theme(
        name: str = Form(""),
        image_names: list[str] = Form([]),
        palettes: list[str] = Form([]),
        images: list[UploadFile] = File([]),
        csrf_token: str = Form(""),
    ) -> Response:
        """Create a custom theme from validated uploaded images."""
        if not secrets.compare_digest(csrf_token, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        if not (len(images) == len(image_names) == len(palettes)):
            raise HTTPException(status_code=422, detail="Every image requires a name and palette.")
        if not 1 <= len(images) <= MAX_THEME_IMAGES:
            raise HTTPException(status_code=422, detail="Choose between one and five images.")
        uploads = []
        try:
            for image, image_name, palette in zip(images, image_names, palettes):
                content = await image.read(MAX_UPLOAD_BYTES + 1)
                if len(content) > MAX_UPLOAD_BYTES:
                    raise ThemeValidationError("Each image must be 5 MB or smaller.")
                uploads.append({"name": image_name, "palette": palette, "content": content})
            created = await asyncio.to_thread(theme_manager().create_theme, name=name, images=uploads)
        except ThemeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            for image in images:
                await image.close()
        styles = {
            image["selection"]: theme_manager().style_attribute(
                theme_manager().style_values(image["selection"])
            )
            for image in created["images"]
        }
        return JSONResponse({"ok": True, "theme": created, "styles": styles})

    @app.delete("/api/themes/{theme_id}")
    async def delete_custom_theme(theme_id: str, csrf_token: str = Form("")) -> Response:
        """Delete a custom theme collection and fall back if it was selected."""
        if not secrets.compare_digest(csrf_token, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        manager = theme_manager()
        selected_theme = app.state.settings.theme
        selected_collection = None
        if is_custom_theme_selection(selected_theme):
            selected_collection = selected_theme.split(":")[1]
        try:
            deleted = await asyncio.to_thread(manager.delete_theme, theme_id)
        except ThemeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Custom theme was not found.")
        if selected_collection == theme_id:
            app.state.settings.theme = "garden"
            await asyncio.to_thread(app.state.settings.save)
        return JSONResponse({"ok": True, "fallback": "garden" if selected_collection == theme_id else None})

    @app.get("/healthz")
    async def healthz(request: Request) -> Response:
        task = station_runtime(request).poller.task
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
        altitude: str | None = Form(None),
        altitude_unit: str | None = Form(None),
        use_ip_location: bool | None = Form(None),
        timezone_name: str | None = Form(None),
        forecast_provider: str | None = Form(None),
        theme: str | None = Form(None),
        unit_system: str | None = Form(None),
        metric_tile_style: str | None = Form(None),
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
                if altitude is not None or altitude_unit is not None:
                    if altitude_unit not in {None, "m", "ft"}:
                        raise ValueError("altitude unit must be m or ft")
                    altitude_m = float(altitude) if altitude and altitude.strip() else None
                    if altitude_m is not None and altitude_unit == "ft":
                        altitude_m *= 0.3048
                    candidate.altitude_m = AppSettings._validate_value("altitude_m", altitude_m)
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
                requested_theme = normalize_theme(theme or candidate.theme)
                candidate.theme = (
                    theme_manager().normalize_selection(requested_theme)
                    if is_custom_theme_selection(requested_theme)
                    else requested_theme
                )
                candidate.unit_system = AppSettings._validate_value(
                    "unit_system", unit_system or candidate.unit_system
                )
                # Retained internally for compatibility with older settings;
                # pressure now follows the selected display-unit preset.
                candidate.pressure_unit = "auto"
                if metric_tile_style is not None:
                    candidate.metric_tile_style = AppSettings._validate_value(
                        "metric_tile_style", metric_tile_style
                    )
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

        changes = {item.name: getattr(candidate, item.name) for item in fields(AppSettings)
                   if getattr(settings, item.name) != getattr(candidate, item.name)}
        await asyncio.to_thread(
            save_settings_changes, settings, changes, getattr(app.state, "station_lock", None)
        )
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

    def station_setup() -> EcowittStationSetup:
        setup = getattr(app.state, "station_setup", None)
        if setup is None and not hasattr(app.state, "weather_adapter"):
            gateway = getattr(app.state, "gateway", None)
            if gateway is not None:
                setup = EcowittStationSetup(app.state.settings, gateway)
        if setup is None:
            raise HTTPException(status_code=409, detail="This adapter does not support Ecowitt setup")
        return setup

    @app.get("/api/stations")
    async def list_stations() -> Dict[str, Any]:
        """List independent local sources and their in-memory health."""
        return {"stations": [{"key": item.key, "name": item.name, "status": item.adapter.status()}
                             for item in getattr(app.state, "stations", {}).values()]}

    @app.post("/api/stations/{key}/settings")
    async def configure_station(key: str, request: Request) -> Response:
        """Validate and save only one connection's fields; stations may stay enabled."""
        payload = await ecowitt_json(request)
        if key not in getattr(app.state, "stations", {}):
            raise HTTPException(status_code=404, detail="Unknown weather station")
        runtime = station_runtime(request, key)
        settings = app.state.settings
        try:
            prefix = "davis" if key == "davis_vue" else key.removesuffix("_usb")
            enabled_field = "gateway_enabled" if key == "ecowitt" else f"{prefix}_enabled"
            enabled = AppSettings._validate_value(enabled_field, payload.get("enabled"))
            interval_field = "poll_interval_seconds" if key == "ecowitt" else f"{prefix}_poll_interval_seconds"
            interval = payload.get("poll_interval_seconds")
            if isinstance(interval, bool) or not isinstance(interval, int) or not 60 <= interval <= 3600:
                raise ValueError("History interval must be a whole number between 60 and 3600 seconds")
            if key == "ecowitt":
                url_value = payload.get("gateway_url", settings.gateway_url)
                if not isinstance(url_value, str):
                    raise ValueError("Gateway URL must be text")
                url = validate_gateway_url(url_value)
                if enabled:
                    discovery = await asyncio.to_thread(station_setup().discover, url, for_save=True)
                    await asyncio.to_thread(station_setup().save, discovery, interval)
                else:
                    await asyncio.to_thread(save_settings_changes, settings,
                                            {"gateway_enabled": False, "gateway_url": url, interval_field: interval},
                                            app.state.station_lock)
            elif key == "davis_vue":
                port = AppSettings._validate_value("davis_port", payload.get("port", settings.davis_port))
                baud = AppSettings._validate_value("davis_baud_rate", payload.get("baud_rate", settings.davis_baud_rate))
                if enabled and not port:
                    raise ValueError("Set the Davis datalogger serial port before enabling acquisition")
                await asyncio.to_thread(save_settings_changes, settings,
                                        {enabled_field: enabled, "davis_port": port, "davis_baud_rate": baud, interval_field: interval},
                                        app.state.station_lock)
            else:
                model_field = f"{prefix}_model"
                model = AppSettings._validate_value(model_field, payload.get("model", getattr(settings, model_field)))
                serial_field = f"{prefix}_usb_serial"
                serial = AppSettings._validate_value(serial_field, payload.get("usb_serial", ""))
                if len(serial) > 128 or any(ord(char) < 32 for char in serial):
                    raise ValueError("Invalid USB serial number")
                await asyncio.to_thread(save_settings_changes, settings,
                                        {enabled_field: enabled, model_field: model, serial_field: serial.strip(), interval_field: interval},
                                        app.state.station_lock)
        except (TypeError, ValueError, EcowittGatewayError) as exc:
            logger.warning("Station configuration failed", exc_info=True)
            message = "Could not validate the Ecowitt gateway. Check its address and connection." if isinstance(exc, EcowittGatewayError) else str(exc)
            raise HTTPException(status_code=422, detail=message) from exc
        if key in {"wmr100_usb", "davis_vue"}:
            await asyncio.to_thread(runtime.adapter.reset)
        runtime.poller.reset_schedule()
        initial_reading = await asyncio.to_thread(runtime.poller.poll_once) if enabled else None
        return JSONResponse({"ok": True, "enabled": enabled, "poll_interval_seconds": interval,
                             "initial_reading_stored": initial_reading is not None})

    @app.get("/api/station/capabilities")
    async def station_capabilities(request: Request) -> Dict[str, Any]:
        """Describe normalized measurement channels independently of discovery."""
        adapter = station_runtime(request).adapter
        channels = adapter.capabilities() if adapter is not None else ()
        keys = {key for channel in channels for key in channel.metrics}
        return {"channels": [asdict(channel) for channel in channels],
                "units": {key: METRIC_UNITS[key] for key in keys if key in METRIC_UNITS}}

    @app.get("/api/station/status")
    @app.get("/api/ecowitt/status")
    async def ecowitt_status(request: Request) -> Dict[str, Any]:
        adapter = station_runtime(request, "ecowitt" if request.url.path == "/api/ecowitt/status" else None).adapter
        if adapter is not None:
            return adapter.status()
        gateway = getattr(app.state, "gateway", None)
        if gateway is None:
            return {"enabled": False, "state": "unavailable", "label": "Station service unavailable"}
        return gateway.status()

    @app.post("/api/ecowitt/discover")
    async def ecowitt_discover(request: Request) -> Response:
        payload = await ecowitt_json(request)
        try:
            result = await asyncio.to_thread(
                station_setup().discover, payload.get("gateway_url")
            )
        except EcowittGatewayError:
            logger.warning("Ecowitt discovery failed", exc_info=True)
            return JSONResponse(
                {"ok": False, "error": "Could not discover the Ecowitt gateway. Check its address and connection; see server logs for details."},
                status_code=400,
            )
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
            discovery = await asyncio.to_thread(
                station_setup().discover, payload.get("gateway_url"), for_save=True
            )
        except EcowittGatewayError:
            logger.warning("Ecowitt gateway validation before saving failed", exc_info=True)
            return JSONResponse(
                {"ok": False, "error": "Could not validate the Ecowitt gateway. Check its address and connection; see server logs for details."},
                status_code=400,
            )

        await asyncio.to_thread(station_setup().save, discovery, interval)
        ecowitt_poller = station_runtime(request, "ecowitt").poller
        initial_reading = await asyncio.to_thread(ecowitt_poller.poll_once)
        reset_schedule = getattr(ecowitt_poller, "reset_schedule", None)
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
        await asyncio.to_thread(station_setup().disable)
        return JSONResponse({"ok": True, "enabled": False})

    @app.get("/api/astronomy")
    async def get_astronomy() -> Dict[str, Any]:
        return await asyncio.to_thread(astronomy_context, app.state.settings)

    @app.get("/api/readings/current")
    async def get_current_reading(request: Request) -> Dict[str, Any]:
        """Return the selected station's latest stored observation."""
        settings: AppSettings = app.state.settings
        latest = reading_for_display(
            await asyncio.to_thread(station_runtime(request).data_logger.get_latest),
            settings.unit_system,
            settings.pressure_unit,
        )
        return {
            "reading": latest,
            "latest_observation_time": format_observation_time(
                latest.get("timestamp"), settings.timezone
            ),
            "poll_interval_seconds": getattr(station_runtime(request).poller, "settings", settings).poll_interval_seconds,
            "display_units": {
                field: display_unit_for(field, settings.unit_system, settings.pressure_unit)
                for field in ("temperature", "feels_like", "wind_chill", "pressure", "indoor_absolute_pressure", "wind_speed", "wind_gust", "rain_total")
            },
        }

    @app.get("/api/metrics/24h")
    async def get_24_hour_metrics(request: Request) -> Dict[str, Any]:
        """Return the selected station's metric series and statistics for the last day."""
        observed_at = datetime.now(timezone.utc)
        rows = await asyncio.to_thread(
            station_runtime(request).data_logger.get_readings_since,
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
                observed_at,
            ),
        }

    @app.get("/api/metrics/range")
    async def get_metric_range(request: Request, hours: int = 24) -> Dict[str, Any]:
        """Return display-ready metric series for a supported graph window."""
        if hours not in GRAPH_RANGE_HOURS:
            raise HTTPException(status_code=422, detail="unsupported graph range")
        observed_at = datetime.now(timezone.utc)
        rows = await asyncio.to_thread(
            station_runtime(request).data_logger.get_readings_since,
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

    @app.get("/api/weather-climate")
    async def get_weather_climate() -> Response:
        """Return historical statistics without waiting for archive retrieval."""
        service = getattr(app.state, "weather_climate_service", None)
        payload = service.snapshot(app.state.settings) if service else {"status": "unavailable"}
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/forecast")
    async def get_forecast(force: bool = False) -> Dict[str, Any]:
        forecast_service = getattr(app.state, "forecast_service", None)
        if forecast_service is None:
            return {"ok": False, "reason": "forecast service unavailable"}
        return await asyncio.to_thread(forecast_service.get, app.state.settings, force=force)

    @app.get("/export")
    async def export_data(request: Request, format: str = "csv") -> Response:
        settings: AppSettings = app.state.settings
        runtime = station_runtime(request)
        data_logger: DataLogger = runtime.data_logger
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
    async def poll_gateway(request: Request, csrf_token: str = Form("")) -> Dict[str, Any]:
        """Poll the gateway only after validating the browser mutation token."""
        if not secrets.compare_digest(csrf_token, app.state.csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")
        reading = await asyncio.to_thread(station_runtime(request).poller.poll_once)
        if reading is None:
            return {"status": "error", "message": "gateway fetch failed"}
        return {"status": "ok", "reading": reading}
