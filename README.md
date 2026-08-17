# Caelus

Caelus is a lightweight Python-based weather dashboard for Ecowitt-compatible
weather station gateways.

For illustrated setup and operating instructions, see the
[Caelus User Guide](docs/user_guide.md).

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
the runtime `data` folder during later installations or updates. The installed
desktop launcher opens Caelus in a centered, resizable pywebview window. Its
default size is 1600 × 1000 pixels and is reduced automatically when the usable
display is smaller. The installation includes Skyfield and its packaged DE421
ephemeris, so eclipse calculations do not download astronomy data while Caelus
is running.

The desktop launcher starts the local server when necessary and stops that
server when its window closes. If a healthy Caelus server is already running,
the desktop window attaches to it and leaves it running when the window closes.
The separate server launcher remains available for unattended and LAN use.

### macOS

With Python 3.10 or newer installed, run `install.sh` from the downloaded source
directory. For example:

```bash
chmod +x /Users/alice/Downloads/Caelus/install.sh
/Users/alice/Downloads/Caelus/install.sh
```

Start the installed application with:

```bash
/Users/alice/Caelus/run_caelus_gui.sh
```

The application appears as Caelus in the macOS Dock and app switcher. The
default runtime database is `/Users/alice/Caelus/data/caelus.db`. To run only
the server, use `/Users/alice/Caelus/run_caelus.sh`.

### Linux and Raspberry Pi OS Bookworm/Trixie

Install Python and venv support if needed:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

Then install and run Caelus. For a Raspberry Pi user named `pi`:

```bash
chmod +x /home/pi/Caelus-source/install.sh
/home/pi/Caelus-source/install.sh
/home/pi/Caelus/run_caelus_gui.sh
```

The default runtime database is `/home/pi/Caelus/data/caelus.db`. The same
commands work on x86-64 or ARM Linux with the appropriate absolute home path.
The first GUI launch creates the per-user application menu entry and hicolor
icon under `/home/pi/.local/share`. Use `/home/pi/Caelus/run_caelus.sh` for a
headless server. A graphical GTK session using X11 or Wayland is required for
the desktop launcher.

### Windows 10/11

Install Python 3.10 or newer from python.org with the Python launcher enabled.
Then open PowerShell and run the native installer, for example:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\Alice\Downloads\Caelus\install.ps1
C:\Users\Alice\Caelus\run_caelus_gui.cmd
```

The desktop window uses the installed Microsoft Edge WebView2 runtime and shows
the native Caelus icon in its window and taskbar. The default runtime database
is `C:\Users\Alice\Caelus\data\caelus.db`. Use
`C:\Users\Alice\Caelus\run_caelus.cmd` for a headless server.

After starting the Caelus server on any platform, open
`http://127.0.0.1:8767` on the Caelus computer or
`http://<Caelus-computer-LAN-IP>:8767` from another device
on the same network. Caelus listens on all network interfaces by default; keep
it on a trusted private LAN and allow inbound TCP port 8767 through the host
firewall if needed.

To choose another runtime folder, set `CAELUS_INSTALL_DIR` before running
`install.sh`, or pass `-InstallDir` to `install.ps1`. Existing `.venv` and
`data` directories in that dedicated runtime folder are reused.

Override the desktop window geometry when needed. Omitting `CAELUS_GUI_X` and
`CAELUS_GUI_Y` lets the operating system center the window:

```bash
CAELUS_GUI_WIDTH=1400 CAELUS_GUI_HEIGHT=900 /home/pi/Caelus/run_caelus_gui.sh
```

```powershell
$env:CAELUS_GUI_WIDTH = "1400"
$env:CAELUS_GUI_HEIGHT = "900"
C:\Users\Alice\Caelus\run_caelus_gui.cmd
```

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
