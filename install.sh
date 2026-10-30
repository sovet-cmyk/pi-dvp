#!/usr/bin/env bash
set -euo pipefail
DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DVP_AUTOSTART=0
case "${1:-}" in
  "") ;;
  --autostart) DVP_AUTOSTART=1 ;;
  *) echo "Usage: ./install.sh [--autostart]" >&2; exit 2 ;;
esac
if [[ "$EUID" -eq 0 ]]; then
  echo "Run as the normal DVP user, without sudo. The script uses sudo when required." >&2
  exit 1
fi
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This installer requires the DVP 64-bit processing platform." >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-opencv python3-numpy \
  ffmpeg v4l-utils udisks2 exfatprogs network-manager x11-xserver-utils \
  i2c-tools python3-smbus python3-rpi-lgpio
python3 -m venv --system-site-packages "$DVP_ROOT/.venv"
"$DVP_ROOT/.venv/bin/python" -m pip install --upgrade pip
DVP_CONSTRAINT="$(mktemp)"
trap 'rm -f -- "$DVP_CONSTRAINT"' EXIT
# Prevent pip dependencies from replacing apt's NumPy underneath apt's OpenCV.
"$DVP_ROOT/.venv/bin/python" -c 'import numpy; print("numpy=="+numpy.__version__)' > "$DVP_CONSTRAINT"
"$DVP_ROOT/.venv/bin/python" -m pip install --only-binary=:all: \
  --constraint "$DVP_CONSTRAINT" -r "$DVP_ROOT/requirements.txt"
for DVP_GROUP in video dialout i2c gpio; do
  if getent group "$DVP_GROUP" >/dev/null; then
    sudo usermod -aG "$DVP_GROUP" "$(id -un)"
  fi
done
chmod +x "$DVP_ROOT/start_dvp.sh"
chmod +x "$DVP_ROOT/start_kiosk.sh" "$DVP_ROOT/setup_appliance.sh" \
  "$DVP_ROOT/restore_desktop.sh" "$DVP_ROOT/configure_pair.sh"
chmod +x "$DVP_ROOT/tools/touch_hotspot.sh"
chmod +x "$DVP_ROOT/tools/test_ina226.py"
chmod +x "$DVP_ROOT/tools/test_usb_buzzer.py"
"$DVP_ROOT/.venv/bin/python" "$DVP_ROOT/tools/check_system.py"
if [[ "$DVP_AUTOSTART" -eq 1 ]]; then
  "$DVP_ROOT/.venv/bin/python" "$DVP_ROOT/tools/autostart.py" enable
fi
echo "Installed. Log out and back in for device permissions."
echo "Launch DVP with: $DVP_ROOT/start_dvp.sh"
echo "If autostart is enabled, DVP starts at desktop login."
