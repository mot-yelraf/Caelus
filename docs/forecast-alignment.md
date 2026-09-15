# Forecast artwork and mapping contract

Caelus follows `/Users/twfarley/Projects/Sensorius_AI` as the reference implementation.
The copied artwork lives at `/Users/twfarley/Projects/Caelus/static/weather-glyphs`.
Its `manifest.json` pins asset set `sensorius-nine-svg-1` with SHA-256 hashes for
all nine SVGs and the unchanged reference attribution and license files.
Twemoji v17.0.2 artwork and the Sensorius partly-cloudy-night adaptation are
licensed under CC BY 4.0; see the copied `README.md` and `LICENSE-GRAPHICS`.

Treat the Sensorius files as authoritative. To update the set, copy its exact
files, review the artwork/version change, and update the manifest hashes.
`python3 -m pytest -q tests/test_forecast_contract.py` verifies the pinned copies.
Do not independently redraw or optimize a project's SVGs. Local `<img>` elements
render the weather artwork with condition descriptions as alternative text.

## Shared rules

The portable JSON cases and rules are at
`/Users/twfarley/Projects/Caelus/tests/fixtures/forecast-contract-v1.json`.
They can be consumed by Python or browser JavaScript without framework dependencies.
They record Sensorius's existing behavior; changing them requires a coordinated
contract version change in consuming projects.

- Preserve provider condition mappings: WMO codes for Open-Meteo, MET symbols,
  and native NWS short forecast wording. Match artwork keywords in the ordered
  precedence recorded in the JSON; unmatched conditions use the sunny SVG,
  matching Sensorius. There is no emoji rendering fallback.
- Hourly day/night selection uses boolean provider daylight first, then MET
  `_day`/`_night` suffixes. Otherwise calculate solar elevation at the station's
  coordinates and the forecast timestamp, with the station timezone for naive
  timestamps. Daylight means elevation without refraction exceeds −0.833°.
  This handles polar day and night. Incomplete legacy data uses daytime artwork.
- Daily representative conditions use the most frequent normalized condition,
  with ties resolved by first chronological occurrence. Daily and today's
  summary artwork always use daytime variants, independently of summary prose.
- Sort samples by local timestamp and retain those starting at or after now
  minus 90 minutes. Show the first 24 samples. Today's summary uses the current
  station-local date, falling back to those 24 samples when necessary. Daily
  cards cover the next six available local dates, excluding today.
- Aggregate temperature, humidity, and wind ranges from sample extrema;
  precipitation probability uses the maximum and precipitation amounts are
  summed. The representative condition uses unweighted sample counts.

The hourly display is 24 **samples**, which may span longer than 24 hours for
coarse provider data. Caelus environmental decisions retain their separate
elapsed 24-hour window. Matching artwork cannot make different providers,
locations, retrieval times, or sample coverage produce identical predictions.

Cache format 8 retains provider daylight metadata and SVG keys. Older offline
caches receive artwork keys from saved conditions and station solar position
while the service attempts a refresh.
