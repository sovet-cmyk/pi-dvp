#!/usr/bin/env bash
set -euo pipefail

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DVP_PAIRING_FILE="$DVP_ROOT/pairing.json"
DVP_TOUCH_PROFILE="DVP-TOUCH"
DVP_TOUCH_SSID="DVP-TOUCH"
DVP_TOUCH_PASSWORD="t7Kp4Nw9Qx2R8m6V"
DVP_TOUCH_INTERFACE="wlan0"

run_root() {
  if [[ "$EUID" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if [[ -f "$DVP_PAIRING_FILE" ]]; then
  DVP_PAIRING_TEXT="$(python3 - "$DVP_PAIRING_FILE" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
for key in ("ssid", "wifi_password", "touch_shared_key"):
    value = data.get(key)
    if not isinstance(value, str) or not value or "\n" in value:
        raise SystemExit(f"Invalid {key} in {path}")
print(data["ssid"])
print(data["wifi_password"])
PY
)"
  mapfile -t DVP_PAIRING_VALUES <<< "$DVP_PAIRING_TEXT"
  if [[ "${#DVP_PAIRING_VALUES[@]}" -ne 2 ]]; then
    echo "Invalid pairing configuration: $DVP_PAIRING_FILE" >&2
    exit 1
  fi
  DVP_TOUCH_PROFILE="${DVP_PAIRING_VALUES[0]}"
  DVP_TOUCH_SSID="${DVP_PAIRING_VALUES[0]}"
  DVP_TOUCH_PASSWORD="${DVP_PAIRING_VALUES[1]}"
fi

usage() {
  echo "Usage: bash tools/touch_hotspot.sh {setup|start|stop|status}" >&2
  exit 2
}

command -v nmcli >/dev/null || {
  echo "NetworkManager/nmcli is required. No network changes were made." >&2
  exit 1
}

action="${1:-}"
case "$action" in
  setup)
    echo "This activates the DVP Wi-Fi hotspot and can disconnect an SSH session using wlan0."
    run_root nmcli radio wifi on
    while IFS= read -r old_profile; do
      if [[ "$old_profile" =~ ^DVP-TOUCH([12])?$ && "$old_profile" != "$DVP_TOUCH_PROFILE" ]]; then
        run_root nmcli connection delete "$old_profile" >/dev/null
      fi
    done < <(nmcli -g NAME connection show)
    if nmcli -g NAME connection show | awk -v name="$DVP_TOUCH_PROFILE" '$0==name {found=1} END {exit !found}'; then
      profile_type="$(nmcli -g connection.type connection show "$DVP_TOUCH_PROFILE")"
      if [[ "$profile_type" != "802-11-wireless" && "$profile_type" != "wifi" ]]; then
        echo "A non-Wi-Fi profile named $DVP_TOUCH_PROFILE already exists; refusing to modify it." >&2
        exit 1
      fi
    else
      run_root nmcli connection add type wifi ifname "$DVP_TOUCH_INTERFACE" \
        con-name "$DVP_TOUCH_PROFILE" ssid "$DVP_TOUCH_SSID"
    fi
    run_root nmcli connection modify "$DVP_TOUCH_PROFILE" \
      connection.autoconnect yes connection.autoconnect-priority 999 \
      connection.autoconnect-retries 0 \
      802-11-wireless.mode ap 802-11-wireless.band bg \
      802-11-wireless.channel 6 \
      wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn \
      wifi-sec.psk "$DVP_TOUCH_PASSWORD" \
      ipv4.method shared ipv4.addresses 10.42.0.1/24 \
      ipv6.method disabled
    run_root nmcli connection up "$DVP_TOUCH_PROFILE"
    ;;
  start)
    run_root nmcli radio wifi on
    run_root nmcli connection up "$DVP_TOUCH_PROFILE"
    ;;
  stop)
    run_root nmcli connection down "$DVP_TOUCH_PROFILE"
    ;;
  status)
    echo "Configured touch network: $DVP_TOUCH_SSID"
    nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
    nmcli -f NAME,TYPE,DEVICE connection show --active
    ;;
  *) usage ;;
esac

if [[ "$action" == "setup" || "$action" == "start" || "$action" == "status" ]]; then
  ip -4 address show dev "$DVP_TOUCH_INTERFACE" || true
fi
