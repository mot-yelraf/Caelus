import atexit
import math
import warnings
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.moon import azimuth as moon_azimuth
from astral.moon import elevation as moon_elevation
from astral.moon import phase
from astral.sun import azimuth as sun_azimuth
from astral.sun import elevation as sun_elevation
from astral.sun import sun

PHASES = (
    ("New moon", "🌑"),
    ("Waxing crescent", "🌒"),
    ("First quarter", "🌓"),
    ("Waxing gibbous", "🌔"),
    ("Full moon", "🌕"),
    ("Waning gibbous", "🌖"),
    ("Last quarter", "🌗"),
    ("Waning crescent", "🌘"),
)
PHASE_AGES = (0.0, 3.5, 7.0, 10.5, 14.0, 17.5, 21.0, 24.5)
SUN_RADIUS_KM = 696_340.0
MOON_RADIUS_KM = 1_737.4
ECLIPSE_WINDOW_DAYS = 365
ECLIPSE_LIMIT = 3
SKYFIELD_EPHEMERIS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "skyfield" / "de421.bsp"
)


def _horizontal_vector(azimuth_degrees: float, elevation_degrees: float) -> tuple[float, float, float]:
    """Return an east, north, up unit vector for horizontal coordinates."""
    azimuth = math.radians(azimuth_degrees)
    elevation = math.radians(elevation_degrees)
    return (
        math.cos(elevation) * math.sin(azimuth),
        math.cos(elevation) * math.cos(azimuth),
        math.sin(elevation),
    )


def _moon_time(at: datetime) -> datetime:
    """Normalize to UTC because Astral's lunar position ignores tzinfo offsets."""
    if at.tzinfo is None:
        return at
    return at.astimezone(timezone.utc).replace(tzinfo=None)


def _moon_azimuth(observer: Any, at: datetime) -> float:
    return float(moon_azimuth(observer, _moon_time(at)))


def _moon_elevation(observer: Any, at: datetime) -> float:
    return float(moon_elevation(observer, _moon_time(at)))


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(_dot(vector, vector))
    if length < 1e-10:
        raise ValueError("local sky direction is undefined")
    return tuple(component / length for component in vector)  # type: ignore[return-value]


def _cross(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _local_screen_basis(
    observer: Any, at: datetime
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    moon_vector = _horizontal_vector(_moon_azimuth(observer, at), _moon_elevation(observer, at))
    zenith = (0.0, 0.0, 1.0)
    moon_up_dot = _dot(zenith, moon_vector)
    projected_up = tuple(
        zenith[index] - moon_up_dot * moon_vector[index] for index in range(3)
    )
    try:
        screen_up = _normalize(projected_up)  # toward the observer's zenith
    except ValueError:
        north = (0.0, 1.0, 0.0)
        north_dot = _dot(north, moon_vector)
        screen_up = _normalize(
            tuple(north[index] - north_dot * moon_vector[index] for index in range(3))
        )
    screen_right = _normalize(_cross(moon_vector, screen_up))
    return moon_vector, screen_up, screen_right


def local_bright_limb_angle(observer: Any, at: datetime) -> float:
    """Return the bright-limb direction clockwise from the observer's zenith."""
    moon_vector, screen_up, screen_right = _local_screen_basis(observer, at)
    sun_vector = _horizontal_vector(sun_azimuth(observer, at), sun_elevation(observer, at))

    sun_moon_dot = _dot(sun_vector, moon_vector)
    sun_tangent = _normalize(
        tuple(sun_vector[index] - sun_moon_dot * moon_vector[index] for index in range(3))
    )
    clockwise_from_up = math.degrees(
        math.atan2(_dot(sun_tangent, screen_right), _dot(sun_tangent, screen_up))
    )
    return round(clockwise_from_up % 360.0, 2)


def local_lunar_north_angle(observer: Any, at: datetime) -> float:
    """Return lunar north's approximate local-sky rotation from the zenith."""
    moon_vector, screen_up, screen_right = _local_screen_basis(observer, at)
    latitude = math.radians(float(observer.latitude))
    north_celestial_pole = (0.0, math.cos(latitude), math.sin(latitude))
    pole_moon_dot = _dot(north_celestial_pole, moon_vector)
    projected_pole = _normalize(
        tuple(
            north_celestial_pole[index] - pole_moon_dot * moon_vector[index]
            for index in range(3)
        )
    )
    clockwise_from_up = math.degrees(
        math.atan2(_dot(projected_pole, screen_right), _dot(projected_pole, screen_up))
    )
    return round(clockwise_from_up % 360.0, 2)


def _best_local_view(observer: Any, local_date: Any, tzinfo: ZoneInfo) -> datetime:
    """Choose the hourly instant when the Moon is highest on the local date."""
    midnight = datetime.combine(local_date, datetime.min.time(), tzinfo=tzinfo)
    candidates = (midnight + timedelta(hours=hour) for hour in range(24))
    return max(candidates, key=lambda candidate: _moon_elevation(observer, candidate))


def _nearest_phase_date(estimated_date: Any, target_age: float) -> Any:
    """Refine an approximate phase date against Astral's non-uniform cycle."""
    candidates = (estimated_date + timedelta(days=offset) for offset in range(-4, 5))

    def phase_distance(candidate: Any) -> float:
        difference = abs(float(phase(candidate)) - target_age)
        return min(difference, 28.0 - difference)

    return min(candidates, key=phase_distance)


def local_phase_cycle(
    observer: Any, tzinfo: ZoneInfo, observed_at: datetime, phase_day: float
) -> list[dict[str, Any]]:
    """Build observer-local snapshots for the eight phases around this lunation."""
    local_now = observed_at.astimezone(tzinfo)
    current_index = int((phase_day / 28.0) * 8 + 0.5) % 8
    cycle: list[dict[str, Any]] = []
    for index, ((name, glyph), target_age) in enumerate(zip(PHASES, PHASE_AGES)):
        estimated_date = (local_now + timedelta(days=target_age - phase_day)).date()
        representative_date = _nearest_phase_date(estimated_date, target_age)
        view_at = _best_local_view(observer, representative_date, tzinfo)
        illumination = round((1 - math.cos(2 * math.pi * target_age / 28.0)) * 50)
        cycle.append(
            {
                "name": name,
                "glyph": glyph,
                "active": index == current_index,
                "index": index,
                "illumination": illumination,
                "bright_limb_angle": local_bright_limb_angle(observer, view_at),
                "disk_rotation": local_lunar_north_angle(observer, view_at),
                "altitude": round(_moon_elevation(observer, view_at), 1),
                "representative_date": view_at.date().isoformat(),
            }
        )
    return cycle


def moon_phase_context(at: datetime | None = None) -> dict[str, Any]:
    """Return Astral's current lunar phase as a display-ready cycle."""
    observed_at = at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    phase_day = float(phase(observed_at.date()))
    position = phase_day / 28.0
    phase_index = int(position * 8 + 0.5) % 8
    illumination = round((1 - math.cos(2 * math.pi * position)) * 50)
    days_to_full = (14.0 - phase_day) % 28.0
    cycle = [
        {"name": name, "glyph": glyph, "active": index == phase_index, "index": index}
        for index, (name, glyph) in enumerate(PHASES)
    ]
    name, glyph = PHASES[phase_index]
    return {
        "name": name,
        "glyph": glyph,
        "illumination": illumination,
        "age_days": round(phase_day, 1),
        "days_to_full": round(days_to_full, 1),
        "phase_index": phase_index,
        "cycle": cycle,
        "updated_at": observed_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _clock_label(at: datetime) -> str:
    """Format a solar event with a portable 12-hour clock label."""
    hour = at.hour % 12 or 12
    return f"{hour}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'}"


def _polar_daylight_duration(local_date: Any, latitude: float) -> str:
    """Return all-day or all-night sunlight duration at a geographic pole."""
    observer = LocationInfo("Pole", "", "UTC", latitude, 0.0).observer
    reference = datetime.combine(
        local_date, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=12)
    minutes = 1440 if sun_elevation(observer, reference) > -0.833 else 0
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _julian_day_datetime(julian_day: float) -> datetime:
    """Convert a Julian day to an approximate UTC datetime."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=julian_day - 2440587.5
    )


def _season_events(year: int) -> list[tuple[str, datetime]]:
    """Approximate the four equinoxes and solstices using Meeus polynomials."""
    value = (year - 2000) / 1000
    coefficients = (
        ("March Equinox", (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057)),
        ("June Solstice", (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030)),
        ("September Equinox", (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078)),
        ("December Solstice", (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032)),
    )
    events = []
    for label, terms in coefficients:
        julian_day = sum(coefficient * value**power for power, coefficient in enumerate(terms))
        events.append((label, _julian_day_datetime(julian_day)))
    return events


def _next_season_event(observed_at: datetime, tzinfo: ZoneInfo) -> dict[str, str]:
    """Return the next equinox or solstice in the station timezone."""
    observed_utc = observed_at.astimezone(timezone.utc)
    candidates = _season_events(observed_utc.year) + _season_events(observed_utc.year + 1)
    label, event = next(item for item in candidates if item[1] > observed_utc)
    local = event.astimezone(tzinfo)
    return {
        "label": label,
        "date": f"{local.strftime('%b')} {local.day}, {local.year}",
        "at": local.isoformat(),
    }


@lru_cache(maxsize=1)
def _skyfield_ephemeris_path() -> Path | None:
    """Find the operator-supplied or packaged Skyfield ephemeris."""
    if SKYFIELD_EPHEMERIS_PATH.exists():
        return SKYFIELD_EPHEMERIS_PATH
    try:
        from skyfield_data import get_skyfield_data_path

        # skyfield-data also ships an aging Earth-orientation file and warns
        # about it here. Caelus deliberately uses Skyfield's current built-in
        # timescale below and needs this package only for the DE421 ephemeris.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            packaged_path = Path(get_skyfield_data_path()) / "de421.bsp"
        return packaged_path if packaged_path.exists() else None
    except (ImportError, OSError):
        return None


@lru_cache(maxsize=1)
def _skyfield_runtime_if_installed() -> tuple[Any, Any] | None:
    """Load an offline ephemeris without downloading data at request time."""
    ephemeris_path = _skyfield_ephemeris_path()
    if ephemeris_path is None:
        return None
    try:
        from skyfield.api import Loader, load_file

        loader = Loader(str(ephemeris_path.parent), verbose=False)
        ephemeris = load_file(str(ephemeris_path))
        close_ephemeris = getattr(ephemeris, "close", None)
        if close_ephemeris is not None:
            atexit.register(close_ephemeris)
        return loader.timescale(builtin=True), ephemeris
    except Exception:
        return None


def _apparent_radius_degrees(radius_km: float, distance_km: Any) -> Any:
    """Return an astronomical body's apparent angular radius in degrees."""
    import numpy

    return numpy.degrees(numpy.arcsin(radius_km / distance_km))


@lru_cache(maxsize=96)
def _next_visible_eclipses_for_hour(
    observed_hour_iso: str,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> tuple[dict[str, str], ...]:
    """Return locally visible eclipses when optional Skyfield data is present."""
    runtime = _skyfield_runtime_if_installed()
    if runtime is None:
        return ()
    from skyfield import almanac, eclipselib
    from skyfield.api import wgs84

    ts, ephemeris = runtime
    observed_at = datetime.fromisoformat(observed_hour_iso)
    start = ts.from_datetime(observed_at)
    end = ts.from_datetime(observed_at + timedelta(days=ECLIPSE_WINDOW_DAYS))
    observer = ephemeris["earth"] + wgs84.latlon(latitude, longitude)
    tzinfo = ZoneInfo(timezone_name)
    visible: list[dict[str, str]] = []

    phase_times, phase_types = almanac.find_discrete(
        start, end, almanac.moon_phases(ephemeris)
    )
    for phase_time, phase_type in zip(phase_times, phase_types):
        if int(phase_type) != 0:
            continue
        center = phase_time.utc_datetime().astimezone(timezone.utc)
        samples = [center + timedelta(minutes=minute) for minute in range(-720, 721, 2)]
        sample_times = ts.from_datetimes(samples)
        observer_at = observer.at(sample_times)
        apparent_sun = observer_at.observe(ephemeris["sun"]).apparent()
        apparent_moon = observer_at.observe(ephemeris["moon"]).apparent()
        separation = apparent_sun.separation_from(apparent_moon).degrees
        overlap = _apparent_radius_degrees(
            SUN_RADIUS_KM, apparent_sun.distance().km
        ) + _apparent_radius_degrees(MOON_RADIUS_KM, apparent_moon.distance().km)
        altitude = apparent_sun.altaz()[0].degrees
        indices = [
            index
            for index in range(len(samples))
            if separation[index] <= overlap[index] and altitude[index] >= -0.833
        ]
        if indices:
            event = samples[min(indices, key=lambda index: separation[index])].astimezone(tzinfo)
            visible.append(
                {
                    "kind": "Solar eclipse",
                    "date": f"{event.strftime('%b')} {event.day}, {event.year}",
                    "at": event.isoformat(),
                }
            )

    eclipse_times, eclipse_types, details = eclipselib.lunar_eclipses(
        start, end, ephemeris
    )
    for index, (eclipse_time, eclipse_type) in enumerate(
        zip(eclipse_times, eclipse_types)
    ):
        center = eclipse_time.utc_datetime().astimezone(timezone.utc)
        contact_radius = float(details["moon_radius_radians"][index]) + float(
            details["penumbra_radius_radians"][index]
        )
        closest = float(details["closest_approach_radians"][index])
        half_minutes = math.ceil(
            math.sqrt(max(0.0, contact_radius**2 - closest**2)) / 0.0092 * 60
        )
        samples = [
            center + timedelta(minutes=minute)
            for minute in range(-half_minutes, half_minutes + 1, 10)
        ]
        altitudes = (
            observer.at(ts.from_datetimes(samples))
            .observe(ephemeris["moon"])
            .apparent()
            .altaz()[0]
            .degrees
        )
        if any(altitude >= -0.833 for altitude in altitudes):
            event = center.astimezone(tzinfo)
            visible.append(
                {
                    "kind": f"{eclipselib.LUNAR_ECLIPSES[int(eclipse_type)]} lunar eclipse",
                    "date": f"{event.strftime('%b')} {event.day}, {event.year}",
                    "at": event.isoformat(),
                }
            )
    visible.sort(key=lambda event: event["at"])
    return tuple(visible[:ECLIPSE_LIMIT])


def _next_visible_eclipses(
    observed_at: datetime, latitude: float, longitude: float, tzinfo: ZoneInfo
) -> list[dict[str, str]]:
    """Safely resolve observer-visible eclipses for the next twelve months."""
    observed_hour = observed_at.astimezone(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    try:
        return list(
            _next_visible_eclipses_for_hour(
                observed_hour.isoformat(),
                round(latitude, 4),
                round(longitude, 4),
                tzinfo.key,
            )
        )
    except Exception:
        return []


def astronomy_context(settings: Any, at: datetime | None = None) -> dict[str, Any]:
    """Combine Astral moon phase and local sunrise/sunset for settings location."""
    observed_at = at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    result = moon_phase_context(observed_at)
    try:
        timezone_name = str(settings.timezone or "UTC")
        tzinfo = ZoneInfo(timezone_name)
        local = observed_at.astimezone(tzinfo)
        location = LocationInfo(
            str(settings.location_name or "Caelus station"),
            "",
            timezone_name,
            float(settings.latitude),
            float(settings.longitude),
        )
        solar = sun(location.observer, date=local.date(), tzinfo=tzinfo)
        effective_sunset = solar["sunset"]
        if effective_sunset <= solar["sunrise"]:
            effective_sunset += timedelta(days=1)
        daylight_seconds = (effective_sunset - solar["sunrise"]).total_seconds()
        daylight_minutes = round(daylight_seconds / 60)
        next_season = _next_season_event(observed_at, tzinfo)
        eclipse_calculation_available = _skyfield_runtime_if_installed() is not None
        next_eclipses = _next_visible_eclipses(
            observed_at, float(settings.latitude), float(settings.longitude), tzinfo
        )
        if local <= solar["sunrise"]:
            daylight_progress = 0
        elif local >= effective_sunset:
            daylight_progress = 100
        else:
            daylight_progress = round((local - solar["sunrise"]).total_seconds() / daylight_seconds * 100)
        result.update(
            sunrise=solar["sunrise"].strftime("%H:%M"),
            sunset=solar["sunset"].strftime("%H:%M"),
            solar_noon=solar["noon"].strftime("%H:%M"),
            sunrise_display=_clock_label(solar["sunrise"]),
            sunset_display=_clock_label(solar["sunset"]),
            solar_noon_display=_clock_label(solar["noon"]),
            daylight_hours=round(daylight_seconds / 3600, 2),
            daylight_duration=f"{daylight_minutes // 60}h {daylight_minutes % 60:02d}m",
            north_pole_daylight=_polar_daylight_duration(observed_at.date(), 90.0),
            south_pole_daylight=_polar_daylight_duration(observed_at.date(), -90.0),
            next_season_label=next_season["label"],
            next_season_date=next_season["date"],
            next_season_at=next_season["at"],
            next_eclipses=next_eclipses,
            eclipse_calculation_available=eclipse_calculation_available,
            daylight_progress=daylight_progress,
            sun_is_up=solar["sunrise"] <= local < effective_sunset,
            moon_altitude=round(_moon_elevation(location.observer, observed_at), 1),
            bright_limb_angle=local_bright_limb_angle(location.observer, observed_at),
            disk_rotation=local_lunar_north_angle(location.observer, observed_at),
            cycle=local_phase_cycle(location.observer, tzinfo, observed_at, result["age_days"]),
            timezone=timezone_name,
        )
    except Exception:
        result.update(
            sunrise="—",
            sunset="—",
            solar_noon="—",
            sunrise_display="—",
            sunset_display="—",
            solar_noon_display="—",
            daylight_hours=None,
            daylight_duration="—",
            north_pole_daylight="—",
            south_pole_daylight="—",
            next_season_label="Seasonal event unavailable",
            next_season_date="—",
            next_season_at="",
            next_eclipses=[],
            eclipse_calculation_available=False,
            daylight_progress=0,
            sun_is_up=False,
            moon_altitude=None,
            bright_limb_angle=0.0,
            disk_rotation=0.0,
            timezone=str(getattr(settings, "timezone", "UTC") or "UTC"),
        )
    return result
