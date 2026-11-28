# Caelus localization support

Caelus supports 13 interface languages across the dashboard, Caelus Graphum,
System Settings, and live dashboard updates. This guide documents the
implementation in Caelus `v0.26.332.5` and the pattern that Biodynamic_Calendar
and Sensorius_AI can adapt to their own interfaces.

## Supported languages

| Interface language | Catalog locale | Example system preferences |
| --- | --- | --- |
| US English | `en-US` (built-in source text) | `en-US`, `en-GB`, `en-CA` |
| Modern Standard Arabic | `ar` | `ar`, `ar-EG`, `ar-SA`, `ar-MA` |
| German | `de-DE` | `de-DE`, `de-AT`, `de-CH` |
| Latin American Spanish | `es-419` | `es-419`, `es-MX`, `es-AR`, `es-ES` |
| Canadian French | `fr-CA` | `fr-CA`, `fr-FR` |
| Hindi | `hi-IN` | `hi`, `hi-IN` |
| Italian | `it-IT` | `it-IT`, `it-CH` |
| Japanese | `ja-JP` | `ja-JP` |
| Dutch | `nl-NL` | `nl-NL`, `nl-BE` |
| Polish | `pl-PL` | `pl-PL` |
| Brazilian Portuguese | `pt-BR` | `pt-BR`, `pt-PT` |
| Ukrainian | `uk-UA` | `uk-UA` |
| Simplified Chinese | `zh-Hans-CN` | `zh`, `zh-CN`, `zh-Hans`, `zh-SG` |

The catalog locale determines the wording. A supported regional preference
can also determine formatting. For example, `fr-FR` uses the Canadian French
catalog with France’s date and time formats, and `nl-BE` uses the Dutch catalog
with Belgian formats. Traditional Chinese preferences such as `zh-TW` use
English interface text with the available regional formatting.
The Arabic interface reads right to left. The selected region supplies
formatting conventions, including numeral shapes where applicable. Caelus
uses Gregorian dates for weather and astronomy across locales.

## Selecting a language and region

Open **Settings → Appearance → Language & Region**, select **System** or
**English**, then save Appearance.

- **System** is the default. Caelus uses the viewing browser or desktop
  webview’s highest-priority valid `Accept-Language` preference. A
  language-only preference uses its catalog’s default region.
- **English** forces US English wording and US formatting. The mode is
  saved for the installation. In System mode, each viewer can get a
  different locale from the same server.
- An unsupported interface language uses English source text. A recognized
  regional preference can still supply formatting. When the preference is
  absent or unusable, both the language and region default to `en-US`.
  A missing catalog entry also falls back to the English source message.

The viewing locale affects display formatting. The station’s configured
timezone sets the time shown for weather and astronomy, and its measurement
settings determine which units appear. For example, a French-speaking viewer
can see local dates and decimal separators while viewing readings in °F
from a station in another timezone.

## How the implementation fits together

| Component | What Caelus does |
| --- | --- |
| [Settings model](../caelus/settings.py) and [routes](../caelus/routes.py) | Persist `language_mode` as `system` or `english`. Validate and save it with the Appearance pane through the existing CSRF-protected flow. Resolve the locale per request. |
| [Locale resolver](../caelus/localization.py) | Map the browser preference to a catalog language and a formatting locale. Use Babel for server-rendered dates, times, and numbers. |
| [Message catalogs](../static/locales/) | Bundle UTF-8 JSON mapping English source messages to translated messages. Named placeholders allow translators to reorder values within a sentence. |
| [Dashboard template](../templates/dashboard.html) and [client JavaScript](../static/dashboard.js) | Render the initial HTML through Jinja, set the page’s `lang`, and pass the resolved formatting locale and message catalog to JavaScript as JSON. Use the same messages and browser `Intl` formatting for live updates, controls, chart labels, and accessibility text. |
| [Forecast service](../caelus/forecast.py) | Store locale-independent data and structured inputs for generated summaries. Render the summary for each viewer while sharing one provider cache. |
| [Linux/macOS installer](../install.sh) and [Windows installer](../install.ps1) | Copy the static asset tree recursively so new catalogs ship with a standalone install. |

The dashboard HTTP response declares its catalog language with
`Content-Language` and varies by `Accept-Language`. Translation happens
where the data is displayed. Observation keys, timestamps, calculations,
stored readings, and export formats remain compatible across UI languages.

## Bundled translations and provider text

The interface and Caelus-generated forecast summaries use bundled catalogs
and need no translation service. Free-form NWS forecast narratives and alert
text are available in their original wording.

An operator can enable optional machine translation by setting
`CAELUS_TRANSLATION_API_KEY` in the Caelus server environment. When a viewer
using a supported non-English locale requests a translation, the
[server-side adapter](../caelus/weather_translation.py) sends the relevant
public NWS text and language codes to Google Cloud Translation Basic. This
requires internet access and can incur charges. The original stays visible,
and Caelus labels the translated text as machine translation.

The translation route uses the existing CSRF token and selects the current
narrative or active alert on the server. The adapter caches complete
translations by source text and target language. The client checks the source
against the text still on screen before showing the result. Alerts can appear
immediately, and an outage or incomplete translation leaves the original
available.

## Reusing the pattern in other projects

1. **Resolve language and region once per request.** Return an interface
   language and a formatting locale. Start with System and English modes,
   and keep a complete English fallback.
2. **Catalogue complete messages.** Use a shared UTF-8 catalog for server
   templates and client scripts. Preserve named placeholders and include
   chart text, dialogs, validation, status messages, and accessibility
   labels in the inventory.
3. **Keep domain settings explicit.** In Biodynamic_Calendar, format dates
   for the viewer while using the calendar’s configured location and timezone
   for calculations. In Sensorius_AI, format sensor values and statuses for
   the viewer while preserving stored units, identifiers, and timestamps.
4. **Localize structured data at display time.** Store stable event or
   condition keys and raw values. Translate generated sentences from those
   inputs. If a project also needs translation of external prose, make it
   optional and keep the source available.
5. **Package and test the catalogs.** Check message coverage and placeholder
   parity. Test two simultaneous locales, an unsupported locale, an explicit
   English override, regional number and date formats, and a live update.
   Exercise the installed desktop webview as well as a browser.

Caelus verification covers [locale and catalog behavior](../tests/test_localization.py),
[route rendering](../tests/test_routes.py),
[optional translation](../tests/test_weather_translation.py), and
[headless Chromium checks](../scripts/playwright_verify.py). The ten most
recently added catalogs have yet to receive native-speaker review.
