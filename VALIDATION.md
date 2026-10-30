# Validation — updated 29 October 2026

This is software validation on an x86-64 Linux development environment. It is
not a processing-board performance benchmark and does not replace final tests on
the assembled DVP hardware.

Environment: Python 3.12, NumPy 2.2.6, OpenCV headless 4.12.0, ONNX Runtime
1.23.2, pyserial 3.5, and FFmpeg with libx264. The target installer uses
the distribution's GUI OpenCV/NumPy plus apt-provided SMBus/GPIO packages.

## Current automated result

The baseline **44 processing-repository tests passed** on 27 October 2026. The
29 October v3.2.8 sounder additions passed targeted fake-GPIO thread/pattern,
USB lifecycle, Python compilation, Bash syntax, whitespace, and silent-boot
transformation checks. The suite covers:

- the supplied ONNX model, person-class decoding, letterbox coordinates, NMS,
  expiry/generation behavior, and missing-model fallback;
- motion detection and global-scene-change suppression;
- zoom/pan geometry without mutating the raw camera frame;
- bounded recording queues, boundaries, timing gaps, duplication/skipping, and
  real FFmpeg output/duration;
- unique transactional USB export, checksum verification, completion marker,
  cancellation, media removal, low space, symlink refusal, corrupted copies,
  mission pinning, and exclusion of system/data disks;
- automatic selection of **all** missions when a new USB drive appears;
- persistent USB success/failure state, safe-removal state, and completion files;
- non-blocking GPIO17 start/success/failure patterns, interruption/silencing,
  and clean PWM cancellation through the deployed lgpio-compatible API;
- authenticated UDP/serial touch parsing, sessions, sequence rejection, timeout,
  release behavior, authenticated coordinated poweroff, and operator-visible
  ready/searching/lost/error link states;
- parsing both 800x480 and 1920x1080 XRandR modes;
- resizing an 800x480 logical frame to a 1920x1080 presentation frame and
  verifying that every output pixel is filled without software-added borders;
- mapping local 1920x1080 pointer coordinates back to the logical canvas;
- R005 INA226 calibration and register conversion at a simulated 7.4 V / 5 A load;
- auto-detection and conversion of the installed die-`0x2270`, address-`0x50`
  compatible monitor using captured hardware register values;
- all four configured battery-bar thresholds;
- absence of board names in the power dialog and removal of routine diagnostic
  labels from the normal overlay;
- stale-camera blanking and removal of stale detections.

The screen-side repository's three tests also passed. They confirm that touch
remains normalized and therefore independent of either HDMI mode, and that a
local per-unit pairing key overrides the public bench default. Python
compilation, JSON parsing, Bash syntax, and whitespace checks passed in both
repositories. Pairing-script smoke tests produced distinct unit-1/unit-2 files.

## Synthetic application run

The final application ran for three seconds with the synthetic camera, bundled
model, motion detector, raw recorder, FFmpeg, touch receiver, UI renderer, clean
shutdown, and PNG snapshot enabled. It closed its MP4 files cleanly and produced
an 800x480 PNG. The visually inspected snapshot contained the requested controls;
diagnostic header/footer text was absent. Performance figures from this x86 test
environment are not target-hardware claims.

Earlier real-encoder tests also verify that 30 samples arriving at 15 fps produce
59 output frames over about 1.97 seconds, including 29 intentional duplicates.
This preserves elapsed time instead of playing the recording twice as fast.

## Still required on assembled hardware

- Direct HDMI at 800x480 and Skywire HDMI at 1920x1080, including full-screen
  fill, every corner/control, hot-plug, and cold boot.
- Actual camera mode negotiation, sustained recording/AI rate, reconnect, and
  maximum-load temperature/throttling.
- Human-detection accuracy in intended lighting, range, and camera angles.
- A real USB drive: all-mission copy, hash verification, automatic unmount,
  persistent completion/failure result, physical removal, failure behavior, and
  the complete one-beep / repeating-triplet / continuous-warning sound sequence.
- R005 monitor address/readings against a trusted multimeter and series ammeter,
  shunt/terminal temperature at peak load, and a full 2S discharge to calibrate
  the four thresholds.
- Headless boot, hotspot priority, touch reconnect, external-antenna range,
  interference/packet loss, and coordinated shutdown of both units.
- Sudden power loss after safe shutdown and during recording/export. Software
  cannot make in-flight filesystem writes survive arbitrary battery removal.

Use the wiring and hardware test sequence in `README.md` before treating the
assembled device as validated. No sustained frame-rate, radio-range, runtime, or
battery-percentage guarantee is inferred from these development tests.
