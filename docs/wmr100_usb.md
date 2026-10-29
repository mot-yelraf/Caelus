# Oregon Scientific WMR100-family USB

Caelus can collect live readings from a WMR100-family console attached to the
computer running Caelus. Ecowitt and AcuRite can stay enabled; each station has
independent current readings, graphs, exports, and SQLite history.

The configured console choices are WMR100, WMR100N, WMR88, WMR88A, WMR180,
WMR180A, and WMRS200. These families follow the
[WeeWX compatibility list](https://weewx.com/docs/5.5/hardware/drivers/).
**WMRS200 is different from WMR200.** WMR200, WMR300, and WMR89 are not supported
by this adapter. Model selection records the configured hardware; USB ID
`0fde:ca01` does not identify the precise console model.

Coverage is based on public protocol documentation, synthetic packets, and
simulated USB/HID devices. No physical console or Raspberry Pi has been validated.
Treat all listed model/platform combinations as awaiting hardware validation.

## Setup

1. Run the standard installer as your normal account. Python USB dependencies
   are included. On Raspberry Pi OS/Linux, accept its weather-console USB access
   setup, then unplug/reconnect the console. The dedicated elevated helper installs
   libusb when needed and grants your existing primary group mode 0660 access to
   AcuRite `24c0:0003` and Oregon Scientific `0fde:ca01` only. The runtime remains
   user-owned. Other distributions may require installing libusb manually.
2. Close other software reading the same console, including WeeWX. Connect the
   console by USB and pair its sensors using the console's own controls.
3. Open **Settings > Station > Oregon Scientific USB console**, select the
   model, enable it, and save. Leave the optional USB serial blank when only one
   compatible console is connected. Multiple consoles require a unique serial;
   multiple serial-less consoles are not automatically selected.
4. Select **Oregon Scientific USB** in the dashboard station picker. Set the
   history interval to 60–3600 seconds. Sampling runs independently of this interval.
5. Set the console altitude under **Place & coordinates** to obtain an estimated
   barometric pressure using the existing NWS altimeter calculation. With altitude
   blank, the headline displays raw absolute pressure. The console's relative
   pressure value is deliberately unused because calibration differs across models.

The Linux helper retains its existing filename and automation setting for upgrade
compatibility: `/etc/udev/rules.d/70-caelus-acurite.rules` and
`CAELUS_SETUP_ACURITE_USB=yes|no`. Rerun the installer to update an older rule.
macOS and Windows use native HIDAPI with a five-second worker deadline and do
not require replacing the operating system HID driver. Native sessions reopen
periodically and resynchronize packet framing; packets at session boundaries can
be missed. Their continuous-acquisition behavior requires physical validation.

For an installation at `/home/pi/Caelus`, Oregon history is stored separately at
`/home/pi/Caelus/data/wmr100.db`; disabling acquisition preserves that history.
Substitute your actual absolute installation path when troubleshooting.

## Measurements and semantics

The adapter decodes indoor temperature/RH on channel 0, outdoor temperature/RH
on channel 1, wind speed/gust/direction, raw absolute pressure, rain rate, and
optional UV index. Extra temperature channels and temperature-only packets are
not stored. Missing sensors and invalid fields remain unavailable; zero remains
valid. Sensor updates expire individually after 180 seconds, so indoor packets
cannot keep old outdoor weather fresh. Battery status is reported per sensor;
radio signal strength is unavailable.

Rain's total counter means **since console reset**, not today or the last 24
hours. It is handled as a rolling hundredths-of-an-inch counter, with its reset
date included in provenance. SQLite retains the baseline across restarts. A
changed source/reset date starts a new baseline without inventing rainfall.
**Recorded rain today** sums observed increments in the configured timezone;
missing baselines, outages, and unsampled reset boundaries can leave gaps. A
rolling 24-hour value is never presented as calendar-day rain.

The sampler enables live USB input and reads interrupt reports. It does not read
archives, set the console clock, pair sensors, change console mode, or reset it.
The console clock is ignored; timestamps are UTC receipt times. Checksums,
packet lengths, stream bounds, and sensor value bounds are validated locally.

Protocol references: [WLoggerDaemon's public protocol notes](https://github.com/ejeklint/WLoggerDaemon/blob/master/Station_protocol.md)
and [WeeWX WMR100 field notes](https://github.com/weewx/weewx/blob/master/src/weewx/drivers/wmr100.py).
The latter correct rain scaling to hundredths of an inch. Caelus uses its own
implementation and has no WeeWX runtime dependency.

For hardware validation, compare each available field with the console display,
including negative temperature, calm wind, north, pressure, rain increments,
sensor battery indications, and UV. Exercise unplug/reconnect, disabled/re-enabled
acquisition, stale RF sensors, application restart, and shutdown. Check both the
station-specific dashboard and JSON/CSV exports. Do not claim physical support
from protocol-fixture tests alone.
