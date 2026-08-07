# Caelus

Caelus is a lightweight Python-based weather dashboard for Ecowitt-compatible
weather station gateways.

## Features

- FastAPI backend with server-rendered templates
- Ecowitt gateway polling via configurable URL
- Immersive current-conditions dashboard with wind, rain, atmosphere, indoor
  metrics, and a Windy iframe map
- Calculated eight-phase moon cycle with illumination, lunar age, and a live
  observer-local disk whose bright limb follows the Sun in the user's sky; a
  detailed lunar surface texture remains visible through the calculated phase
  and every phase marker is rendered as a representative local-sky view
- Sunrise, solar noon, sunset, and total daylight beside the regional map
- Automatic IP-based coordinate/timezone detection with Astral sunrise and
  sunset calculations
- Selectable MET Norway, Open-Meteo, or US National Weather Service forecasts
- Six-day forecast details with daily condition summaries, dual-unit
  temperatures and wind, humidity ranges, and precipitation outlook
- Forecast-derived irrigation, frost, and outdoor-work decisions
- Time-based CSV / JSON export and retention settings
- Four device-persistent scene themes: Mountain Garden, Ocean Island, Forest
  River, and Desert Bloom
- Modal System Settings with keyboard navigation and live theme previews
- Poller-aware health reporting at `/healthz`

## Location and forecast privacy

When **Use IP location** is enabled, Caelus sends the server's public IP address
to `ipapi.co` (with `ipwho.is` as a fallback) to obtain an approximate city,
timezone, latitude, and longitude. Astral then uses the saved coordinates
locally to calculate sunrise, sunset, and moon information; Astral does not
perform IP geolocation.

Forecast requests send the saved latitude and longitude to the selected weather
provider (MET Norway, Open-Meteo, or the US National Weather Service). Disable
IP location and enter coordinates manually if you do not want to use a public
IP-geolocation service.

## Run

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Start Caelus:

```bash
python3 Caelus.py
```

3. Open `http://127.0.0.1:8767`

Override the dedicated default port when needed:

```bash
CAELUS_HTTP_PORT=8877 python3 Caelus.py
```

## Test

Run the validation suite with:

```bash
pytest -q
```
