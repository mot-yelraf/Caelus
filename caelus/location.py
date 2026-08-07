import logging
from typing import Any

import requests

from caelus.settings import AppSettings

logger = logging.getLogger(__name__)

IP_GEOLOCATION_PROVIDERS = (
    ("ipapi.co", "https://ipapi.co/json/"),
    ("ipwho.is", "https://ipwho.is/"),
)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_location(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    latitude = _safe_float(payload.get("latitude", payload.get("lat")))
    longitude = _safe_float(payload.get("longitude", payload.get("lon")))
    if latitude is None or longitude is None:
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    timezone_value = payload.get("timezone")
    if isinstance(timezone_value, dict):
        timezone_name = str(timezone_value.get("id") or timezone_value.get("name") or "UTC")
    else:
        timezone_name = str(timezone_value or "UTC")
    city = str(payload.get("city") or "").strip()
    region = str(payload.get("region") or payload.get("regionName") or "").strip()
    location_name = ", ".join(part for part in (city, region) if part)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone_name,
        "location_name": location_name,
    }


def resolve_ip_location(
    settings: AppSettings,
    *,
    force: bool = False,
    persist: bool = True,
    timeout_seconds: float = 2.5,
    session: Any = requests,
) -> dict[str, Any]:
    """Resolve public-IP location, optionally applying it to shared settings."""
    if not settings.use_ip_location:
        return {"ok": False, "reason": "automatic location is disabled"}
    if not force and settings.latitude != 0.0 and settings.longitude != 0.0:
        return {
            "ok": True,
            "source": settings.location_source or "settings",
            "provider": settings.location_provider,
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "timezone": settings.timezone,
            "location_name": settings.location_name,
        }

    errors = []
    for provider, url in IP_GEOLOCATION_PROVIDERS:
        try:
            response = session.get(
                url,
                timeout=timeout_seconds,
                headers={"User-Agent": "Caelus local-weather-dashboard"},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("success") is False:
                raise ValueError(str(payload.get("message") or "unsuccessful response"))
            resolved = _extract_location(payload)
            if resolved is None:
                raise ValueError("provider returned invalid coordinates")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            continue

        if persist:
            settings.latitude = resolved["latitude"]
            settings.longitude = resolved["longitude"]
            settings.timezone = resolved["timezone"]
            if resolved["location_name"]:
                settings.location_name = resolved["location_name"]
            settings.location_source = "ip"
            settings.location_provider = provider
            settings.save()
        return {"ok": True, "source": "ip", "provider": provider, **resolved}

    message = "; ".join(errors) or "no geolocation provider responded"
    logger.warning("IP geolocation failed: %s", message)
    return {"ok": False, "reason": message}
