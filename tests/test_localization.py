from string import Formatter

import pytest

from caelus.localization import CATALOGS, resolve_display_locale
from caelus.weather_translation import TARGETS


def test_system_uses_quality_and_regional_formats():
    locale = resolve_display_locale("system", "en-US;q=0.5, es-AR;q=0.9, de;q=0, bad_thing")
    assert (locale.language, locale.region) == ("es-419", "es-AR")
    assert locale.number(12.5) == "12,5"
    assert locale.translate("Message without a translation") == "Message without a translation"


@pytest.mark.parametrize("language", CATALOGS)
def test_catalog_preserves_message_arguments(language):
    formatter = Formatter()
    for source, translated in resolve_display_locale("system", language).messages.items():
        assert translated.strip(), source
        source_fields = {field for _, field, _, _ in formatter.parse(source)}
        translated_fields = {field for _, field, _, _ in formatter.parse(translated)}
        assert source_fields - {None} == translated_fields - {None}, source


@pytest.mark.parametrize("language", CATALOGS)
def test_catalog_covers_all_existing_messages(language):
    expected = resolve_display_locale("system", "es").messages
    locale = resolve_display_locale("system", language)
    assert locale.messages.keys() == expected.keys()
    assert locale.language in TARGETS


@pytest.mark.parametrize(("preference", "language", "region", "formatted"), [
    ("ar-EG", "ar", "ar-EG", "١٢٫٥"),
    ("ar-MA", "ar", "ar-MA", "12,5"),
    ("de-CH", "de-DE", "de-CH", "12.5"),
    ("pt-PT", "pt-BR", "pt-PT", "12,5"),
    ("zh-CN", "zh-Hans-CN", "zh-Hans-CN", "12.5"),
    ("zh-SG", "zh-Hans-CN", "zh-Hans-SG", "12.5"),
    ("zh-TW", "en-US", "zh-Hant-TW", "12.5"),
    ("zh-Hant-XX", "en-US", "en-US", 12.5),
    ("hi", "hi-IN", "hi-IN", "12.5"),
    ("ja", "ja-JP", "ja-JP", "12.5"),
    ("it", "it-IT", "it-IT", "12,5"),
    ("nl-BE", "nl-NL", "nl-BE", "12,5"),
    ("pl", "pl-PL", "pl-PL", "12,5"),
    ("uk", "uk-UA", "uk-UA", "12,5"),
])
def test_catalog_and_regional_formatting(preference, language, region, formatted):
    locale = resolve_display_locale("system", preference)
    assert (locale.language, locale.region) == (language, region)
    assert locale.number(12.5) == formatted
    english = resolve_display_locale("english", preference)
    assert (english.language, english.region) == ("en-US", "en-US")


def test_arabic_direction_and_regional_numerals():
    egypt = resolve_display_locale("system", "ar-EG")
    assert egypt.direction == "rtl"
    assert egypt.number(123456.5) == "١٢٣٬٤٥٦٫٥"
    assert egypt.date_label("2026-11-28", "Nov 28") == "٢٨ نوفمبر"
    assert "٢٠٢٦" in egypt.timestamp("2026-11-28T12:00:00Z", "English", "UTC")
    assert resolve_display_locale("english", "ar-EG").direction == "ltr"
    hindi = resolve_display_locale("system", "hi-IN")
    assert hindi.direction == "ltr"
    assert hindi.number(123456.5) == "1,23,456.5"


@pytest.mark.parametrize(("preference", "region", "clock"), [
    ("fr", "fr-CA", "17 h 05"),
    ("fr-CA", "fr-CA", "17 h 05"),
    ("fr-FR", "fr-FR", "17:05"),
])
def test_french_ui_respects_request_region(preference, region, clock):
    locale = resolve_display_locale("system", preference)
    assert (locale.language, locale.region) == ("fr-CA", region)
    assert locale.number(12.5) == "12,5"
    assert locale.clock("17:05", "5:05 PM") == clock


def test_structured_forecast_translates_without_an_online_service():
    locale = resolve_display_locale("system", "es-MX")
    assert locale.forecast_summary({
        "summary": "Clear early, thunderstorms afternoon",
        "summary_message": ["{opening} early, {precipitation} {period}", {
            "opening": "Clear", "precipitation": "thunderstorms", "period": "afternoon",
        }],
    }) == "Despejado al inicio, con tormentas eléctricas por la tarde"


def test_french_forecast_formats_conditions_as_a_sentence():
    locale = resolve_display_locale("system", "fr-CA")
    assert locale.forecast_summary({
        "summary": "Clear early, partly cloudy late",
        "summary_message": ["{opening} early, {later} late", {
            "opening": "Clear", "later": "Partly cloudy",
        }],
    }) == "Dégagé en début de période, puis partiellement nuageux"
