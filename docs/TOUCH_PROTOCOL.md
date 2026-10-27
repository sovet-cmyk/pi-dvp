# Radxa Zero 3W to Pi 5 wireless touch protocol

## Route

There is one Radxa Zero 3W inside the screen enclosure:

```text
Screen USB touch -> Radxa USB host -> 2.4 GHz Wi-Fi -> Pi 5 built-in Wi-Fi -> DVP UI
```

HDMI carries the picture separately. No touch bridge is required at the Pi. The
Pi is the `DVP-TOUCH` access point at `10.42.0.1`; the Radxa sends UDP datagrams
to the Pi gateway on port `4210`.

The DVP application starts the receiver automatically when `TOUCH_MODE` is
`udp`. Local mouse/direct-USB touch continues to work through OpenCV as before.

## Message format

Each UDP datagram contains exactly one UTF-8 JSON object and is limited to 512
bytes. Coordinates are normalized to the complete 800x480 application:

```json
{"type":"hello","session":"device-boot-id","seq":0,"key":"shared-key"}
{"type":"heartbeat","session":"device-boot-id","seq":1,"key":"shared-key"}
{"type":"touch","event":"down","x":0.04,"y":0.21,"session":"device-boot-id","seq":2,"key":"shared-key"}
{"type":"touch","event":"move","x":0.05,"y":0.21,"session":"device-boot-id","seq":3,"key":"shared-key"}
{"type":"touch","event":"up","x":0.05,"y":0.21,"session":"device-boot-id","seq":4,"key":"shared-key"}
```

The key must match `TOUCH_SHARED_KEY` in the Pi's `settings.json` and
`shared_key` in `radxa_touch/config.json`. The receiver removes it before
placing a message in the UI queue. WPA2 protects the Wi-Fi link; the application
key rejects unrelated datagrams but is a bearer secret rather than a per-packet
cryptographic MAC. Change both bundled bench credentials before deployment.

## Coordinated shutdown

The UDP socket is bidirectional. After the user taps PWR and then confirms the
shutdown dialog, the Pi sends the following datagram back to the exact IP and
source port of the currently authenticated Radxa session:

```json
{"type":"poweroff","session":"device-boot-id","key":"shared-key"}
```

The Pi repeats it five times before closing its touch receiver. The Radxa accepts
it only when it comes from the configured Pi address and port, and when both the
shared key and the current randomized session match. Wrong sources, old sessions,
extra fields, malformed JSON, and wrong keys are ignored.

The unprivileged touch process writes a request into its private systemd runtime
directory. A separate root-owned path/service pair performs the actual poweroff,
so the network-facing sender does not run as root. Failure to contact a Radxa does
not prevent the Pi from completing its own clean shutdown.

## Ordering and failure behavior

- The Radxa sender uses a fresh session identifier whenever it opens the touch
  device and repeats `hello` once per second so a DVP application started later
  can synchronize.
- Every non-hello message has a strictly increasing 32-bit sequence number.
- The Pi locks a session to the UDP source address/port that supplied its valid
  hello. Wrong keys, wrong sessions, duplicate/out-of-order messages, oversized
  datagrams and malformed JSON are ignored.
- The Radxa sends a heartbeat every 250 ms. While a finger stays down, it sends
  an update at least every 100 ms even if the coordinates do not change.
- No valid message for 0.7 seconds marks the internal link state lost and
  releases any held control. Queue overflow also releases held controls instead
  of replaying stale actions. The final operator overlay hides this maintenance
  state.
- A new session releases the previous held control before accepting input.
- Destructive dialogs still require ordinary coordinate touches. Network
  command shortcuts cannot directly confirm shutdown or deletion.
- The Radxa cannot power the Pi off; the coordinated power command is accepted
  only in the Pi-to-Radxa direction after local UI confirmation.

## Linux input mapping

The Radxa uses Linux `evdev`, rather than decoding controller-specific USB
reports. It auto-selects a direct touchscreen exposing either multitouch
`ABS_MT_POSITION_X/Y` data or single-touch `ABS_X/Y` data. Coordinates are
normalized using the axis minimum and maximum published by the kernel driver.
Rotation, axis inversion, a stable device-name filter, and optional measured
axis limits are available in `radxa_touch/config.json`.

The sender stops its heartbeat if the USB touchscreen disappears, so the
receiver releases any active control instead of treating Wi-Fi alone as proof
that touch input is healthy.
See `radxa_touch/README.md` for installation and local input tests.

## Alternate serial mode

The previous JSON-lines serial receiver remains available for diagnostics. Set
`TOUCH_MODE` to `serial`, set `TOUCH_SERIAL_PORT` to the stable device path and
keep `TOUCH_BAUD` at 115200. Set `TOUCH_MODE` to `off` for local input only.
