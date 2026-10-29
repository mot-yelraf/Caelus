# AcuRite PC Connect USB setup

Caelus can collect live USB data directly from supported AcuRite PC Connect
consoles connected to the same Raspberry Pi, Linux PC, Mac, or Windows PC that
runs Caelus. Ecowitt can remain enabled at the same time. Choose the station at the top of the dashboard; each
station has its own current readings, graphs, exports, and history.

This implementation is verified with synthetic protocol fixtures and simulated
USB devices. It still needs validation against a physical 01536-RX, including
its console pressure calibration. It targets the console's live R1/R2 reports;
it does not read the console logger or change USB mode. The
[WeeWX AcuRite hardware guide](https://weewx.com/docs/5.5/hardware/acurite/)
states that the 01536 always operates in USB mode 4. The
[WeeWX driver's message maps](https://github.com/weewx/weewx/blob/v5.2.0/src/weewx/drivers/acurite.py)
are the protocol reference for the local decoder.

## Supported console families and mode 4

| Console profile | Listed model aliases | Mode 4 setup |
| --- | --- | --- |
| 01536 | 01536-RX, 06056 | Automatic; no mode menu |
| 01025 | 01025 | Select on console |
| 01035 | 01035 | Select on console |
| 01036 | 01036, 01092, 06006 | Select on console |
| 01525 | 01525 | Select on console |
| 02032 | 02032, 02032C, 02033, 01093, 06037 | Select on console |

For 01025, 01035, 01036, 01525, and 02032 families, use the display's SET menu to
select **USB MODE** or **PC CONNECT MODE 4** before enabling acquisition. Recheck
the setting after loss of console power. The software cannot select or query that
mode for you. These are the live-stream mode-4 paths; no console archive access
is added. The 01536-RX / 06056 retains its automatic mode-4 behavior.

The model selector records the family you configure; a shared USB vendor/product
ID cannot identify the exact model. All profiles share R1 outdoor decoding and R2
console decoding. Pressure calibration is validated from the bytes received,
including both HP03S and the recognized linear layout, rather than guessed from
the selected model. Unknown calibration remains unavailable with a visible error.

These additional families are verified with synthetic protocol fixtures and
simulated transports, not physical devices. Each family still needs raw-report
and measurement validation. Related model groupings are listed in
[AcuRite's display compatibility guide](https://support.acurite.com/hc/en-us/articles/1260802952850-PC-Connect-Display-Unit).

## Install USB support

Standard installation includes the required Python packages: PyUSB on all
platforms and HIDAPI on macOS/Windows. No separate AcuRite Python dependency
installation is needed. Existing installations should rerun their normal installer.

| Platform | USB path | Initial setup |
| --- | --- | --- |
| Raspberry Pi OS / Linux | PyUSB with system libusb | `install.sh` offers administrator-authorized libusb and weather-console udev setup |
| macOS | Native HIDAPI | `install.sh` installs and checks the HID binding; the OS HID driver stays in place |
| Windows | Native HIDAPI | `install.ps1` installs and checks the HID binding; the OS HID driver stays in place |

All three acquisition paths are tested with simulated devices. Physical console
validation is still required for each model and platform. The
[HIDAPI platform guide](https://github.com/libusb/hidapi/wiki) documents native
macOS and Windows HID access; Caelus uses numbered input-report reads through the
[Python HIDAPI binding](https://trezor.github.io/cython-hidapi/api.html).

### Raspberry Pi and Linux permissions

Run `install.sh` as your normal account. It asks whether to configure AcuRite and Oregon Scientific USB
access. Accepting requests administrator authentication through `sudo` in a
terminal or `pkexec` on a supported desktop. Only a dedicated USB helper runs
with elevated privileges; application files, pip, and the virtual environment
remain user-owned.

The helper installs `libusb-1.0-0` with apt if the backend is missing, writes
`/etc/udev/rules.d/70-caelus-acurite.rules`, and reloads udev rules. The rule grants
mode 0660 access only to vendor/products `24c0:0003` (AcuRite) and
`0fde:ca01` (Oregon Scientific) for your account's existing
primary group. No group-membership change or application root access is required.
Unplug/reconnect the console after setup.

You can decline the system step and finish installing the application. Permission
or package-install failures are reported without blocking Ecowitt use. Automatic
libusb package installation supports Debian, Ubuntu, and Raspberry Pi OS; other
Linux distributions must supply libusb through their package manager first.

For an unattended installation, explicitly request or skip the system step with
`CAELUS_SETUP_ACURITE_USB=yes` or `CAELUS_SETUP_ACURITE_USB=no`. Noninteractive
`auto` mode skips privileged setup. A noninteractive terminal run requires cached
sudo authorization; a supported graphical session can use its authentication
agent. To grant access to a different service account, set `CAELUS_USB_USER` to
that existing account's name.

Example for `/home/pi/Caelus` and a service account named `pi` (replace both with
your actual absolute installation path and account):

```bash
CAELUS_SETUP_ACURITE_USB=yes CAELUS_USB_USER=pi /home/pi/Caelus/install.sh
```

If package installation fails because the apt indexes are stale, update them with
`sudo apt-get update` and rerun the installer. If no authentication agent is
available, run the installer from a terminal. Only one program should read the
console at a time; stop WeeWX or other USB weather software before enabling Caelus.

### macOS and Windows

The console remains attached to the native HID driver. This integration requires
neither a Linux permission rule nor a WinUSB/libusb driver replacement. Run the
ordinary installer, connect the console, and enable its Station settings card.
If another program owns the console or the OS denies access, Caelus reports that
condition instead of attempting to change drivers or elevating the application.

Native HID input-report APIs have no caller-supplied timeout. Caelus runs each
native read cycle in a short-lived worker with a five-second timeout; Linux
libusb transfers retain their one-second per-request timeout. Both paths close
USB handles after each cycle. No USB logger, reset, or mode-setting commands run.

## Configure the station

1. Power the console and confirm it receives the outdoor array in its own display.
2. Connect its USB cable to the computer running Caelus.
3. Open **Settings > Station**. The Ecowitt and AcuRite cards save independently.
   Disable and save the Ecowitt card if you are using only AcuRite.
4. Expand **AcuRite USB console**, select your **Console model**, follow its mode-4
   instructions, then select **Enabled**. Choose a history interval from 60 to 3600
   seconds. Leave USB serial number blank when only one matching console is attached. If multiple matching devices exist, selection requires
   an actual USB serial descriptor; otherwise connect only the intended console.
5. Select **Save AcuRite**. Connection status reports missing dependencies,
   permissions, or device access problems without changing Ecowitt settings.
6. Close Settings and select **AcuRite USB** in the station selector. Allow
   a sampling cycle and a history interval for the first saved observation.

The outdoor sampler runs every 18 seconds; console temperature/pressure requests
are limited to once per 60 seconds. Saving a 300-second history interval does not
slow the USB sampler to five minutes. Each station's retention and location use
the shared settings. Disabling a connection retains its historical data.

## Measurements and limits

- Outdoor temperature and humidity, wind speed and 16-point direction are decoded
  from alternating R1 reports. Zero wind and north are valid readings. Missing RF
  reception clears outdoor values; individual cached fields expire after 120 seconds.
- R2 supplies indoor temperature and **absolute console pressure**. Recognized
  HP03S calibration or the known linear calibration signature is required. Unknown
  calibration is reported, and those fields remain unavailable while valid outdoor
  reports can continue. Absolute pressure is not relabelled as sea-level pressure;
  it may differ from the compensated value on the console display.
- Rain uses the 13-bit rolling tip counter at 0.01 inch per tip. Raw counter values
  and sample times are persisted as provenance, separately from daily/lifetime
  weather totals. Comparable counter samples produce interval rain, including
  near-boundary rollover at 81.92 inches. Unexpected counter decreases establish
  a conservative reset with zero interval rain rather than inventing rainfall.
- **Recorded rain today** sums the recorded intervals by the configured local day.
  It is unavailable until a comparable rain baseline exists. It does not recover
  rainfall before the initial baseline, across a lost baseline, or multiple counter
  wraps during an outage. An interval spanning midnight is assigned to its ending
  date. It is not a backfill of the console's daily rain display.
- No wind gust, live indoor humidity, UV/solar, or console archive data are
  advertised. Feels Like, Heat Index, and Wind Chill use Caelus's shared calculations.
- Battery health recognizes the documented normal/low R1 status nibbles; unfamiliar
  encodings remain UNKNOWN. USB connectivity and outdoor RF reception have separate
  health states. A connected console can still have no outdoor sensor reception.

Ecowitt retains `/home/pi/Caelus/data/caelus.db`; AcuRite uses
`/home/pi/Caelus/data/acurite.db`. The existing Ecowitt database is neither moved
nor split. Both databases retain the historical naive-UTC ISO timestamp contract.
Station-specific endpoints take `?station=ecowitt` or `?station=acurite_usb`,
including current readings, metrics, exports, and health. The selection stays in
each tab's URL; opening another station does not change that tab's data requests.
The two sources share one configured location and forecast, not measurement values.

## Validate your physical console

Compare decoded values with the console while both receive the same outdoor
reports. Check calm wind, known compass direction, temperature/RH, and a small
rain counter increase. Compare pressure only after accounting for the distinction
between raw absolute and console-compensated pressure.

To collect raw live reports for decoder validation, stop Caelus and any other USB
reader, then run:

```bash
cd /home/pi/Caelus
/home/pi/Caelus/.venv/bin/python -m caelus.acurite --capture /home/pi/Caelus/data/acurite-usb-capture.json --samples 4
```

On macOS, the equivalent example uses `/Users/yourname/Caelus`:

```bash
cd /Users/yourname/Caelus
/Users/yourname/Caelus/.venv/bin/python -m caelus.acurite --capture /Users/yourname/Caelus/data/acurite-usb-capture.json --samples 4
```

On Windows, use PowerShell and your actual absolute installation path:

```powershell
Set-Location 'C:\Users\yourname\Caelus'
& 'C:\Users\yourname\Caelus\.venv\Scripts\python.exe' -m caelus.acurite --capture 'C:\Users\yourname\Caelus\data\acurite-usb-capture.json' --samples 4
```

Add `--model 01035` (or another canonical profile from the table) when capturing
one of the additional families. The capture records your selected model and prints
its mode instructions; it does not detect the model or change the USB mode.

The command samples four times at 18-second spacing and saves timestamped R1/R2 hex
reports. Linux releases/reattaches the USB interface after each cycle; macOS and
Windows close their native HID handles. It performs no
logger, reset, or mode-setting commands. Restart Caelus after capture. If access
fails, confirm the console is detected by the OS and no competing reader owns it.
On Linux, check `lsusb` and that the udev rule targets the service account's primary
group. On macOS/Windows, keep the native HID driver assigned.

## Altitude and barometric pressure

Set **Station altitude** under **Settings > Location** to the console's height
above sea level, in feet for Imperial units or meters for Metric. A blank value
keeps the Current Readings card on absolute pressure. Zero is a valid sea-level
altitude. IP location detection does not supply or change this setting.

With altitude configured, new AcuRite polls calculate a barometric pressure
estimate using the [NWS altimeter-setting formula](https://www.weather.gov/media/epz/wxcalc/altimeterSetting.pdf).
This standard-atmosphere correction does not use outdoor temperature and is not
a meteorological mean-sea-level pressure reduction. The estimate is stored in
`pressure`; the original console value remains in `indoor_absolute_pressure`.
Both remain available to histories and exports. Historical rows are unchanged,
and the Current Readings value updates after the next successful poll. Missing
or stale console pressure does not produce an adjusted value. Ecowitt values
are unaffected. No console calibration or mode commands are sent.
