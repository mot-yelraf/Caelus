# Davis Vantage Vue datalogger

Caelus can read a legacy Vantage Vue console through an installed local datalogger.
A datalogger expansion socket alone is not a computer interface: a compatible
logger must be fitted. USB virtual-serial loggers and serial loggers use the same
adapter. A 9-pin serial logger can connect through a suitable USB-to-RS232 adapter.
WeatherLink Live, WeatherLinkIP, the newer touchscreen WeatherLink Console, and
other Davis console models are outside this implementation.

Coverage is based on synthetic protocol fixtures and simulated serial sessions.
No physical Vue, logger, operating-system serial driver, or Raspberry Pi has been
validated yet. The feature is disabled by default and keeps its history separate
from Ecowitt, AcuRite, and Oregon Scientific.

## Connect and configure

1. Rerun the normal installer to install the new PySerial dependency. Connect the
   datalogger to the computer running Caelus and close other console-reading
   applications, including WeatherLink and WeeWX.
2. Identify its local serial port. Examples are `/dev/ttyUSB0` on Raspberry Pi OS,
   `/dev/cu.usbserial-123` on macOS, and `COM3` on Windows. On Linux, prefer the
   device's full `/dev/serial/by-id/` path when available so reconnecting does not
   select a different device. Caelus does not probe unrelated serial equipment.
3. Open **Settings > Station > Davis Vantage Vue**. Enter the port, match the
   console baud rate (normally 19200), enable acquisition, and save. History
   intervals range from 60 to 3600 seconds; live sampling runs independently.
4. Use one enabled Vue ISS transmitter in the console setup. Caelus reads this
   configuration and rejects ambiguous or different transmitter arrangements.
   Leave the console's setup and number-entry screens before collecting data.
5. Match Caelus's configured timezone to the console's timezone and daily-rain
   reset. Select **Davis Vantage Vue** in the dashboard station picker.

For USB loggers that do not expose a serial port, Davis documents a
**CP210X to Serial Converter** utility in its WeatherLink program group. Follow
[Davis's own setup guide](https://www.weatherlink.com/static/software/weatherlink_software_getting_started_guide_pc_2018_11_28.pdf)
to switch a direct-USB logger back to COM-port emulation. Caelus does not change
logger mode or install/replace OS drivers. A required manufacturer virtual-serial
driver must already be installed.

The existing Linux USB helper covers AcuRite and Oregon Scientific, not Davis tty
permissions. Run Caelus under an account with access to the chosen serial device;
inspect the device's owner/group and use your distribution's normal serial-port
access setup. Do not run the application as root. macOS and Windows likewise need
an accessible local serial port, not an HID driver replacement.

## Readings and history

The adapter provides indoor/outdoor temperature and relative humidity, current
wind speed and direction, the console's 10-minute wind gust, relative and absolute
pressure, rain rate, and daily, monthly, yearly, and storm rain. It does not add
UV, solar, extra channels, console forecasts, or archive imports.

Rain conversion follows the console's configured collector size. The displayed
daily total comes from the console; interval rain uses Caelus's existing daily
counter processing. Source, transmitter, collector scale, and timezone identify
the baseline, so incompatible counters are never subtracted. A changed collector
or first sample establishes a new baseline. Missing polls and counter resets can
leave gaps; matching console/Caelus timezones is required for daily rollover.

For an installation at `/home/pi/Caelus`, Vue history is stored at
`/home/pi/Caelus/data/davis.db` and settings at
`/home/pi/Caelus/data/settings.json`. Substitute your actual absolute installation
path. Disabling acquisition retains history. The station query parameter is
`station=davis_vue` for readings, graphs, health, and exports.

The sampler checks packet framing and CRC, reads the rain configuration, and
verifies RF reception progress. Outdoor fields remain unavailable until two
samples show an advancing reception count. They expire after 120 seconds without
RF progress, even if the console still answers. A reception-counter reset requires
new progress. Indoor readings/pressure can remain available during an RF outage.
Sampling failures clear the live cache, appear in station status, and are retried.
Reported battery health concerns the selected ISS; signal strength is unavailable.

Only wakeup, model identification, read-only configuration/diagnostics, and finite
live-packet requests are issued. No clock, calibration, pairing, archive, reset,
or console-mode writes occur. Read/write deadlines bound acquisition; the port
is closed after every session, and shutdown drains in-flight sampling.

Protocol reference: [Davis Vantage Serial Communication Reference 2.6.1](https://www.davis.cz/download/VantageSerialProtocolDocs_v261.pdf).
Caelus implements this protocol independently and does not depend on WeeWX.

## Physical validation

Compare the Vue display with Caelus for negative temperature, calm wind, north,
pressure, rain increments, and the 10-minute gust. Check JSON/CSV exports and
station isolation. Then exercise RF loss, USB disconnect/reconnect, application
restart, midnight rain rollover, and shutdown. Allow two samples for RF progress
after connection or a reception-counter reset. Until these checks pass on the
actual console/logger/platform, fixture coverage is not physical support evidence.
