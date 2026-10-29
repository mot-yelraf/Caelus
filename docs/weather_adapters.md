# Weather adapters

Caelus acquires a primary station observation through `WeatherAdapter`, defined in
[`observations.py`](../caelus/observations.py). An adapter may communicate with a
console or gateway that aggregates sensors, or directly with a supported device.
A new station family providing existing measurements can reuse the poller, SQLite
history, exports, and dashboard.

## Acquisition contract

Implement these synchronous methods:

- `read() -> Observation | None`: perform bounded device communication, normalize
  its payload, and return `None` when unavailable. Unexpected exceptions are logged
  by the scheduled poller, which continues retrying.
- `capabilities()`: describe supported channels and canonical metric keys. This is
  parser support, not a promise that every measurement is currently available.
- `status()`: return the generic `AdapterStatus` fields: source identity,
  connectivity, observation freshness, dashboard station health, and per-sensor
  health. Unknown battery health is `UNKNOWN`. Extra public diagnostics must be
  safe to display. Status and capabilities read local state without network I/O.

Discovery is optional. Ecowitt discovery, device validation, saving, and disabling
live in `EcowittStationSetup`; serial devices and receivers need not imitate it.
Transport retries and Ecowitt's fresh-process LAN recovery remain in its gateway.

An `Observation` contains a stable `source_id`, aware `observed_at` and
`received_at` timestamps, normalized measurements, and a `RainPolicy`.
Timestamps are normalized to UTC. A device timestamp is preferred when available;
the current Ecowitt LAN implementation uses acquisition time because its parsed
live-data contract supplies no observation timestamp. Receipt time remains
separate for adapters that supply device timestamps.

`METRIC_UNITS` is the canonical unit contract: Fahrenheit, mph, inches, in/h,
inHg, percent RH, degrees clockwise from true north, W/m², lux, and UV index.
`pressure` and `indoor_pressure` mean relative pressure; their explicitly named
absolute counterparts retain absolute pressure. `rain_total` means today's
rainfall, never a lifetime counter. Other rain totals retain their named periods.
Display preferences do not change these storage units.

Missing fields and `None` are unavailable. Zero is valid. The shared validator
converts numeric values, rejects booleans and nonfinite/malformed values, and
warns about unknown metrics. Derived Feels Like, Heat Index, and Wind Chill are
calculated centrally from normalized inputs.

## Rain policies and history compatibility

Declare `daily`, `lifetime`, `rolling`, `interval`, or `none`, with a stable rain channel ID.
Rolling counters use separate observation counter values/timestamps and an explicit
modulus; their raw values must not be presented as daily or lifetime totals.
Daily counters use `rain_total` and the declared timezone/reset hour. Lifetime
counters use `rain_lifetime`. Interval sources supply `rain_increment` directly;
a valid adapter-supplied increment is preserved under every policy.

Source, rain channel, policy, timezone, and reset hour identify the stored counter
baseline. A changed identity, a historical row without provenance, or an absent
counter establishes a new baseline without inventing interval rain. Daily reset
boundaries use the new daily total; unexplained counter decreases conservatively
produce zero. Duplicate or older observation times do not produce a derived
increment. A long outage across daily resets cannot reconstruct missing days.

SQLite gains nullable `source_id`, `observed_at`, `received_at`, `rain_counter_id`,
`rain_counter_value`, and `rain_counter_at` columns through the existing additive migration. Historical
rows, metric columns, and naive UTC ISO `timestamp` strings remain valid. New
rows use the observation time as that primary timestamp. CSV/JSON exports include
the additional metadata columns. Following an upgrade, the first counter sample
establishes provenance, so its derived interval rain is unavailable.

The existing acquisition lock also serializes station setup and settings commits
with a poll. Settings are persisted through `AppSettings.save` before updating
the shared object in place; a failed save retains live settings.

## Adding a station family

1. Implement the protocol in a cohesive adapter module, keeping device parsing
   and unit conversion inside that adapter. Use stable device IDs and channel IDs
   when available; changing physical sources must change the rain baseline.
2. Add an explicit constructor in `create_weather_adapter` and the supported
   `weather_adapter` setting validation. Existing settings default to `ecowitt`.
   Tests and embedding applications can inject an adapter with
   `create_app(weather_adapter=adapter)` without adding a production selection.
3. Add the station's runtime name and isolated history in `build_stations`, then
   add optional device setup separately. Station settings has independent Ecowitt
   and AcuRite cards; another family's connection UI must be added when supported.
4. Add fixture payloads and contract tests proving unit conversion, zero/missing
   values, invalid data, timestamps, capabilities, status, and rain behavior.
   The hardware-free second adapter in `test_weather_adapters.py` demonstrates
   reuse of persistence and the current-readings API.

The dashboard uses `/api/station/status`; `/api/ecowitt/status` remains a
compatibility alias. `/api/station/capabilities` exposes channels and canonical
units. Browser setup mutations retain CSRF protection. `/healthz` continues to
report polling-task health separately from source connectivity/data freshness.

## Additional metrics and channels

An inventory entry describes a registered sensor; it does not mean Caelus parses
its measurements. The Ecowitt adapter advertises one primary channel containing
its supported metric fields, including fields unavailable on some hardware.
Unsupported soil probes and extra temperature channels are not advertised as
parsed measurements.

Each observation still represents one primary station. Ecowitt and AcuRite run
concurrently through separate `StationRuntime` adapters, loggers, and pollers in
`caelus/stations.py`. The original Ecowitt database is preserved; AcuRite uses a
separate database. Routes select a runtime through an explicit station query
parameter, keeping browser tabs and exports independent. An optional adapter
sampler has its own start/stop lifecycle; it must not block status requests.

Additional independent measurement channels within a station still require an
additive companion measurements table and explicit primary-channel selection.
New canonical metrics require registry entries, persistence migration,
display/export support, and regression tests. See the [AcuRite USB guide](acurite_usb.md)
for the current direct-USB integration and limits.

## Ecowitt gateway compatibility

| Gateway family | Interface | Verification |
| --- | --- | --- |
| GW1100 | Shared read-only LAN HTTP API | Existing normalization, discovery, and polling tests |
| GW1200 | Same API | Existing compatible polling/inventory test; model recognition test |
| GW2000 | Same API over its LAN address, including Ethernet | Protocol-derived discovery/save/poll/storage/API fixture; no physical device tested |
| GW3000 | Same API over its LAN address, including Ethernet | Protocol-derived discovery/save/poll/storage/API fixture; no physical device tested |

Regional suffixes such as GW2000B and GW3000C are recognized as their gateway
family. Firmware version text is retained, with an optional `Version:` prefix
removed for display. Discovery and status expose `gateway_family`; model identity
is not used to guess units or bypass response validation. Other devices returning
the same API may work but are not listed as supported families.

Ecowitt documents the GW2000 HTTP interface in its
[GW2000 support resources](https://www.ecowitt.com/support/download/178) and
links the shared LAN HTTP protocol from its
[GW3000 support resources](https://www.ecowitt.com/api/quickstart/product?id=336).
The tests use synthetic fixtures derived from that protocol, not hardware captures
or claims of validation across every firmware release.

These gateways can supply the primary outdoor temperature/RH, wind direction,
speed/gusts, solar radiation or illuminance, UV index, traditional or piezo rain,
and indoor temperature/RH/pressure fields that Caelus already persists. Actual
fields depend on the paired hardware. Normalization accepts common-list indoor
fields, separate `wh25` fields, common-list traditional rain fields, separate
`rain`/`piezoRain` fields, and mmHg pressure in addition to existing units.
Explicit indoor/rain sections take precedence over common-list equivalents.
The saved rain-source selection remains authoritative: piezo and disabled rain
do not accidentally consume traditional common-list counters.

The gateway aggregates sensors; Caelus reads their normalized primary weather
values through the shared Ecowitt adapter. Separate WH80 wind/weather sensors,
WH40 rain gauges, and WH90/WS90-style piezo arrays therefore do not require a
WS69 inventory entry to report station health. Battery encodings not yet decoded
remain UNKNOWN rather than interpreting multilevel values as binary flags.

Pair sensors using Ecowitt's own interface first. Then use **Settings > Station >
Find Sensors > Save Gateway** with the gateway base URL. Wi-Fi versus Ethernet
does not change the Caelus adapter. Caelus neither configures radio pairing nor
uses GW3000 SD-card history, cloud accounts, MQTT, irrigation, or device controls.

Discovery can list soil, air-quality, leak, lightning, and extra probe sensors,
but this does not add their independent measurements to storage or the dashboard.
Those channels need the separate metric/channel extensions described above.
