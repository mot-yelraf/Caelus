# Contributing to Caelus

Thank you for your interest in improving Caelus.

Caelus is a lightweight Python weather dashboard and persistence service for
Ecowitt-compatible gateways. It combines:

- A FastAPI web application
- Read-only Ecowitt LAN discovery and polling
- SQLite weather-history persistence
- Forecast, solar, and lunar calculations
- A cross-platform runtime for Raspberry Pi, macOS, Windows, and Linux

The project is approachable, but stability and compatibility with existing
installations are primary goals.

## Workflow

1. Fork the repository.
2. Create a feature branch from `trunk`.
3. Make focused, well-documented changes.
4. Submit a pull request against `trunk`.

Direct pushes to `trunk` are not accepted. Keep each pull request focused on a
single logical change.

## Areas Where Contributions Are Welcome

- Documentation improvements
- Dashboard clarity, accessibility, and responsive-layout improvements
- Ecowitt gateway mapping and compatibility fixes
- Forecast-provider normalization and fixture coverage
- Solar and lunar calculation improvements
- SQLite persistence, export, and retention fixes
- Cross-platform installer and runtime improvements
- Automated test coverage under `tests/`

## Dependency Policy

Caelus intentionally avoids unnecessary dependencies.

When contributing:

- Prefer the Python standard library where practical.
- Reuse existing dependencies and utilities before adding new ones.
- Do not upgrade major dependencies such as FastAPI, Pydantic, Uvicorn,
  Astral, or Skyfield without discussion.
- Explain why any new dependency is required.

Dependency changes must be considered across Raspberry Pi, macOS, Windows, and
Linux installations.

## Architecture and Async Discipline

Caelus includes FastAPI routes, a scheduled gateway poller, synchronous
Ecowitt HTTP requests, SQLite persistence, and external forecast/location
requests.

When contributing:

- Keep route handlers thin.
- Run blocking HTTP and SQLite work outside the async event loop.
- Keep gateway normalization in `caelus/gateway.py`.
- Keep forecast-provider parsing in `caelus/forecast.py`.
- Preserve the poller's idempotent start and prompt shutdown behavior.
- Discuss major concurrency or architectural refactors before implementation.

Large structural rewrites should be proposed through an issue first.

## Database Changes

Caelus stores weather history in `data/caelus.db`.

If modifying database schema or storage behavior:

- Preserve backward compatibility for existing installations.
- Provide additive migration or compatibility logic.
- Keep historical timestamp queries and exports working.
- Close every SQLite connection explicitly.
- Add focused persistence tests using pytest's `tmp_path`; never write test
  state into the repository's `data/` directory.

## Configuration Hygiene

Runtime configuration is stored in `data/settings.json`, and forecast cache
data is stored in `data/forecast.json`.

Do not commit runtime copies of:

- Station gateway addresses or device inventories
- Precise personal coordinates or location names
- Weather-history databases or forecast caches
- Private network details or credentials

Use defaults, placeholders, and temporary test paths. Gateway URLs must not
contain embedded credentials.

## Code Style

- Prefer clear, explicit naming over abstraction for its own sake.
- Keep modules cohesive and avoid deep or circular imports.
- Reuse existing helpers before creating new ones.
- Add concise docstrings to touched public APIs.
- Keep logging lightweight and operator-visible.
- Preserve stable normalized metric names and settings values.

Clarity and compatibility take precedence over stylistic cleverness.

## Testing Expectations

Install and activate the host-side commit gate once per clone:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
git config core.hooksPath .githooks
```

The tracked pre-commit hook runs `python3 scripts/playwright_verify.py` on the
developer host. A commit is created only after Chromium verifies the dashboard,
core dialogs, first-party requests, and browser console. Playwright is not run
by the GitHub Actions workflow.

Run the smallest relevant tests first, followed by the broader suite when the
change warrants it:

```bash
python3 -m pytest -q tests/test_routes.py
python3 -m pytest -q
python3 -m pytest -q -W error
```

Useful additional checks are:

```bash
python3 -m compileall -q Caelus.py caelus tests
ruff check .
```

When submitting changes, describe:

- Platform and Python version used
- Whether Ecowitt GW1100 hardware was available
- Tests and endpoint checks run
- Web UI or Settings paths exercised
- Database or migration behavior exercised
- Any behavior that remains unverified

Hardware-dependent tests must use fakes or fixtures in the automated suite.

## Pull Request Guidelines

Pull requests should:

- Include a clear summary of what changed and why
- Include verification notes
- Add regression coverage for bug fixes
- Update documentation when behavior changes
- Avoid unrelated formatting or refactoring churn
- Update `caelus/__init__.py` according to the repository versioning rule when
  code content changes

## Project Maturity

Caelus is a pre-1.0 project under active development. Internal structure and
configuration may evolve, but deployed settings, historical readings, and
normalized metric contracts should remain compatible whenever practical.
