"""Calculate rain increments using explicit source and counter semantics."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from caelus.observations import Observation, RainPolicy


def counter_identity(source_id: str, policy: RainPolicy) -> str:
    """Identify a counter across restarts, including changes to its reset policy."""
    return json.dumps(
        [
            source_id,
            policy.channel_id,
            policy.kind,
            policy.timezone,
            policy.reset_hour,
            policy.modulus,
        ]
    )


def add_rain_increment(
    reading: dict[str, Any],
    previous: dict[str, Any] | None,
    timestamp: datetime,
    policy: RainPolicy,
) -> None:
    """Preserve supplied intervals; derive only comparable forward counter samples."""
    if reading.get("rain_increment") is not None or policy.kind not in {
        "daily",
        "lifetime",
    }:
        return
    field = "rain_total" if policy.kind == "daily" else "rain_lifetime"
    current = reading.get(field)
    prior = previous.get(field) if previous else None
    if current is None or prior is None:
        return
    try:
        current, prior = float(current), float(prior)
        prior_time = datetime.fromisoformat(str(previous.get("timestamp")))
        if prior_time.tzinfo is None:
            prior_time = prior_time.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp <= prior_time:
            return
    except (TypeError, ValueError):
        return
    crossed_reset = False
    if policy.kind == "daily":
        local = prior_time.astimezone(ZoneInfo(policy.timezone))
        reset = local.replace(hour=policy.reset_hour, minute=0, second=0, microsecond=0)
        if reset <= local:
            reset += timedelta(days=1)
        crossed_reset = reset <= timestamp.astimezone(ZoneInfo(policy.timezone))
    if crossed_reset:
        reading["rain_increment"] = round(current, 3)
    else:
        reading["rain_increment"] = round(max(0.0, current - prior), 3)


def process_rain(observation: Observation, previous: dict[str, Any] | None) -> str:
    """Never subtract counters from a different source, channel, policy or legacy row."""
    identity = counter_identity(observation.source_id, observation.rain)
    if previous and previous.get("rain_counter_id") == identity:
        if observation.rain.kind == "rolling":
            current, prior = (
                observation.rain_counter,
                previous.get("rain_counter_value"),
            )
            if (
                current is not None
                and prior is not None
                and observation.rain_counter_at is not None
            ):
                try:
                    prior_at = datetime.fromisoformat(previous["rain_counter_at"])
                    if prior_at.tzinfo is None:
                        prior_at = prior_at.replace(tzinfo=timezone.utc)
                    if observation.rain_counter_at > prior_at:
                        modulus = observation.rain.modulus
                        delta = current - float(prior)
                        if delta < 0:
                            delta = (
                                current + modulus - float(prior)
                                if prior >= modulus * 0.75 and current <= modulus * 0.25
                                else 0
                            )
                        observation.measurements.setdefault(
                            "rain_increment", round(delta, 3)
                        )
                except (KeyError, TypeError, ValueError):
                    pass
            return identity
        add_rain_increment(
            observation.measurements,
            previous,
            observation.observed_at,
            observation.rain,
        )
    return identity


def add_recorded_daily_rain(
    observation: Observation, previous: dict[str, Any] | None
) -> None:
    """Carry today's recorded total across missing intervals without inventing rain."""
    if observation.rain.kind != "rolling":
        return
    increment = observation.measurements.get("rain_increment")
    total = None
    if previous and previous.get("source_id") == observation.source_id:
        try:
            prior_at = datetime.fromisoformat(previous["timestamp"])
            if prior_at.tzinfo is None:
                prior_at = prior_at.replace(tzinfo=timezone.utc)
            zone = ZoneInfo(observation.rain.timezone)
            if (
                prior_at.astimezone(zone).date()
                == observation.observed_at.astimezone(zone).date()
            ):
                prior_total = previous.get("rain_total")
                total = float(prior_total) if prior_total is not None else None
        except (TypeError, ValueError, KeyError):
            pass
    if increment is not None:
        total = round((total or 0) + increment, 3)
    if total is not None:
        observation.measurements["rain_total"] = total
