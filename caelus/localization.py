"""Resolve request-local display preferences and render translated messages."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from babel import Locale, UnknownLocaleError
from babel.dates import format_datetime, format_skeleton, format_time
from babel.numbers import format_decimal

DEFAULT_LOCALE = "en-US"
CATALOGS = {
    "ar": "ar",
    "de": "de-DE",
    "es": "es-419",
    "fr": "fr-CA",
    "hi": "hi-IN",
    "it": "it-IT",
    "ja": "ja-JP",
    "nl": "nl-NL",
    "pl": "pl-PL",
    "pt": "pt-BR",
    "uk": "uk-UA",
    "zh": "zh-Hans-CN",
}
CATALOG_PATH = Path(__file__).resolve().parents[1] / "static" / "locales"
ARABIC_DIGITS = {
    "arab": str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"),
    "arabext": str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"),
}
PREFERENCE = re.compile(
    r"([a-z]{2,8}(?:-[a-z0-9]{1,8})*|\*)"
    r"(?:\s*;\s*q=(0(?:\.\d{0,3})?|1(?:\.0{0,3})?))?",
    re.IGNORECASE | re.ASCII,
)


@lru_cache
def _catalog(language: str) -> dict[str, str]:
    if language == DEFAULT_LOCALE:
        return {}
    return json.loads((CATALOG_PATH / f"{language}.json").read_text(encoding="utf-8"))


@lru_cache
def _format_locale(region: str) -> Locale:
    return Locale.parse(region, sep="-")


def _display_digits(value: str, locale: Locale) -> str:
    if locale.language == "ar":
        # Babel localizes the separators but emits Latin digits.
        table = ARABIC_DIGITS.get(locale.default_numbering_system)
        if table is not None:
            return value.translate(table)
    return value


@dataclass(frozen=True)
class DisplayLocale:
    """The interface language and the viewer's date and number conventions."""

    language: str = DEFAULT_LOCALE
    region: str = DEFAULT_LOCALE

    @property
    def direction(self) -> str:
        """Return the reading direction of the selected interface catalog."""
        return "rtl" if self.language == "ar" else "ltr"

    @property
    def messages(self) -> dict[str, str]:
        """Return the shared catalog for this interface language."""
        return _catalog(self.language)

    def translate(self, message: str | None, **values: object) -> str:
        """Look up a message with English source text as its fallback."""
        if message is None:
            return ""
        translated = self.messages.get(message, message)
        return translated.format(**values) if values else translated

    def number(self, value: object) -> object:
        """Format a display value without changing form values or API data."""
        if self.region == DEFAULT_LOCALE or not isinstance(value, (int, float)):
            return value
        locale = _format_locale(self.region)
        numbering = "default" if locale.language == "ar" else "latn"
        return _display_digits(format_decimal(value, locale=locale, numbering_system=numbering), locale)

    def date_label(self, value: str, fallback: str, skeleton: str = "MMMd") -> str:
        """Format an ISO calendar date in the selected region."""
        if self.region == DEFAULT_LOCALE or not value:
            return fallback
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return fallback
        locale = _format_locale(self.region)
        return _display_digits(format_skeleton(skeleton, day, locale=locale), locale)

    def clock(self, value: str, fallback: str) -> str:
        """Format a station-local clock value using the selected hour cycle."""
        if self.region == DEFAULT_LOCALE or not value or value == "—":
            return fallback
        try:
            clock = datetime.strptime(value, "%H:%M").time()
        except ValueError:
            return fallback
        locale = _format_locale(self.region)
        return _display_digits(format_time(clock, "short", locale=locale), locale)

    def timestamp(self, value: str, fallback: str, zone: str) -> str:
        """Format a timestamp in the station timezone and selected region."""
        if self.region == DEFAULT_LOCALE or not value:
            return fallback
        try:
            when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return fallback
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        try:
            zoneinfo = ZoneInfo(zone)
        except (KeyError, ValueError):
            return fallback
        locale = _format_locale(self.region)
        return _display_digits(format_datetime(when, "medium", tzinfo=zoneinfo, locale=locale), locale)

    def forecast_summary(self, forecast: dict) -> str:
        """Render a generated forecast headline with its structured parts."""
        fallback = forecast.get("summary", forecast.get("condition", "Forecast unavailable"))
        if self.language == DEFAULT_LOCALE or not forecast.get("summary_message"):
            return self.translate(fallback)
        message, values = forecast["summary_message"]
        localized = {key: self.translate(value) for key, value in values.items()}
        if "later" in localized:
            localized["later"] = localized["later"].lower()
        return self.translate(message, **localized)

    def forecast_synopsis(self, forecast: dict) -> str:
        """Translate a generated synopsis and retain provider-authored prose."""
        if self.language == DEFAULT_LOCALE or not forecast.get("hours"):
            return forecast.get("synopsis", "")
        first, *remaining = forecast["hours"]
        condition = self.translate(first.get("condition"))
        for row in remaining:
            if row.get("condition") != first.get("condition"):
                instant = row.get("time", "")
                message = "{first}, then {next} around {time}"
                if instant[:10] != first.get("time", "")[:10]:
                    message += " next day"
                return self.translate(message, first=condition, next=self.translate(row.get("condition")).lower(),
                                      time=self.clock(instant[11:16], row.get("label", ""))) + "."
        return f"{condition}." if condition else forecast.get("synopsis", "")


def resolve_display_locale(mode: str, accept_language: str) -> DisplayLocale:
    """Use the highest-priority valid browser preference in System mode."""
    if mode != "system":
        return DisplayLocale()
    preferences = []
    for item in accept_language.split(","):
        match = PREFERENCE.fullmatch(item.strip())
        if match and match[1] != "*" and (quality := float(match[2] or 1)) > 0:
            preferences.append((quality, match[1]))
    if not preferences:
        return DisplayLocale()
    tag = max(preferences, key=lambda item: item[0])[1]
    base, *subtags = tag.lower().split("-")
    language = CATALOGS.get(base, DEFAULT_LOCALE)
    if base == "zh" and subtags[:1] == ["hant"]:
        language = DEFAULT_LOCALE
    try:
        locale = Locale.parse(tag, sep="-")
        if base == "zh" and locale.script == "Hant":
            language = DEFAULT_LOCALE
        region = str(locale).replace("_", "-") if locale.territory else language
    except (UnknownLocaleError, ValueError):
        region = language
    return DisplayLocale(language, region)
