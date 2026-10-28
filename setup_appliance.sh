#!/usr/bin/env bash
set -euo pipefail

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DVP_USER="$(id -un)"
DVP_LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
DVP_LIGHTDM_BACKUP="/etc/lightdm/lightdm.conf.before-dvp"
DVP_KIOSK_CONF="/etc/lightdm/lightdm.conf.d/99-dvp-kiosk.conf"
DVP_XSESSION="/usr/share/xsessions/dvp.desktop"
DVP_HOTSPOT_SERVICE="/etc/systemd/system/dvp-hotspot.service"
DVP_LABWC_AUTOSTART="/etc/xdg/labwc/autostart"
DVP_LABWC_BACKUP="/etc/xdg/labwc/autostart.before-dvp"
DVP_DESKTOP_SESSION=""

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
if [[ ! -f "$DVP_LIGHTDM_CONF" ]]; then
  echo "LightDM configuration was not found: $DVP_LIGHTDM_CONF" >&2
  exit 1
fi

# DVP must run above the ordinary desktop session. This is intentional: the
# interface starts automatically and covers the desktop, but a deliberate Esc
# exit reveals the already-running maintenance desktop instead of relaunching
# DVP. Raspberry Pi OS currently calls this session rpd-labwc; retain fallbacks
# for supported older desktop images.
for DVP_SESSION_CANDIDATE in rpd-labwc LXDE-pi lightdm-xsession; do
  if [[ -f "/usr/share/wayland-sessions/$DVP_SESSION_CANDIDATE.desktop" || \
        -f "/usr/share/xsessions/$DVP_SESSION_CANDIDATE.desktop" ]]; then
    DVP_DESKTOP_SESSION="$DVP_SESSION_CANDIDATE"
    break
  fi
done
if [[ -z "$DVP_DESKTOP_SESSION" ]]; then
  echo "No supported maintenance desktop session was found." >&2
  echo "Install the 64-bit OS image with Desktop, then run this setup again." >&2
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

DVP_TEMP_LIGHTDM="$(mktemp)"
DVP_TEMP_HOTSPOT="$(mktemp)"
DVP_TEMP_EARLY_START="$(mktemp)"
trap 'rm -f -- "$DVP_TEMP_LIGHTDM" "$DVP_TEMP_HOTSPOT" "$DVP_TEMP_EARLY_START"' EXIT
sed "s|@DVP_ROOT@|$DVP_ROOT|g" \
  "$DVP_ROOT/appliance/dvp-hotspot.service" > "$DVP_TEMP_HOTSPOT"
{
  printf '%s\n' '[Seat:*]'
  printf 'autologin-user=%s\n' "$DVP_USER"
  printf '%s\n' 'autologin-user-timeout=0'
  printf 'user-session=%s\n' "$DVP_DESKTOP_SESSION"
  printf 'autologin-session=%s\n' "$DVP_DESKTOP_SESSION"
} > "$DVP_TEMP_LIGHTDM"

sudo install -d -m 0755 /etc/lightdm/lightdm.conf.d
sudo install -m 0644 "$DVP_TEMP_LIGHTDM" "$DVP_KIOSK_CONF"
sudo install -m 0644 "$DVP_TEMP_HOTSPOT" \
  "$DVP_HOTSPOT_SERVICE"
# Remove the obsolete locked session from packages up to 3.2.5. It launched a
# restart supervisor, which is why Esc appeared to exit and then opened DVP
# again. The early desktop-session launcher below runs start_dvp.sh only once.
sudo rm -f "$DVP_XSESSION"

# The base image may set autologin-session in lightdm.conf itself. That value
# overrides the drop-in, so update any active assignment while retaining the
# complete original file above for recovery.
if grep -Eq '^[[:space:]]*autologin-session=' "$DVP_LIGHTDM_CONF"; then
  sudo sed -Ei "s|^[[:space:]]*autologin-session=.*|autologin-session=$DVP_DESKTOP_SESSION|" \
    "$DVP_LIGHTDM_CONF"
fi
if grep -Eq '^[[:space:]]*user-session=' "$DVP_LIGHTDM_CONF"; then
  sudo sed -Ei "s|^[[:space:]]*user-session=.*|user-session=$DVP_DESKTOP_SESSION|" \
    "$DVP_LIGHTDM_CONF"
fi
if grep -Eq '^[[:space:]]*autologin-user=' "$DVP_LIGHTDM_CONF"; then
  sudo sed -Ei "s|^[[:space:]]*autologin-user=.*|autologin-user=$DVP_USER|" \
    "$DVP_LIGHTDM_CONF"
fi
if getent group autologin >/dev/null; then
  sudo usermod -aG autologin "$DVP_USER"
fi

# On the current labwc desktop, start DVP before the distribution's wallpaper,
# panel, file manager, and XDG-autostart commands. The DVP command deliberately
# runs in the foreground. Pressing Esc lets the saved system autostart continue,
# revealing the desktop without ever flashing it before DVP. The system file is
# backed up once and regenerated from that clean copy on every setup run.
if [[ "$DVP_DESKTOP_SESSION" == "rpd-labwc" && -f "$DVP_LABWC_AUTOSTART" ]]; then
  if [[ ! -e "$DVP_LABWC_BACKUP" ]]; then
    sudo cp -a "$DVP_LABWC_AUTOSTART" "$DVP_LABWC_BACKUP"
  fi
  {
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' '# DVP early foreground launch; installed by setup_appliance.sh.'
    printf '"%s/start_dvp.sh"\n' "$DVP_ROOT"
    printf '%s\n' 'DVP_RESULT=$?'
    printf '%s\n' 'DVP_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}'
    printf '%s\n' 'if [ -e "$DVP_RUNTIME_DIR/dvp-poweroff-requested" ]; then'
    printf '%s\n' '  exit "$DVP_RESULT"'
    printf '%s\n' 'fi'
    printf '%s\n' '# DVP exited with Esc or an error: finish starting the desktop.'
    sudo cat "$DVP_LABWC_BACKUP"
  } > "$DVP_TEMP_EARLY_START"
  sudo install -m 0755 "$DVP_TEMP_EARLY_START" "$DVP_LABWC_AUTOSTART"
  # Avoid a second, delayed launch from the ordinary XDG desktop autostart.
  "$DVP_ROOT/.venv/bin/python" "$DVP_ROOT/tools/autostart.py" disable
else
  # Compatibility fallback for older non-labwc desktop images.
  "$DVP_ROOT/.venv/bin/python" "$DVP_ROOT/tools/autostart.py" enable
fi

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
echo "Early desktop-backed DVP startup is enabled ($DVP_DESKTOP_SESSION)."
echo "The desktop starts only after DVP exits with Esc."
echo "The paired DVP touch hotspot will now be configured and activated."
echo "If this terminal uses wlan0 remotely, its connection may close normally."
echo "Afterwards reboot with: sudo reboot"
echo "Recovery: press Esc to reveal the desktop, or use Ctrl+Alt+F2."
echo

# Keep this last: activation intentionally replaces the current wlan0
# connection. All local appliance changes are already safely committed.
exec bash "$DVP_ROOT/tools/touch_hotspot.sh" setup
