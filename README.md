# Caelus

Caelus is a lightweight Python-based weather dashboard for Ecowitt-compatible
weather station gateways.

## Features

- FastAPI backend with server-rendered templates
- Read-only Ecowitt GW1100-compatible LAN discovery and polling for paired
  7-in-1 weather arrays
- Additively migrated SQLite weather history, including normalized temperature,
  humidity, pressure, wind, UV/solar, rain-rate, interval-rain, and cumulative
  rain metrics
- Immersive current-conditions dashboard with wind, rain, atmosphere, indoor
  metrics, and a Windy iframe map
- Full-width Windy map that defaults to radar and remains interaction-locked
  until deliberately activated, so page scrolling is not captured accidentally
- Responsive 24-hour cards for every valid stored Ecowitt metric, with local
  three-hour graph ticks and complete-window minimum, average, and maximum stats
- Full-screen live history graph with eight selectable windows from one hour to
  29 days and up to four independently scaled metrics across two axes per side
- Calculated eight-phase moon cycle with illumination, lunar age, and a live
  observer-local disk whose bright limb follows the Sun in the user's sky; a
  detailed lunar surface texture remains visible through the calculated phase
  and every phase marker is rendered as a representative local-sky view
- Sunrise, solar noon, sunset, total daylight, polar daylight, the next
  seasonal event, and locally visible eclipse details calculated offline with
  Skyfield beside the regional map
- Automatic IP-based coordinate/timezone detection with Astral sunrise and
  sunset calculations
- Selectable MET Norway, Open-Meteo, or US National Weather Service forecasts
- Six-day forecast details with daily condition summaries, dual-unit
  temperatures and wind, humidity ranges, and precipitation outlook
- Forecast-derived irrigation, frost, and outdoor-work decisions
- Time-based CSV / JSON export and retention settings
- Four device-persistent scene themes: Mountain Garden, Sunny Beach, Forest
  River, and Desert Bloom
- Modal Settings with keyboard navigation and live theme previews
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

## Ecowitt gateway setup

1. Use the Ecowitt app or gateway interface to join the gateway to 2.4 GHz
   Wi-Fi, pair the outdoor 7-in-1 array, and verify live readings.
2. Give the gateway a stable LAN address, preferably with a DHCP reservation.
3. In Caelus, open **Settings → Station**, enter the gateway base URL
   such as `http://192.168.1.100`, and choose **Find Sensors**.
4. Review the discovered sensor inventory, choose a 60–3600 second retrieval
   interval, and choose **Save Gateway**.

Caelus calls only the gateway's read-only local HTTP endpoints. It does not
configure Ecowitt cloud upload, custom-server push, MQTT, Nodus sensors, or
switches. Disabling the gateway stops polling without deleting historical data.

## Standalone installation

The installers copy the application into a user-owned runtime folder, create a
private `.venv`, install the pinned modules in `requirements.txt`, and preserve
the runtime `data` folder during later installations or updates. Administrator
access is not required unless Python or the operating system's venv package is
missing. The installation includes Skyfield and its packaged DE421 ephemeris,
so eclipse calculations do not download astronomy data while Caelus is running.

### macOS

With Python 3.10 or newer installed, run `install.sh` from the downloaded source
directory. For example:

```bash
chmod +x /Users/alice/Downloads/Caelus/install.sh
/Users/alice/Downloads/Caelus/install.sh
```

Start the installed application with:

```bash
/Users/alice/Caelus/run_caelus.sh
```

The default runtime database is `/Users/alice/Caelus/data/caelus.db`.

### Linux and Raspberry Pi OS Bookworm/Trixie

Install Python and venv support if needed:

```bash
sudo apt update
sudo apt install python3 python3-venv
```

Then install and run Caelus. For a Raspberry Pi user named `pi`:

```bash
chmod +x /home/pi/Caelus-source/install.sh
/home/pi/Caelus-source/install.sh
/home/pi/Caelus/run_caelus.sh
```

The default runtime database is `/home/pi/Caelus/data/caelus.db`. The same
commands work on x86-64 or ARM Linux with the appropriate absolute home path.

### Windows 10/11

Install Python 3.10 or newer from python.org with the Python launcher enabled.
Then open PowerShell and run the native installer, for example:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\Alice\Downloads\Caelus\install.ps1
C:\Users\Alice\Caelus\run_caelus.cmd
```

The default runtime database is `C:\Users\Alice\Caelus\data\caelus.db`.

After starting Caelus on any platform, open `http://127.0.0.1:8767` on the
Caelus computer or `http://<Caelus-computer-LAN-IP>:8767` from another device
on the same network. Caelus listens on all network interfaces by default; keep
it on a trusted private LAN and allow inbound TCP port 8767 through the host
firewall if needed.

To choose another runtime folder, set `CAELUS_INSTALL_DIR` before running
`install.sh`, or pass `-InstallDir` to `install.ps1`. Existing `.venv` and
`data` directories in that dedicated runtime folder are reused.

Override the application port when needed:

```bash
CAELUS_HTTP_PORT=8877 /home/pi/Caelus/run_caelus.sh
```

```powershell
$env:CAELUS_HTTP_PORT = "8877"
C:\Users\Alice\Caelus\run_caelus.cmd
```

To restrict Caelus to the local computer again, set `CAELUS_HTTP_HOST` to
`127.0.0.1` before starting it:

```bash
CAELUS_HTTP_HOST=127.0.0.1 /home/pi/Caelus/run_caelus.sh
```

```powershell
$env:CAELUS_HTTP_HOST = "127.0.0.1"
C:\Users\Alice\Caelus\run_caelus.cmd
```

## Source development

To run directly from a source checkout instead of installing:

```bash
python3 -m pip install -r requirements.txt
python3 Caelus.py
```

## Test

Run the validation suite with:

```bash
pytest -q
```
