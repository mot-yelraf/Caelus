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
  and every phase marker is rendered as a representative local-sky view, with
  an optional reference view and sunrise-to-sunrise Sun/Moon event timelines
- Sunrise, solar noon, sunset, total daylight, polar daylight, the next
  seasonal event, and locally visible eclipse details calculated offline with
  Skyfield beside the regional map
- Automatic IP-based coordinate/timezone detection with Astral sunrise and
  sunset calculations
- Selectable MET Norway, Open-Meteo, or US National Weather Service forecasts
- With US NWS selected at a US location, active NWS weather alerts rated Severe
  or Extreme replace today’s summary with the official headline, affected area,
  validity times, description, and instructions. Alerts are checked every minute
  using the station coordinates; hourly and six-day forecasts remain available.
  Today’s summary returns when alerts expire or NWS removes them. During outages,
  unexpired cached alerts remain visible with an unavailable-update notice.
  Alert data uses the [NWS active alerts API](https://www.weather.gov/documentation/services-web-api).
- Today’s forecast includes temperature, RH and wind ranges, an early/late
  sky summary, and a synopsis (native NWS text retains its original units).
  The 24-hour carousel shows temperature, RH, wind and rain/snow chance.
- Six-day forecast details with daily condition summaries, dual-unit
  temperatures and wind, humidity ranges, and precipitation outlook
- Forecast-derived irrigation, frost, and outdoor-work decisions
- Time-based CSV / JSON export and retention settings
- Four built-in scene themes plus device-persistent custom themes created from
  local images and accessible color palettes. Each theme pairs light and tinted
  surfaces across settings and dashboard tiles, with contrasting text; theme
  selectors preview their own palette.
- Modal Settings with keyboard navigation and live theme previews
- Poller-aware health reporting at `/healthz`

The full-screen history graph shows horizontal grid lines for a single metric
and omits them for multiple metrics. Every station-local day boundary has a vertical line and a date tick in `ddmmm`
format (for example, `09Sep`), including across daylight-saving changes. The
header has glyph-only Graph and Settings buttons to the left and right of the title.

Tap or click the Caelus icon or title to reload the dashboard and pick up settings
changed on another device. This also works in an installed Home Screen web app.

Settings saves refresh the dashboard immediately and keep System Settings on the
current pane, preserving drafts in other panes. Action and warning toasts appear
at the top center of the dialog and disappear after five seconds.

To add Caelus to an iPhone Home Screen, open the dashboard in Safari, choose
**Share > Add to Home Screen**, then **Add**. Caelus supplies its 180×180 app
icon and web-app title using [Apple’s Safari web-app metadata](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html).

Caelus also supplies a web app manifest with standard 192×192 and 512×512 Android
icons and a separate 512×512 maskable icon for adaptive launcher shapes. The
manifest opens the dashboard in standalone mode when installed by a supporting
browser.

## Recovery and troubleshooting

Gateway polling retries automatically after failed requests and temporary database
errors. After three consecutive connection failures for a read-only gateway API
request, Caelus also tries that request in a fresh Python process. This allows
readings to resume when the server process has lost LAN access but a new process
can still reach the gateway. The worker has an eight-second deadline and a
512 KiB response limit. Each poll continues trying the direct connection and
returns to it automatically when it succeeds. HTTP errors and malformed data
continue through normal polling retries.

`/api/ecowitt/status` exposes `recovery_active` and fixed summaries in
`connection_error`, `inventory_error`, and `last_error` when those failures occur.
Full exception diagnostics remain in server logs rather than browser responses.
An active recovery path can still report the gateway online when it is receiving
valid readings. Connection-loss
and recovery transitions are logged without repeating an outage warning on
every poll. For a default macOS installation, inspect
`/Users/<username>/Caelus/data/desktop-launch.log`; saved settings and observations
remain in `/Users/<username>/Caelus/data/settings.json` and
`/Users/<username>/Caelus/data/caelus.db`.

Polling starts independently of optional service failures. Forecast warmup runs
in the background so an unavailable provider cannot hold up server readiness;
later forecast and historical-weather requests retry and retain available cached
data. Shutdown stops polling even if another service fails during cleanup.

Manual `POST /poll` requests require the dashboard's `csrf_token` form field,
like other browser mutation requests.

`/healthz` reports whether the polling task is running; use the gateway status
and latest reading timestamp to assess data freshness. A disconnected gateway,
revoked macOS Local Network permission, or failed hardware still requires the
underlying network or device problem to be corrected. The fallback uses the
installed Python runtime and does not restart the application. Legacy gateway
URLs with a path use their existing direct-request retry path. Fatal server
exits require a desktop relaunch or an external service manager; the desktop
launcher does not currently supervise a server after opening its window.

## Location and forecast privacy

Today’s forecast also shows same-calendar-date minimums, maximums, and averages for temperature, relative
humidity, wind speed, and daily rainfall from 1991 through the latest available
archive date. These use [Open-Meteo / ERA5 reanalysis](https://open-meteo.com/en/docs/historical-weather-api),
not station observations. Minimums and maximums are historical extrema from daily
lows/highs, with their year of occurrence (earliest year for ties); averages are
means of daily averages. Rainfall uses minimum, maximum,
and average daily totals including dry days, not rain probabilities. Dates follow the station timezone and values follow the
selected metric/imperial units. The label shows the archive year range; its
tooltip gives the exact coverage and sample count (leap days use only leap years).

Historical retrieval sends the saved coordinates and timezone to Open-Meteo,
regardless of the selected forecast provider. It runs in the background and
stores a compact 366-day summary at
`/Users/twfarley/Projects/Caelus/data/weather_climate.json` for this checkout.
The service checks hourly, refreshes as new archive dates become available
(allowing ERA5’s five-day publication delay), and retries failures after five
minutes. Same-location cached statistics remain visible during outages; changing
coordinates or timezone discards the old displayed values. Loading, unavailable,
and cached states appear in the historical row.

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

For a GW1100/GW1200 with a WS69 array, the Current readings footer shows
**Station reporting** when the current sensor inventory has a signal, and
**Station offline** when unavailable, disabled, or stale. Battery Status is
**OK** (normal), **LOW** (low-battery flag), or **UNKNOWN** when missing,
unrecognized, or unavailable. Inventory is refreshed on each poll; a failed
inventory request does not discard weather readings. These health indicators
are runtime status and are not stored in the historical readings database.

## Standalone installation

The installers ask where Caelus should be installed, defaulting to the existing
`Caelus` folder under the user's home directory. The selected location is saved
in the user's local configuration and offered again during later installations
or updates. They copy the application into that user-owned runtime folder,
create a private `.venv`, install the pinned modules in `requirements.txt`, and
preserve the runtime `data` folder during later installations or updates. The
installed desktop launcher opens Caelus in a centered, resizable pywebview window. Its
default size is 1600 × 1000 pixels and is reduced automatically when the usable
display is smaller. The installation includes Skyfield and its packaged DE421
ephemeris, so eclipse calculations do not download astronomy data while Caelus
is running.

The macOS launcher source is `scripts/macos_launcher.c`. Maintainers can rebuild
the bundled universal executable with `bash scripts/build_macos_launcher.sh` on
a Mac with Command Line Tools; installing Caelus does not require those tools.

The desktop launcher starts the local server when necessary and stops that
server when its window closes. If a healthy Caelus server is already running,
the desktop window attaches to it. On macOS and Linux, quitting also checks for
orphaned servers from the same installation owned by the current user and sends
them a termination signal. Startup also clears these orphans before opening the
dashboard, and macOS Quit runs cleanup through the native termination notification.
Servers still owned by another process and explicit
`CAELUS_GUI_URL` connections are left running.
The separate server launcher remains available for unattended and LAN use.

### macOS

With Python 3.10 or newer installed, run `install.sh` from the downloaded source
directory. For example:

```bash
chmod +x /Users/alice/Downloads/Caelus/install.sh
/Users/alice/Downloads/Caelus/install.sh
```

The installer creates `/Users/alice/Applications/Caelus.app`, following the
Gaiascapes launcher pattern. Double-click it in Finder, or drag it to the Dock.
The app points to the selected runtime; reinstalling updates that path. You can
also run `/Users/alice/Caelus/run_caelus_gui.sh` directly. The Finder app uses a
bundled native launcher for Intel and Apple Silicon, signed locally during
installation, so macOS can associate local-network permission with Caelus.
Allow Caelus in **System Settings → Privacy & Security → Local Network** when
prompted; the first gateway request may fail while the prompt is open, and the
next scheduled poll retries it. Startup failures show
an alert, with details in `/Users/alice/Caelus/data/desktop-launch.log`.

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
The installer creates the Caelus application-menu entry at
`/home/pi/.local/share/applications/weather.caelus.Caelus.desktop` and its hicolor
icon under `/home/pi/.local/share/icons` (or the configured `XDG_DATA_HOME`).
Select Caelus from the application menu to open its desktop window. Use `/home/pi/Caelus/run_caelus.sh` for a
headless server. A graphical GTK session using X11 or Wayland is required for
the desktop launcher.

### Windows 10/11

Install Python 3.10 or newer from python.org with the Python launcher enabled.
Then open PowerShell and run the native installer, for example:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\Alice\Downloads\Caelus\install.ps1
C:\Users\Alice\Caelus\run_caelus_gui.cmd
```

The installer creates icon shortcuts named Caelus on the user's Desktop and in
the Start menu's Caelus folder. Both point to the selected runtime and are updated
when the installer is run again.

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

The graphical selector accepts either the `Caelus` installation folder itself
or its parent directory. Selecting a folder named `Caelus` uses it directly;
selecting any other folder creates or reuses a `Caelus` folder beneath it.
macOS remembers the resulting absolute path in
`/Users/<name>/.config/caelus/install-location`; Linux and Raspberry Pi use
`/home/<name>/.config/caelus/install-location` unless `XDG_CONFIG_HOME` is set;
Windows uses
`C:\Users\<name>\AppData\Local\Caelus\install-location.txt`.

For unattended installation or an exact custom folder name, set
`CAELUS_INSTALL_DIR` before running `install.sh`, or pass `-InstallDir` to
`install.ps1`. An explicit location skips the dialog and becomes the remembered
location after installation succeeds. Existing `.venv` and `data` directories
in that dedicated runtime folder are reused. A headless Unix installer without
a graphical chooser uses the remembered location, or `/home/<name>/Caelus` on
Linux and Raspberry Pi when no location has been saved.

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

Dependency updates must continue to install and pass CI on Python 3.10 and
3.13. CI checks the installed dependency graph with `pip check` and audits
runtime dependencies on both versions. Keep both quality-and-tests checks
required in GitHub branch protection before merging dependency updates.

Starlette 1.8 and newer require Python 3.11, so Dependabot excludes those
versions while Caelus supports Python 3.10. If an existing dependency PR pins
Starlette 1.8 or newer, restore the compatible pin from `requirements.txt`
(currently 1.6.0), or close that PR. Rerunning the same incompatible pin will
not fix installation. Review this exclusion when raising the minimum Python
version; review security alerts manually if a fix requires a newer interpreter.

## Attribution

- System Architecture: TW Farley
- Implementation and Coding: TW Farley and ChatGPT/Codex
