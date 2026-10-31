# DVP V3 Processing Unit

Version **3.2.9** — 31 October 2026

This repository is the complete processing-unit package for DVP V3. It provides
the live camera interface, raw/UI recording, motion detection, human detection,
wireless touch reception, automatic USB export, battery bars, coordinated
shutdown, audible export status, and desktop-backed appliance autostart.

The supported hardware image is Raspberry Pi OS 64-bit with Desktop on a
Raspberry Pi 5. Those platform names are retained here for installation and
maintenance accuracy. Normal operator-facing boot, UI, hostname, services, and
shutdown surfaces use DVP naming only.

## Final operating behavior

- Direct screen: HDMI mode is normally `800x480`.
- Skywire link: HDMI mode is normally `1920x1080`.
- DVP detects the active X11 mode with `xrandr` and scales its fixed logical
  800x480 control canvas to fill either output.
- Local/direct touch is converted back into logical coordinates. Wireless touch
  is already normalized from 0 to 1, so the same packet lands on the same DVP
  control at both resolutions.
- The screen-side interface sends touch over its paired `DVP-TOUCH`,
  `DVP-TOUCH1`, or `DVP-TOUCH2` Wi-Fi link.
- The normal overlay contains controls, detection boxes, a four-bar battery
  symbol, a clear `REC RAW` / `REC UI` state, and operator messages at the top.
  A separate badge shows `TOUCH READY`, `TOUCH SEARCHING`, `TOUCH LOST`, or
  `TOUCH ERROR`, so the link remains visible beside recording and USB messages.
  Diagnostic telemetry is retained in logs, not drawn on screen.
- Confirming `PWR` displays `SHUT DOWN DVP?`, requests shutdown of the touch
  interface, closes recordings/exports, and then powers down the processing unit.
- DVP starts at the beginning of the graphical session, before the wallpaper,
  panel, and other desktop components. This prevents a desktop flash at boot.
  Pressing Esc exits DVP once and lets the maintenance desktop finish starting.
- Kernel and system-service output is routed to the serial maintenance console,
  Plymouth is disabled, and diagnostic records remain in the journal. The HDMI
  display stays black until DVP opens, while `Ctrl+Alt+F2` remains available for
  recovery. Physical header pins 8 and 10 are reserved for that serial console.
- The transistor-driven sounder gives one beep when export starts and repeats
  three beeps every five seconds after verified safe removal. A failed export
  gives a warning tone for 10 seconds and then stops automatically. The success
  signal stops when the drive is physically removed.
- USB export is automatic. There is no on-screen USB button because the display
  is disconnected before the shared connector is used for the pendrive.
- The `S` storage screen lists completed recording sessions with date, time and
  size. Select individual rows or `ALL`, then choose `DELETE` and confirm.

## Fresh installation from GitHub

Temporarily connect the processing unit to internet Wi-Fi. Open Terminal and run:

```bash
sudo apt-get update
sudo apt-get install -y git
cd ~
git clone https://github.com/sovet-cmyk/DVP-V3-Pi.git dvp
cd ~/dvp
chmod +x install.sh setup_appliance.sh configure_pair.sh restore_desktop.sh start_dvp.sh start_kiosk.sh
./setup_appliance.sh 1
```

Use `1` for production set 1, `2` for production set 2, or `3` for the sample.
The last step creates and activates that set's hotspot, so a Wi-Fi SSH session
may disconnect normally. Then reboot locally:

```bash
sudo reboot
```

The setup installs dependencies, enables I2C, enables desktop autologin, starts
DVP once at the earliest labwc startup stage, starts the hotspot before the UI,
uses the neutral hostname `dvp-processing`, suppresses routine boot text, and
preserves recovery copies of every boot/display file it changes.

DVP remains open when the camera is absent. It shows `CAMERA DISCONNECTED` and
retries the camera automatically. Pressing Esc is a deliberate clean exit and
allows the maintenance desktop to start; DVP is not relaunched. A power-button
shutdown marker prevents the desktop from appearing during shutdown. Application
output is in:

```bash
tail -n 80 ~/dvp/data/logs/dvp.log
```

For an existing clone:

```bash
cd ~/dvp
git pull --ff-only
./install.sh
./setup_appliance.sh 1
sudo reboot
```

Use the correct set number in place of `1`.

## Pairing the three physical sets

Pairing is based on the explicit unit number, not the Linux username. Run the
same number on the processing unit and its matching screen-control unit:

| Physical set | Processing login | Setup argument | Hotspot |
|---|---|---:|---|
| Production 1 | `sovet1` | `1` | `DVP-TOUCH1` |
| Production 2 | `sovet2` | `2` | `DVP-TOUCH2` |
| Sample | `sovet3` | `3` or `sample` | `DVP-TOUCH` |

The bundled public bench Wi-Fi passwords are:

| Hotspot | Bench password |
|---|---|
| `DVP-TOUCH1` | `DVP1-7Kp4Nw9Qx2R8m6V` |
| `DVP-TOUCH2` | `DVP2-6Rm8Qx3Nw7Kp5T2` |
| `DVP-TOUCH` | `t7Kp4Nw9Qx2R8m6V` |

Each number also selects a different authenticated touch key. During setup,
other saved `DVP-TOUCH`, `DVP-TOUCH1`, and `DVP-TOUCH2` profiles are removed
from that device. A unit therefore does not roam onto another DVP set, and even
a manually joined controller cannot operate a differently keyed unit.

For private production credentials, run the same form on both matching devices:

```bash
./setup_appliance.sh 1 'NEW_WIFI_PASSWORD' 'NEW_TOUCH_KEY_AT_LEAST_16_CHARS'
```

The local credentials are stored in ignored `pairing.json`, so later `git pull`
updates do not overwrite the pairing. Never mix unit numbers or credentials
between the two sides of a set.

## R005 battery monitor

The processing-unit battery is a protected **2S2P 7.4 V, 9 Ah** lithium-ion pack.
Charge it only while DVP is switched off, using the supplied **8.4 V, 2 A CC/CV
lithium-ion charger**. A panel-mount USB-C connector is only the physical charge
connector; do not substitute a normal phone/USB charger.

The code supports a standard INA226 whose shunt is exactly `0.005 ohm` and the
installed R005 module that identifies as compatible die `0x2270` at address
`0x50`. It detects the register layout automatically. The R005 resistor is
non-polarized, so its orientation does not matter. If the module was supplied
with R005 already installed, do not add another shunt.

- If converting an R100 module, remove R100 and install R005 across the same two
  shunt nodes.
- Do not put R005 in series with R100; that gives `0.105 ohm`, excessive voltage
  drop, and incorrect/over-range readings.
- If R005 is soldered in parallel with an intact R100, the effective resistance
  is about `0.00476 ohm`; it is close but the current log is about 5% off.

High-current path:

```text
2S BMS P+ -> fuse -> monitor IN+ -> monitor IN- -> master switch -> regulator inputs +
2S BMS P- ----------------------------------------------------------> all regulator inputs -
```

Do not put the monitor on only one 5 V branch. It must be before the branch point
and before the UBEC to measure the complete screen, touch interface, camera, and
processing-unit load.

Monitor logic wiring to the 40-pin header:

| Monitor | Header connection |
|---|---|
| VCC | 3.3 V, physical pin 1 |
| GND | Ground, physical pin 6 |
| SDA | GPIO2/SDA, physical pin 3 |
| SCL | GPIO3/SCL, physical pin 5 |
| VBS | Short sense wire to monitor `IN-` |
| ALE/ALERT | Leave unconnected |

Power the module logic from **3.3 V, not 5 V**, because typical module I2C
pull-ups connect to VCC. Keep the battery wiring short and fused.

`VBS` must be connected to the load-side `IN-` node or bus voltage and power
remain zero. Never connect VBS to the 3.3 V VCC pad. `ALE/ALERT` is unused.

For a standard INA226, R005 and the configured `0.0005 A/bit` current scale give
calibration register `2048` and a measurement span of about `+/-16.384 A`. The
installed `0x2270`-compatible module instead supplies a factory-scaled current
register at `0.00125 A/bit`; DVP calculates power from the same voltage/current
sample rather than trusting that module's inconsistent power register. Neither
electrical span certifies the module terminals, traces, solder joints, or shunt
for that current. Check voltage drop and temperature at maximum real load.

The icon is intentionally approximate rather than a percentage:

| Bars | Default filtered/load-compensated 2S voltage |
|---:|---:|
| 4 | 7.80 V or above |
| 3 | 7.40–7.79 V |
| 2 | 7.00–7.39 V |
| 1 | 6.50–6.99 V |
| 0 | below 6.50 V |

Adjust `BATTERY_BAR_1_V` through `BATTERY_BAR_4_V` in `settings.json` after a
full real-load discharge test. This is not a cell-balancing BMS and cannot detect
individual-cell imbalance.

After reboot, a standard unit normally appears at `40`; the confirmed installed
module appears at `50`. The driver checks `0x40` through `0x50` and accepts only
the supported manufacturer/die identifiers:

```bash
i2cdetect -y 1
.venv/bin/python tools/test_ina226.py
tail -n 50 ~/dvp/data/logs/dvp.log
```

Compare the reported pack voltage and current with trusted meters before relying
on the battery bars. A negative current means the high-current `IN+` and `IN-`
path is reversed.

## USB audible indication

The installed 5 V passive magnetic buzzer is switched through the tested NPN
transistor circuit. Never connect the buzzer directly to GPIO17.

| Connection | Destination |
|---|---|
| Physical pin 11 / GPIO17 | 1 kΩ resistor, then transistor base |
| Transistor base | 10 kΩ pull-down resistor to common ground |
| Transistor emitter | Common ground; physical pin 9 is a ground option |
| Transistor collector | Buzzer negative terminal |
| Buzzer positive terminal | Regulated switched 5 V rail |
| 1N4007 striped end (cathode) | Buzzer positive / 5 V |
| 1N4007 non-striped end (anode) | Buzzer negative / transistor collector |

The two outer transistor leads are not universal between manufacturers; use the
confirmed emitter/collector orientation from the working hardware test. GPIO17
is a logic signal only. The transistor carries the buzzer current and the diode
clamps the magnetic flyback pulse.

Audible behavior:

- export started: one short beep;
- verified copy, sync and unmount completed: three short beeps, repeated every
  five seconds until the pendrive is physically removed;
- export, verification or unmount failed: warning tone for 10 seconds, then
  automatic silence.

The display simultaneously shows export progress and retains one of these
results at the top until the next export or reboot:

- `USB EXPORT COMPLETE - SAFE TO REMOVE` while the verified drive is unmounted;
- `LAST USB EXPORT COMPLETE` after that drive is physically removed;
- `LAST USB EXPORT FAILED` after any copy, verification, or removal failure.

If the display must be disconnected to use the shared four-pin connector, the
last result is still visible after the USB drive is removed and the display is
reconnected. The exported drive also contains `EXPORT_COMPLETE.txt` and a
SHA-256 manifest only after the copy has completed successfully.

After installation and a logout/reboot, test the complete insertion path with
the pendrive initially removed:

```bash
cd ~/dvp
sudo .venv/bin/python tools/test_usb_buzzer.py
```

Insert the pendrive only when `USB WAIT` appears. The tool reports the detected
device, gives one beep and exits. It does not copy or alter any files.

## Automatic USB export

`AUTO_USB_EXPORT` and `AUTO_USB_EJECT` are enabled by default. Insert a USB drive
with exFAT, FAT, NTFS, ext, or F2FS. DVP then:

1. recognizes only removable USB storage and excludes its own boot/data disks;
2. closes the current recording boundary without stopping live capture;
3. copies **all** completed missions to a unique `DVP_Export_*` directory;
4. verifies every file with SHA-256 and writes `export_manifest.json` plus
   `EXPORT_COMPLETE.txt`;
5. syncs and unmounts the filesystem, then prevents it from remounting;
6. starts the repeating three-beep safe-removal signal;
7. retains the verified success/failure result for display after reconnection.

The originals remain internally. Failed copies stay clearly marked as partial
and are never reported as complete. When the display is connected, remove the
drive only after `USB EXPORT COMPLETE - SAFE TO REMOVE` appears.

The interchangeable four-pin enclosure connector must carry a real USB 2.0
connection, not four power conductors:

| Pin/function | Source/use |
|---|---|
| +5 V | Main switched regulated 5 V rail |
| D- | D- from a processing-unit USB 2.0 port |
| D+ | D+ from the same USB port |
| GND | Main common ground and USB ground |

Use a short twisted pair for D+/D-. The screen/TX power harness uses only +5 V
and GND and must leave D+/D- insulated and unconnected; the USB-A export adapter
uses all four pins. If the existing connector currently uses two positive and
two ground pins, it cannot also carry USB data until it is rewired. Never connect
another powered 5 V source to this port, and verify the connector's current
rating remains sufficient for the screen/TX load.

## What the removed overlay labels meant

- `C`: camera capture frames per second.
- `V`: unique preview frames per second.
- `39C` (or similar): processor temperature.
- `DROP`: frames rejected because the bounded recording queue was full.
- `DUP`: frames duplicated to preserve recording time through camera timing gaps.
- `AI`: person-detection inference latency in milliseconds.

They are no longer shown to the operator. Maintenance metrics remain in
`data/logs/dvp.log`.

## Controls

| Control | Function |
|---|---|
| `+` / `-` | Digital zoom in/out |
| `U D L R C` | Pan or recenter the zoomed view |
| `M` | Motion toggle; green means enabled |
| `H` | Human detection toggle; green means enabled/ready |
| `RAW` / `UIR` | Raw-camera or UI-overlay recording; the top badge confirms `REC RAW` or `REC UI` |
| `S` | Recording list; select individual sessions or all sessions for deletion |
| `PWR` | Confirmed coordinated DVP shutdown |

### Deleting selected recordings

Tap `S` to open the completed-recording list. Four sessions are shown per page,
newest first. Each row shows the recording number, completion date/time and
approximate size. Tap a row to select or deselect it; selected rows show `[X]`.
Use `<` and `>` for other pages. `ALL` selects every completed recording that
is currently safe to delete. Tap `DELETE`, review the selected count, and tap
`CONFIRM`. `BACK` leaves the screen without deleting anything.

An active recording and any recording protected by an export are never
selectable. Deletion is permanent. Export and verify important recordings before
selecting them for deletion.

## Hotspot, recovery, and validation

```bash
cd ~/dvp
bash tools/touch_hotspot.sh status
systemctl status dvp-hotspot.service --no-pager
```

The bundled Wi-Fi passwords and touch keys are public bench credentials. Use
the custom `setup_appliance.sh` form above on both sides before production.

Press Esc to leave DVP and start the maintenance desktop. To disable DVP startup
and restore all saved pre-appliance boot/network settings:

```bash
cd ~/dvp
./restore_desktop.sh
sudo reboot
```

The appliance removes routine boot text, vendor splash, board-named shutdown
text, board-named hostnames, and board-named service descriptions. The desktop
does not start until the full-screen DVP interface exits with Esc. This is
presentation control, not a security boundary: shell/root
access, repository access, the maintenance desktop, or physical inspection can
still identify the platform. Third-party license and attribution files remain
intact.

Run the software checks after installation:

```bash
cd ~/dvp
.venv/bin/python -m unittest discover -s tests -v
bash -n install.sh setup_appliance.sh configure_pair.sh restore_desktop.sh tools/touch_hotspot.sh
```

Finally test real hardware at both resolutions, the persistent USB result,
one complete USB export, battery-monitor readings against trusted meters, maximum
recording/detection load, a battery discharge, safe shutdown, and cold boot
before sealing the enclosures.
