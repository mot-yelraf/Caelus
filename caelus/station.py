"""Optional Ecowitt setup operations, separate from weather acquisition."""

from dataclasses import replace
from threading import RLock
from typing import Any

from caelus.settings import AppSettings


def save_settings_changes(
    settings: AppSettings, changes: dict[str, Any], lock: Any = None
) -> None:
    """Persist validated partial changes under the acquisition lock before applying them."""
    with lock if lock is not None else RLock():
        changes = {
            name: AppSettings._validate_value(name, value)
            for name, value in changes.items()
        }
        candidate = replace(settings, **changes)
        candidate.save()
        for name, value in changes.items():
            setattr(settings, name, value)


class EcowittStationSetup:
    """Own device discovery and settings writes for the Ecowitt setup UI."""

    def __init__(self, settings: AppSettings, gateway: Any, lock: Any = None) -> None:
        self.settings = settings
        self.gateway = gateway
        self.lock = lock if lock is not None else RLock()

    def discover(self, url: Any, *, for_save: bool = False) -> dict[str, Any]:
        """Return validated device metadata without requiring this on other adapters."""
        with self.lock:
            discover = self.gateway.discover
            if for_save:
                discover = getattr(self.gateway, "discover_for_save", discover)
            return discover(url)

    def save(self, discovery: dict[str, Any], interval: int) -> None:
        """Validate and persist a candidate before updating the shared settings in place."""
        updates = {
            "gateway_enabled": True,
            "gateway_url": discovery["gateway_url"],
            "gateway_id": discovery["gateway_id"],
            "gateway_model": discovery["gateway_model"],
            "gateway_inventory": discovery["inventory"],
            "gateway_rain_source": discovery["rain_source"],
            "gateway_rain_reset_hour": discovery["rain_reset_hour"],
            "poll_interval_seconds": interval,
        }
        save_settings_changes(self.settings, updates, self.lock)

    def disable(self) -> None:
        """Disable acquisition without discarding station identity or historical readings."""
        with self.lock:
            save_settings_changes(self.settings, {"gateway_enabled": False})
            self.gateway.disable()
