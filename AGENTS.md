# AGENTS.md

Operational instructions for coding agents working in this repository.
This file is the repo-local source of truth for AI coding agent behavior and
project-specific conventions.

## Scope

- Applies to the entire repository unless a deeper `AGENTS.md` overrides the
  subtree.
- Prefer repo-local `AGENTS.md` guidance over generic coding-agent defaults.
- When switching repositories, confirm the target repo before editing.
- Do not overwrite or revert user changes you did not make unless explicitly
  asked.
- If code files are missing from the workspace, tell the user the repo appears
  incomplete and ask them to provide the missing source.

## Build / Test / Run Commands

- Install dependencies: `python3 -m pip install -r requirements.txt`
- Main runtime entrypoint: `python3 Caelus.py`
- Default UI URL: `http://127.0.0.1:8767`
- Health check: `http://127.0.0.1:8767/healthz`
- The runtime binds to `0.0.0.0` for LAN access by default. Override the bind
  address with `CAELUS_HTTP_HOST` when localhost-only access is required.
- Override the port with `CAELUS_HTTP_PORT`; port 8000 belongs to Sensorius and
  must not be used as the Caelus default.
- Test suite: `python3 -m pytest -q`
- Strict warning check: `python3 -m pytest -q -W error`
- Lint when Ruff is available: `ruff check .`
- Syntax check: `python3 -m compileall -q Caelus.py caelus tests`
- When verifying behavior, prefer `pytest`, `curl`, or terminal-based checks
  over ad hoc GUI interaction.
- Standalone install: `./install.sh` on macOS/Linux/Raspberry Pi or
  `install.ps1` on Windows. Both create a user-owned runtime and `.venv` while
  preserving installed `data/` state.
- This repository does not currently contain `deploy_scripts/`. Do not
  document or invoke them unless they are added.

## Project Context

- Caelus is currently a lightweight FastAPI weather dashboard and persistence
  service for Ecowitt-compatible gateways.
- Supported runtime targets are Raspberry Pi, macOS, Windows, and Linux.
- Initial hardware support is Ecowitt GW1100; future Ecowitt gateway support may
  be added.
- Implemented behavior includes current gateway readings, SQLite persistence,
  scheduled polling, CSV/JSON export, scene themes, a calculated lunar phase
  display, Astral sunrise/sunset calculations, selectable weather forecasts,
  forecast decisions, IP-assisted location setup, and an embedded Windy map.
- IP location resolution is implemented in `caelus/location.py`; keep provider
  calls behind the existing setting or explicit detection action, preserve the
  manual-coordinate path, and disclose that the public IP is sent externally.
- Forecast adapters and their normalized dashboard contract live in
  `caelus/forecast.py`. Keep provider-specific parsing there, preserve cached
  last-good data when a provider is unavailable, and use fixture-based tests.
- Forecast results contain both sampled `hours` and aggregated future `days`.
  Increment `CACHE_FORMAT` whenever this persisted contract changes so older
  cache files cannot silently suppress new dashboard fields.
- Preserve humidity and cloud-cover fields through every provider normalizer;
  the six-day summaries use them for RH ranges and early/late sky descriptions.
- Astral consumes the configured coordinates and timezone; it is not itself an
  IP-geolocation service. Keep that distinction clear in code and docs.
- The live Moon disk is observer-local: `caelus/astronomy.py` projects the Sun's
  direction into the Moon's local sky plane, and `static/dashboard.js` renders
  that bright-limb angle over `static/moon-surface.png`. Do not replace it with
  a fixed emoji/reference phase or bake a phase shadow into the texture.
- The eight phase markers use representative dates around the current lunation,
  sampled near the Moon's highest local altitude. Preserve their per-phase
  `bright_limb_angle` and `disk_rotation` data when changing the lunar header.
- Normalize aware datetimes to UTC before calling Astral's lunar azimuth or
  elevation functions; their underlying Julian-day calculation ignores timezone
  offsets. Solar functions accept aware datetimes and should remain timezone-aware.
- Keep matching waxing/waning markers as exact opposite-polarity pairs in the
  client renderer. Their shared tilt is derived from both local-sky snapshots;
  their individual lunar-surface rotations remain location-specific.
- Keep sunrise, solar noon, sunset, daylight duration, and the daylight track
  derived from the same timezone-aware Astral result so their dates agree.
- On wide screens, keep `.map-row` on the same three-column proportions as
  `.conditions-row`: sunlight aligns with Current Readings, while Windy spans
  the Forecast and Environmental Decisions columns.
- Use absolute on-device file paths in user-facing docs and troubleshooting
  guidance.

## Known Documentation

- Current project and run guide: `README.md`
- The repository does not currently contain a `docs/` tree. If more detailed
  documentation is introduced, keep the README as the concise entrypoint and
  link to canonical topic documents from it.
- If code behavior and docs disagree, inspect and test source behavior first,
  then update the documentation as part of the change.

## Code and Architecture Conventions

- Keep edits minimal, targeted, and easy to review.
- Avoid broad refactors unless explicitly requested.
- Prefer clear, explicit naming over abstraction for its own sake.
- Keep modules cohesive and avoid deep or circular imports.
- Prefer the Python standard library unless a dependency is clearly justified.
- Avoid adding heavy dependencies without explicit discussion.
- Reuse existing utilities before creating new helpers.
- Prefer explicit error handling and operator-visible failures over layered
  silent fallbacks.
- Add concise docstrings for touched public APIs.
- Keep logging lightweight and avoid noisy log churn in hot paths.
- `caelus.app.create_app` owns application-state wiring. Shared settings,
  gateway, logger, poller, templates, and CSRF state live under `app.state`.
- Python 3.10 or newer is required by the current type syntax.

## Configuration and Settings

- Runtime settings are represented by `caelus.settings.AppSettings` and stored
  as JSON at `data/settings.json`.
- Write settings through `AppSettings.save`; do not edit the JSON directly from
  runtime paths.
- `AppSettings.load` must remain tolerant of missing and unknown fields so newer
  and older installations retain all recognized values. Invalid fields should
  be ignored individually with an operator-visible warning, not silently reset
  the entire configuration.
- Reuse `validate_gateway_url` and `validate_windy_iframe_url` at input
  boundaries. Gateway URLs must remain absolute HTTP(S) URLs without embedded
  credentials or fragments. Windy iframe URLs are restricted to the supported
  HTTPS embed endpoint.
- Keep the theme and export-format allowlists synchronized with the template.
- Scene themes use the stable values `garden`, `island`, `river`, and `desert`.
  Preserve `normalize_theme` migrations for the legacy `light`, `dark`, and
  `midnight` values.
- Forecast providers use `met_no`, `open_meteo`, or `us`. Normalize each remote
  payload in `caelus/forecast.py`, retain the last good cache, and never make
  provider-specific response shapes part of the template contract.
- IP geolocation supplies approximate coordinates, city, and timezone. Astral
  consumes those coordinates for solar/lunar calculations; do not describe
  Astral itself as an IP-geolocation provider.
- Poll intervals have a 30-second minimum. Retention is constrained to 30–366
  days. Latitude and longitude must remain within geographic bounds.
- The gateway and poller retain a reference to the shared settings object, so
  update it in place when applying live settings changes.
- Keep setup and runtime behavior idempotent and preserve factory defaults for
  existing installations.

## Persistence Requirements

- Caelus persists runtime data in SQLite through `caelus/data_logger.py`.
- The `readings` table stores normalized sensor metrics, keyed by an ISO-format
  timestamp.
- Preserve backward compatibility for schema and historical query behavior.
- If schema or persistence logic changes, include additive migration logic or a
  compatibility path.
- Sensor readings should be written through `DataLogger.log_reading` unless a
  narrow test bypass is explicitly justified.
- Stored timestamps currently use naive ISO strings representing UTC. Do not
  change their representation without a compatibility migration for historical
  rows and lexical timestamp queries.
- Explicitly close every SQLite connection. A `sqlite3.Connection` context
  manager handles transactions but does not itself close the connection; use
  `contextlib.closing` or an equivalent explicit lifecycle.
- Retention and export windows are elapsed-day filters using timestamp cutoffs,
  never row-count approximations based on an assumed polling interval.
- Generate CSV through Python's `csv` module so commas, quotes, and newlines are
  escaped correctly.
- Pruning runs after successful polls; avoid moving expensive cleanup into
  request hot paths without measurement.

## Gateway and Polling Requirements

- `caelus.gateway.map_gateway_reading` is the single normalization boundary for
  Ecowitt payload keys. Both scheduled and manual polls must use it.
- Preserve normalized metric names because they are database columns and UI
  contracts. In particular, distinguish `None` from legitimate zero values;
  `0.0` wind speed and `0` degrees are valid readings.
- `GatewayPoller.poll_once` owns fetch, normalization, persistence, and pruning.
  Do not duplicate that workflow in routes.
- Gateway HTTP requests and SQLite work are synchronous. Run polling through
  `asyncio.to_thread` when called from async code.
- Keep `GatewayPoller.start` idempotent, allow `stop` to wake the loop promptly,
  and use an awaitable timeout such as `asyncio.wait_for(stop_event.wait(), ...)`.
  Do not pass bare coroutines to `asyncio.wait`.
- Unexpected polling exceptions should be logged and must not permanently
  terminate the scheduled task. An empty gateway response remains a recoverable
  failed fetch.

## Web UI and Route Requirements

- Keep FastAPI route handlers thin.
- Move substantial behavior into supporting modules.
- Avoid blocking operations inside async handlers. Use `asyncio.to_thread` or a
  background task for blocking I/O.
- Keep `/poll` delegated to `GatewayPoller.poll_once` and keep database reads and
  exports off the event loop.
- `/healthz` is poller-aware: return success only while the polling task is
  running and return HTTP 503 when it has stopped, failed, or was cancelled.
- Keep template and static asset wiring consistent.
- Use existing UI templates under `templates/` and assets under `static/`.
- Settings POSTs require the per-process CSRF token created by `create_app` and
  rendered into the dashboard form. New browser-based mutation routes need the
  same protection.
- System Settings live in the native `#settingsDialog` modal. Preserve its
  split navigation, independently scrollable panes, keyboard navigation,
  cancel-time theme restoration, and persistent footer status.
- Each System Settings pane saves independently through `settings_pane`; only
  validate and update fields owned by that pane. Keep partial writes atomic by
  validating a copied `AppSettings` value before updating the shared instance.
- Keep the Windy iframe host restricted, sandboxed, and covered by a conservative
  referrer policy.
- Build the displayed Windy URL with `build_windy_iframe_url` so the station's
  saved coordinates control `lat`, `lon`, detail coordinates, and marker state.
- Windy's cross-origin embed does not expose its spot-forecast controls to
  Caelus. Preserve the dashboard's `data-reset-windy` control, which closes an
  open forecast by reloading the sandboxed iframe from its configured URL.
- In Jinja templates, test sensor values explicitly against `none`; truthiness
  expressions such as `value or 'N/A'` incorrectly hide valid zero readings.

## Sensor Extension Guidance

- Add Ecowitt source keys and casting behavior in `caelus/gateway.py`, then map
  them to stable Caelus names in `map_gateway_reading`.
- Adding a persisted metric requires an additive SQLite schema migration,
  updates to inserts and templates, and focused mapping/persistence tests.
- Do not rename existing metric keys or database columns casually; historical
  rows, exports, and templates depend on them.
- Treat malformed or missing gateway values as unavailable without crashing the
  background polling task.

## Testing and Verification

- Prefer the smallest relevant verification.
- Add regression tests under `tests/` for every bug fix and use `pytest` for code
  verification.
- Use `tmp_path` for SQLite and settings tests. Do not write test state to the
  repository's `data/` directory.
- Use fake gateways and loggers for polling tests so the suite never requires
  Ecowitt hardware or network access.
- Prefer a minimal FastAPI application around `register_routes` for route tests;
  avoid starting the production poller unless lifecycle behavior is the test.
- Run the suite with `-W error` when changing resource or async lifecycles. This
  catches unclosed SQLite connections and unawaited coroutine regressions.
- Use `curl` for endpoint and health-check validation.
- When web UI verification is required, prefer Playwright or headless
  Chromium and avoid macOS GUI Chrome headless mode.
- If VS Code in-app Browser is unavailable, verify using terminal-based tools.
- Report the verification surface used and any UI behavior that remains
  unverified.
- When runtime behavior changes, include concise environment assumptions such
  as platform, gateway type, direct hardware availability, and whether the web
  UI or settings paths were exercised.

## Safety Rules

- Do not run destructive commands without explicit user request.
- Prefer idempotent operations.
- Avoid broad search-and-replace edits unless the task specifically requires
  them.
- Treat settings materialization, normalized metric names, SQLite persistence,
  and gateway polling behavior as compatibility-sensitive.
- Surface major concurrency or storage refactors before implementation.

## Versioning Rule

When you make a code content change, update the canonical `__version__` in
`caelus/__init__.py` using:

```text
v0.<year>.<doy>.<x>
```

- `<year>`: 2-digit year.
- `<doy>`: 3-digit day of year.
- `<x>`: per-day incrementing patch counter.

If the date matches today, increment `<x>` by 1. If the date has changed,
reset `<x>` to `1`.

Documentation-only changes, including edits to this file, do not require a
version bump.
