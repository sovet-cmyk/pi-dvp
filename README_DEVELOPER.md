# DVP V3 developer notes

Use [README.md](README.md) for installation, wiring, operation, and validation.
This file records the implementation boundaries most likely to matter during
future development.

## Video and coordinate model

The application always renders a logical `DISPLAY_WIDTH x DISPLAY_HEIGHT` canvas
(currently 800x480). `hardware/display.py` polls `xrandr --current` and resizes
only the final presentation frame to the active HDMI mode. Raw recordings and AI
input are unaffected.

`touch_sender.py` on the screen-side unit sends normalized values. Remote touch
maps directly into the logical canvas. OpenCV local pointer coordinates are first
divided by the physical/logical scale in `ui/touch.py`. Keep this separation;
resolution-specific coordinates must not be added to the UDP protocol.

## Recording

- `raw` mode submits the original camera frame from the capture callback.
- `ui` mode records the logical 800x480 rendered canvas, not the upscaled HDMI
  presentation frame.
- Recorder input is bounded. Drops and timeline duplicates are logged but no
  longer appear in the operator UI.
- Camera disconnect, stale frames, recording-mode changes, USB exports, and
  shutdown create recorder boundaries.

## Automatic USB export

`USBMonitor` runs outside the display loop. New USB storage queues `all`, pins
candidate missions, closes the current recording boundary, copies into a unique
partial directory, hashes and verifies every file, writes a manifest/completion
marker, atomically renames the export, and finally unmounts the disk.
The UI retains the last verified success/failure result so it remains visible
when a display sharing the external connector is reconnected.

Do not move automatic copying into a standalone boot service without recreating
the recorder boundary and mission pinning protocol; copying an active MP4 can
produce a corrupt or incomplete export.

## Touch-link status

`TouchBridge` publishes only its internal link state to `state.touch_status`.
The dedicated operator badge translates that state into product-facing text
without showing the screen-side board, network address, UDP port, or protocol.
It remains visible alongside the separate temporary-message/USB-result banner.

`configure_pair.sh` writes the local ignored `pairing.json`. The hotspot helper
uses its SSID/password, while `app/config.py` overlays only its touch key onto
`settings.json`. The installed hotspot service calls the helper instead of
hardcoding a NetworkManager profile name. Keep the same unit number and secrets
on the matching screen-control device.

## Battery-monitor variants

`hardware/ina226.py` communicates directly rather than depending on an external
sensor library. It probes the configured address and `0x40` through `0x50`, then
requires manufacturer ID `0x5449` plus a supported die ID. A standard INA226
(`0x2260` or `0x2261`) is programmed with configuration `0x4527`, selecting
16-sample averaging, 1.1 ms conversions and continuous mode. With the configured
0.005-ohm shunt and 0.0005 A current LSB:

```text
calibration = 0.00512 / (0.0005 A * 0.005 ohm) = 2048
current A  = signed_current_register * 0.0005 A
shunt A    = signed_shunt_register * 2.5 uV / 0.005 ohm
bus V      = bus_register * 1.25 mV
```

The installed R005 module identifies as die `0x2270` at non-standard address
`0x50`. Compatible mode reads current from register `0x01` at 1.25 mA/bit,
reads bus voltage from `0x02` at 1.25 mV/bit, does not write the INA226-only
calibration register, and calculates power from the same voltage/current pair.
Its separate VBS pin must be connected to load-side IN-.

For a standard INA226, the driver rejects a sample when calibrated current and
independently derived shunt current disagree materially. Keep either monitor
before every power branch so its reading represents the complete processing-unit
load. Validate compatible-mode current against a trusted series meter because
the external R005 module is not a standard INA260 implementation.

The default bar calculation adds positive-current load compensation, applies an
exponential filter, then compares the result to four configurable thresholds.
It is intentionally not described as a precise state-of-charge gauge.

## USB result feedback

No GPIO sounder is present in this build. `USBMonitor` publishes active progress,
safe-removal state, and a persistent last result. `DVPUI.status_banner()` gives
temporary operator messages priority, then shows the persistent USB result.
Successful exports also carry `EXPORT_COMPLETE.txt` and
`export_manifest.json` on the removable drive.

## Product-facing text

Normal runtime surfaces use DVP naming. Do not add board, distribution, framework,
or computer names to the operator UI, splash, shutdown dialog, hostname, service
descriptions, or normal boot output. Developer documentation and mandatory
third-party attribution remain accurate and intact.

## Test entry points

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python main.py --demo --headless --seconds 5 --snapshot /tmp/dvp.png
bash -n install.sh setup_appliance.sh configure_pair.sh restore_desktop.sh tools/touch_hotspot.sh
```

Physical validation still requires both HDMI routes, the actual touchscreen and
radio link, a real camera recording under AI load, a USB drive, the persistent
export result, the actual R005 monitor, and a full 2S discharge/recharge cycle.
