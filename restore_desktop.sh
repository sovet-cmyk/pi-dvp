#!/usr/bin/env bash
set -euo pipefail

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$EUID" -eq 0 ]]; then
  echo "Run this as the normal DVP user, without sudo." >&2
  exit 1
fi

if [[ -f /etc/lightdm/lightdm.conf.before-dvp ]]; then
  sudo cp -a /etc/lightdm/lightdm.conf.before-dvp /etc/lightdm/lightdm.conf
else
  sudo sed -Ei 's|^[[:space:]]*autologin-session=dvp|autologin-session=rpd-labwc|' \
    /etc/lightdm/lightdm.conf
fi
sudo rm -f /etc/lightdm/lightdm.conf.d/99-dvp-kiosk.conf
sudo rm -f /usr/share/xsessions/dvp.desktop
sudo systemctl disable dvp-hotspot.service >/dev/null 2>&1 || true
sudo rm -f /etc/systemd/system/dvp-hotspot.service
sudo systemctl daemon-reload

for DVP_BOOT_FILE in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -f "$DVP_BOOT_FILE.before-dvp" ]]; then
    sudo cp -a "$DVP_BOOT_FILE.before-dvp" "$DVP_BOOT_FILE"
  fi
done
if [[ -f /boot/firmware/config.txt.before-dvp ]]; then
  sudo cp -a /boot/firmware/config.txt.before-dvp /boot/firmware/config.txt
fi
for DVP_IDENTITY_FILE in /etc/hostname /etc/hosts; do
  if [[ -f "$DVP_IDENTITY_FILE.before-dvp" ]]; then
    sudo cp -a "$DVP_IDENTITY_FILE.before-dvp" "$DVP_IDENTITY_FILE"
  fi
done

sudo systemctl set-default graphical.target
sudo systemctl unmask lightdm >/dev/null 2>&1 || true
sudo systemctl enable lightdm NetworkManager >/dev/null

echo "The maintenance desktop session has been restored."
echo "DVP desktop autostart remains disabled for maintenance access."
echo "Reboot with: sudo reboot"
echo "To re-enable old desktop autostart later:"
echo "  $DVP_ROOT/.venv/bin/python $DVP_ROOT/tools/autostart.py enable"
