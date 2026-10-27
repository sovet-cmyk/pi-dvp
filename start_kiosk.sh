#!/usr/bin/env bash
set -u

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DVP_KIOSK_LOG="$DVP_ROOT/data/logs/kiosk.log"
DVP_STOP=0
DVP_CHILD=""

mkdir -p -- "$DVP_ROOT/data/logs"

# An X session returns to the login greeter as soon as its Exec process exits.
# Keep this wrapper alive and restart the operator interface after an unexpected
# exit so a missing/reconnecting camera can never expose the desktop login.
stop_kiosk() {
  DVP_STOP=1
  if [[ -n "$DVP_CHILD" ]] && kill -0 "$DVP_CHILD" 2>/dev/null; then
    kill "$DVP_CHILD" 2>/dev/null || true
  fi
}
trap stop_kiosk INT TERM HUP

# Keep the dedicated display awake. These commands are optional because the
# X server is also configured with screen blanking disabled.
xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true
xsetroot -solid black >/dev/null 2>&1 || true

while [[ "$DVP_STOP" -eq 0 ]]; do
  if [[ -f "$DVP_KIOSK_LOG" ]] && \
     [[ "$(stat -c '%s' "$DVP_KIOSK_LOG" 2>/dev/null || printf '0')" -gt 1000000 ]]; then
    mv -f -- "$DVP_KIOSK_LOG" "$DVP_KIOSK_LOG.1"
  fi

  "$DVP_ROOT/start_dvp.sh" >>"$DVP_KIOSK_LOG" 2>&1 &
  DVP_CHILD=$!
  wait "$DVP_CHILD"
  DVP_STATUS=$?
  DVP_CHILD=""

  if [[ "$DVP_STOP" -ne 0 ]]; then
    break
  fi
  printf '%s DVP interface exited with status %s; restarting.\n' \
    "$(date --iso-8601=seconds)" "$DVP_STATUS" >>"$DVP_KIOSK_LOG"
  sleep 2
done

exit 0
