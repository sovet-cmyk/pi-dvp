# Review of the uploaded source

## 29 October 2026 — processing unit 3.2.8

- Replaced the incompatible `console=null` attempt with the deployed silent-boot
  arrangement: diagnostics route to `serial0`, Plymouth is disabled, routine
  kernel/systemd/udev status is suppressed, and HDMI stays black until DVP.
- Added a persistent systemd `ShowStatus=no` drop-in and masked only the visible
  `tty1` getty; `tty2` remains available for recovery.
- Recovery now removes the quiet-status drop-in and unmasks `tty1`.
- Restored the now physically validated transistor-driven 5 V passive buzzer on
  GPIO17/physical pin 11. Export start gives one beep, verified safe removal
  repeats three beeps every five seconds, failure gives a continuous tone, and
  physical USB removal or application shutdown silences it.
- Added the lgpio dependency, GPIO group setup, a non-destructive USB insertion
  sounder test, configuration validation, operator wiring instructions, and
  automated pattern/USB lifecycle tests.

## 27 October 2026 — processing unit 3.2.7

- Moved DVP from late XDG desktop autostart to the beginning of labwc system
  autostart, in the foreground, so the wallpaper and panel cannot flash first.
- Esc now allows the saved desktop autostart sequence to continue; it still does
  not restart DVP.
- Added a runtime poweroff marker so confirmed shutdown does not briefly start
  the desktop after the DVP window closes.
- Added backup and restoration of the original labwc system autostart file.

## 27 October 2026 — processing unit 3.2.6

- Restored the proven desktop-backed startup arrangement: the normal maintenance
  desktop autologs in and launches DVP once through XDG autostart.
- Esc now exits DVP and reveals the already-running desktop instead of being
  interpreted by the kiosk supervisor as a reason to relaunch the interface.
- Removed the obsolete dedicated `dvp` session during appliance setup and made
  the compatibility kiosk launcher one-shot.
- Preserved quiet boot, automatic paired hotspot, adaptive display, camera
  reconnect, touch status, USB export, battery monitoring, and all UI behavior.

## 27 October 2026 — processing unit 3.2.5

- Restored a product-facing touch-link message without restoring diagnostic
  telemetry or revealing the screen-side board/network implementation.
- A dedicated top badge now shows `TOUCH READY`, `TOUCH SEARCHING`,
  `TOUCH LOST`, or `TOUCH ERROR` without being hidden by recording or USB
  messages.
- Added explicit sample/unit-1/unit-2 pairing. Each set receives its own SSID,
  Wi-Fi password, and authenticated touch key through a local update-safe
  `pairing.json`; nonmatching saved DVP touch profiles are removed.
- Changed the boot hotspot service to resolve the configured profile at runtime
  instead of hardcoding `DVP-TOUCH`.

## 27 October 2026 — processing unit 3.2.4

- Removed the passive-buzzer driver, GPIO dependencies, test utility, settings,
  and wiring instructions; legacy buzzer keys in an existing settings file are
  accepted and ignored during an upgrade.
- Retained verified USB success/failure state in the top banner so the result is
  visible after a display sharing the connector is reconnected.
- Rechecked wireless output detection and added a full-frame 800x480-to-1920x1080
  pixel-fill test in addition to the existing mode and touch-mapping tests.

## 27 October 2026 — processing unit 3.2.3

- Kept the dedicated display session alive and automatically restart the DVP
  interface after an unexpected exit instead of exposing the login greeter.
- Added a bounded kiosk diagnostic log for startup failures.
- Prevented absent-camera retry attempts from generating false disconnect
  callbacks; DVP now waits indefinitely and reconnects when the camera appears.

## 27 October 2026 — processing unit 3.2.2

- Restored temporary operator messages in a dedicated top banner without
  restoring FPS, temperature, AI timing, DROP/DUP, board, or software details.
- Added an always-visible recording badge while controls are shown: `REC RAW`,
  `REC UI`, `REC START`, `REC STOPPED`, or `REC ERROR`.
- Added clear messages for recording start/mode, camera disconnect, detection
  toggles, controls visibility, zoom, recentering, and USB export cancellation.

## 27 October 2026 — processing unit 3.2.1

- Added identity-based auto-detection for standard INA226 devices and the
  installed R005 module reporting die ID `0x2270` at address `0x50`.
- Added compatible-mode current conversion at 1.25 mA/bit and calculate power
  from the same voltage/current pair instead of the module's inconsistent power
  register.
- Documented the required VBS-to-IN- voltage-sense connection and made install,
  test, and log commands independent of the Linux username.

## 27 October 2026 — processing unit 3.2.0

- Replaced the earlier INA219 driver and configuration with INA226 support for
  the installed R005 shunt. The driver programs calibration 2048, cross-checks
  calibrated current against raw shunt current, and retains approximate four-bar
  load-compensated display behavior.
- Earlier builds experimented with audible USB-export indications. Version 3.2.4
  removed that optional hardware and its software dependency.
- Documented the 2S2P 9 Ah processing battery and supplied 8.4 V CC/CV charger.

The supplied archive contained a Pi-oriented OpenCV application, a 320-pixel
YOLOv8n ONNX export, a separate camera_tx.py preview, model-export/training
dependencies, development recordings, and cached files. It was a useful base,
but not sufficient as-is for the updated single-Pi architecture.

## Changes

| Area | Updated behavior |
| --- | --- |
| Architecture | Direct USB camera on one Pi; HDMI carries the complete rendered display through either cable or Skywire |
| Human detection | Load the supplied ONNX model directly; vectorized person filtering; worker with one pending latest frame |
| Inference age | Discard stale detections and results from an earlier camera connection |
| Camera capture | Dedicated worker; latest preview slot; raw recording submitted directly from capture |
| Motion | Small grayscale image changes; global-change suppression; reset on camera reconnect |
| Recording | Dedicated bounded encoder queue; actual capture timestamps set playback timing; explicit duplicate/drop counts |
| Raw/UI choice | RAW defaults to full camera frame; UI includes the current displayed view |
| Disconnect | Blank stale preview and close the recording; retry the configured camera |
| USB | UDisks mounting, background export, cancellation, unique export directories, checksums, eject |
| Storage | Separate worker; completed/active/export distinctions; no deletion of unrelated or legacy folders |
| Shutdown | Authenticated request to halt the active Radxa, then stop capture/control, cancel export, close files, and power off the Pi only after a clean shutdown |
| UI | Shared drawing/hit-test geometry; touch/keyboard controls; small restore button when hidden |
| Radxa/touch | Authenticated UDP receiver plus a screen-side Radxa Linux-input sender; session, sequence, timeout and queue-overflow safety; serial fallback retained |
| Installation | Relative paths, venv, desktop autostart; remove hardcoded /home/sovet and panel-killing commands |

The shipped runtime no longer needs PyTorch, the Ultralytics Python package,
model-export scripts, a separate camera transmitter process, network video
discovery/streaming, or a receiver capture pipeline. Old logs, development
recordings, .pt weights, and caches are not in the new distributable.

The ONNX weights and splash image came from the uploaded ZIP and are retained.
The source modules were restructured to separate capture, inference, recording,
USB work and the UI; this is not a small line-only patch.

## 13 October Radxa wireless-touch integration

The DVP application binds UDP port 4210 itself; no second board or receiver
process is required at the Pi. A hotspot helper configures the Pi's built-in
Wi-Fi. At the screen, a Radxa Zero 3W reads the touchscreen through Linux
`evdev`, normalizes the advertised axis range, and transmits down/move/up events.
The sender supports single-touch and multitouch devices, orientation correction,
USB reconnection, a boot service, and a local monitor mode. The receiver rejects
wrong keys, sessions, peers, duplicates, stale input and oversized/malformed
packets, and releases held UI controls after link loss.

The confirmed PWR action now returns an authenticated, current-session command
to the Radxa before Pi shutdown. A root-owned systemd path helper powers the
Radxa off without giving the UDP touch process root privileges.

## Scope that remains separate

- Physical end-to-end validation of the Radxa USB host, touchscreen event mapping,
  boot service and Wi-Fi reconnection on the assembled screen.
- A physical fuel-gauge driver; an external fresh-percentage file can be connected.
- HDMI output mirroring/mode configuration and Skywire's internal link behavior.
- Camera optics, human-detection accuracy and measured Pi/RF performance.
- Features that may exist only in another Radxa source version not included in
  this archive. This package covers the requested functions and the functionality
  visible in the supplied code; it is not a verified line-for-line Radxa port.

## Interruption recovery

An abnormal power cut can leave an active mission and .partial.mp4 files.
Those are retained, excluded from automatic cleanup/export, and should be
inspected manually. Copy the file before attempting repair. FFmpeg can sometimes
remux the surviving fragments into a different output file, for example:

    ffmpeg -i "capture.partial.mp4" -c copy "recovered.mp4"

Recoverability depends on which data reached storage. Never rename a broken
file and assume it is complete. Clean shutdown and safely ejecting USB are still
necessary.
