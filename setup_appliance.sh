#!/usr/bin/env bash
set -euo pipefail

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DVP_USER="$(id -un)"
DVP_LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
DVP_LIGHTDM_BACKUP="/etc/lightdm/lightdm.conf.before-dvp"
DVP_KIOSK_CONF="/etc/lightdm/lightdm.conf.d/99-dvp-kiosk.conf"
DVP_XSESSION="/usr/share/xsessions/dvp.desktop"
DVP_HOTSPOT_SERVICE="/etc/systemd/system/dvp-hotspot.service"

if [[ "$EUID" -eq 0 ]]; then
  echo "Run this as the normal DVP user, without sudo." >&2
  exit 1
fi
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This package requires the DVP 64-bit processing platform." >&2
  exit 1
fi
if [[ ! "$DVP_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
  echo "Unsupported Linux username: $DVP_USER" >&2
  exit 1
fi

if [[ "$#" -gt 0 ]]; then
  bash "$DVP_ROOT/configure_pair.sh" "$@"
fi

if [[ ! -x "$DVP_ROOT/.venv/bin/python" ]]; then
  echo "DVP dependencies are not installed; running install.sh first."
  echo "The processing unit must have internet access during this stage."
  "$DVP_ROOT/install.sh"
fi

command -v nmcli >/dev/null || {
  echo "NetworkManager is missing. Run install.sh with internet access." >&2
  exit 1
}
command -v lightdm >/dev/null || {
  echo "The supported DVP display manager is missing." >&2
  exit 1
}
if [[ ! -x /usr/lib/xorg/Xorg ]]; then
  echo "The supported DVP display server is missing." >&2
  exit 1
fi
if [[ ! -f "$DVP_LIGHTDM_CONF" ]]; then
  echo "LightDM configuration was not found: $DVP_LIGHTDM_CONF" >&2
  exit 1
fi

chmod +x "$DVP_ROOT/start_dvp.sh" "$DVP_ROOT/start_kiosk.sh" \
  "$DVP_ROOT/configure_pair.sh" \
  "$DVP_ROOT/tools/touch_hotspot.sh" "$DVP_ROOT/restore_desktop.sh"

# Preserve the original session and boot configuration once. Re-running the
# installer does not replace the known-good recovery copies.
if [[ ! -e "$DVP_LIGHTDM_BACKUP" ]]; then
  sudo cp -a "$DVP_LIGHTDM_CONF" "$DVP_LIGHTDM_BACKUP"
fi
for DVP_BOOT_FILE in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -f "$DVP_BOOT_FILE" && ! -e "$DVP_BOOT_FILE.before-dvp" ]]; then
    sudo cp -a "$DVP_BOOT_FILE" "$DVP_BOOT_FILE.before-dvp"
  fi
done
if [[ -f /boot/firmware/config.txt && ! -e /boot/firmware/config.txt.before-dvp ]]; then
  sudo cp -a /boot/firmware/config.txt /boot/firmware/config.txt.before-dvp
fi
for DVP_IDENTITY_FILE in /etc/hostname /etc/hosts; do
  if [[ -f "$DVP_IDENTITY_FILE" && ! -e "$DVP_IDENTITY_FILE.before-dvp" ]]; then
    sudo cp -a "$DVP_IDENTITY_FILE" "$DVP_IDENTITY_FILE.before-dvp"
  fi
done

DVP_TEMP_SESSION="$(mktemp)"
DVP_TEMP_LIGHTDM="$(mktemp)"
DVP_TEMP_HOTSPOT="$(mktemp)"
trap 'rm -f -- "$DVP_TEMP_SESSION" "$DVP_TEMP_LIGHTDM" "$DVP_TEMP_HOTSPOT"' EXIT
sed "s|@DVP_ROOT@|$DVP_ROOT|g" \
  "$DVP_ROOT/appliance/dvp.desktop.in" > "$DVP_TEMP_SESSION"
sed "s|@DVP_ROOT@|$DVP_ROOT|g" \
  "$DVP_ROOT/appliance/dvp-hotspot.service" > "$DVP_TEMP_HOTSPOT"
{
  printf '%s\n' '[Seat:*]'
  printf 'autologin-user=%s\n' "$DVP_USER"
  printf '%s\n' 'autologin-user-timeout=0'
  printf '%s\n' 'user-session=dvp'
  printf '%s\n' 'autologin-session=dvp'
  printf '%s\n' 'xserver-command=X -s 0 -dpms -nocursor'
} > "$DVP_TEMP_LIGHTDM"

sudo install -d -m 0755 /usr/share/xsessions /etc/lightdm/lightdm.conf.d
sudo install -m 0644 "$DVP_TEMP_SESSION" "$DVP_XSESSION"
sudo install -m 0644 "$DVP_TEMP_LIGHTDM" "$DVP_KIOSK_CONF"
sudo install -m 0644 "$DVP_TEMP_HOTSPOT" \
  "$DVP_HOTSPOT_SERVICE"

# The base image may set autologin-session in lightdm.conf itself. That value
# overrides the drop-in, so update any active assignment while retaining the
# complete original file above for recovery.
if grep -Eq '^[[:space:]]*autologin-session=' "$DVP_LIGHTDM_CONF"; then
  sudo sed -Ei 's|^[[:space:]]*autologin-session=.*|autologin-session=dvp|' \
    "$DVP_LIGHTDM_CONF"
fi
if grep -Eq '^[[:space:]]*autologin-user=' "$DVP_LIGHTDM_CONF"; then
  sudo sed -Ei "s|^[[:space:]]*autologin-user=.*|autologin-user=$DVP_USER|" \
    "$DVP_LIGHTDM_CONF"
fi
if getent group autologin >/dev/null; then
  sudo usermod -aG autologin "$DVP_USER"
fi

# A desktop autostart entry would start a second copy if the normal desktop is
# restored later. The dedicated DVP session launches start_kiosk.sh directly.
"$DVP_ROOT/.venv/bin/python" "$DVP_ROOT/tools/autostart.py" disable

# Quiet the kernel/systemd console without removing diagnostic logs from the
# journal. Recovery copies above retain the original serial-console settings.
for DVP_BOOT_FILE in /boot/firmware/cmdline.txt /boot/cmdline.txt; do
  if [[ -f "$DVP_BOOT_FILE" ]]; then
    sudo sed -Ei '1 {
      s#(^|[[:space:]])console=[^[:space:]]+# #g
      s#(^|[[:space:]])earlycon(=[^[:space:]]+)?([[:space:]]|$)# #g
      s#(^|[[:space:]])earlyprintk=[^[:space:]]+# #g
      s#(^|[[:space:]])splash([[:space:]]|$)# #g
      s#(^|[[:space:]])quiet([[:space:]]|$)# #g
      s#(^|[[:space:]])logo\.nologo([[:space:]]|$)# #g
      s#(^|[[:space:]])loglevel=[^[:space:]]+# #g
      s#(^|[[:space:]])systemd\.show_status=[^[:space:]]+# #g
      s#(^|[[:space:]])rd\.systemd\.show_status=[^[:space:]]+# #g
      s#(^|[[:space:]])rd\.udev\.log_level=[^[:space:]]+# #g
      s#(^|[[:space:]])vt\.global_cursor_default=[^[:space:]]+# #g
    }' "$DVP_BOOT_FILE"
    for DVP_TOKEN in quiet logo.nologo loglevel=0 systemd.show_status=false \
      rd.systemd.show_status=false rd.udev.log_level=0 vt.global_cursor_default=0; do
      if ! grep -Eq "(^|[[:space:]])${DVP_TOKEN}([[:space:]]|$)" "$DVP_BOOT_FILE"; then
        sudo sed -i "1 s|[[:space:]]*$| $DVP_TOKEN|" "$DVP_BOOT_FILE"
      fi
    done
    break
  fi
done
if [[ -f /boot/firmware/config.txt ]] && \
   ! grep -Eq '^[[:space:]]*disable_splash=1([[:space:]]*#.*)?$' /boot/firmware/config.txt; then
  printf '\n# DVP appliance: suppress firmware splash\ndisable_splash=1\n' | \
    sudo tee -a /boot/firmware/config.txt >/dev/null
fi
if [[ -f /boot/firmware/config.txt ]] && \
   ! grep -Eq '^[[:space:]]*dtparam=i2c_arm=on([[:space:]]*#.*)?$' /boot/firmware/config.txt; then
  printf '\n# DVP battery monitor\ndtparam=i2c_arm=on\n' | \
    sudo tee -a /boot/firmware/config.txt >/dev/null
fi

# Use product-neutral network/console identification in normal operation.
sudo hostnamectl set-hostname dvp-processing
if grep -Eq '^127\.0\.1\.1[[:space:]]+' /etc/hosts; then
  sudo sed -Ei 's|^127\.0\.1\.1[[:space:]]+.*|127.0.1.1\tdvp-processing|' /etc/hosts
fi

sudo systemctl set-default graphical.target
sudo systemctl daemon-reload
sudo systemctl enable lightdm NetworkManager dvp-hotspot.service >/dev/null

echo
echo "DVP processing appliance configuration is complete."
echo "The paired DVP touch hotspot will now be configured and activated."
echo "If this terminal uses wlan0 remotely, its connection may close normally."
echo "Afterwards reboot with: sudo reboot"
echo "Recovery: press Ctrl+Alt+F2, log in, and run ./restore_desktop.sh"
echo

# Keep this last: activation intentionally replaces the current wlan0
# connection. All local appliance changes are already safely committed.
exec bash "$DVP_ROOT/tools/touch_hotspot.sh" setup
