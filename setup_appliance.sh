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

DVP_INSTALL_REQUIRED=0
if [[ ! -x "$DVP_ROOT/.venv/bin/python" ]]; then
  DVP_INSTALL_REQUIRED=1
elif ! "$DVP_ROOT/.venv/bin/python" -c 'import lgpio' >/dev/null 2>&1; then
  DVP_INSTALL_REQUIRED=1
elif getent group gpio >/dev/null && \
     ! id -nG "$DVP_USER" | tr ' ' '\n' | grep -qx gpio; then
  DVP_INSTALL_REQUIRED=1
fi
if [[ "$DVP_INSTALL_REQUIRED" -eq 1 ]]; then
  echo "DVP dependencies or GPIO permissions need updating; running install.sh first."
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
  "$DVP_ROOT/tools/touch_hotspot.sh" "$DVP_ROOT/tools/test_usb_buzzer.py" \
  "$DVP_ROOT/restore_desktop.sh"

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
      s#(^|[[:space:]])plymouth\.ignore-serial-consoles([[:space:]]|$)# #g
      s#(^|[[:space:]])plymouth\.enable=[^[:space:]]+# #g
      s#(^|[[:space:]])quiet([[:space:]]|$)# #g
      s#(^|[[:space:]])logo\.nologo([[:space:]]|$)# #g
      s#(^|[[:space:]])loglevel=[^[:space:]]+# #g
      s#(^|[[:space:]])systemd\.show_status=[^[:space:]]+# #g
      s#(^|[[:space:]])rd\.systemd\.show_status=[^[:space:]]+# #g
      s#(^|[[:space:]])rd\.udev\.log_level=[^[:space:]]+# #g
      s#(^|[[:space:]])udev\.log_level=[^[:space:]]+# #g
      s#(^|[[:space:]])vt\.global_cursor_default=[^[:space:]]+# #g
      s#[[:space:]]+# #g
      s#^[[:space:]]+##
      s#[[:space:]]+$##
    }' "$DVP_BOOT_FILE"
    # Route diagnostics to the serial maintenance console instead of HDMI.
    # console=null caused plymouthd to fail on the deployed image, while no
    # console target can fall back to the active visible VT. Journald retains
    # service diagnostics and tty2 remains available for local recovery.
    for DVP_TOKEN in console=serial0,115200 quiet logo.nologo loglevel=0 \
      plymouth.enable=0 systemd.show_status=false \
      rd.systemd.show_status=false rd.udev.log_level=0 udev.log_level=0 \
      vt.global_cursor_default=0; do
      if ! grep -Eq "(^|[[:space:]])${DVP_TOKEN}([[:space:]]|$)" "$DVP_BOOT_FILE"; then
        sudo sed -i "1 s|[[:space:]]*$| $DVP_TOKEN|" "$DVP_BOOT_FILE"
      fi
    done
    break
  fi
done
sudo install -d -m 0755 /etc/systemd/system.conf.d
printf '%s\n' '[Manager]' 'ShowStatus=no' | \
  sudo tee /etc/systemd/system.conf.d/99-dvp-quiet.conf >/dev/null
sudo systemctl mask getty@tty1.service >/dev/null
for DVP_PLYMOUTH_UNIT in plymouth-start.service plymouth-read-write.service \
    plymouth-quit.service plymouth-quit-wait.service; do
  sudo systemctl mask "$DVP_PLYMOUTH_UNIT" >/dev/null 2>&1 || true
done
if [[ -f /boot/firmware/config.txt ]] && \
   ! grep -Eq '^[[:space:]]*disable_splash=1([[:space:]]*#.*)?$' /boot/firmware/config.txt; then
  printf '\n# DVP appliance: suppress firmware splash\ndisable_splash=1\n' | \
    sudo tee -a /boot/firmware/config.txt >/dev/null
fi
if [[ -f /boot/firmware/config.txt ]]; then
  if grep -Eq '^[[:space:]]*enable_uart=' /boot/firmware/config.txt; then
    sudo sed -Ei 's|^[[:space:]]*enable_uart=.*|enable_uart=1|' \
      /boot/firmware/config.txt
  else
    printf '\n# DVP serial maintenance console\nenable_uart=1\n' | \
      sudo tee -a /boot/firmware/config.txt >/dev/null
  fi
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
echo "Visible kernel/systemd console output is disabled; logs remain in the journal."
echo "The paired DVP touch hotspot will now be configured and activated."
echo "If this terminal uses wlan0 remotely, its connection may close normally."
echo "Afterwards reboot with: sudo reboot"
echo "Recovery: press Esc to reveal the desktop, or use Ctrl+Alt+F2."
echo

# Keep this last: activation intentionally replaces the current wlan0
# connection. All local appliance changes are already safely committed.
exec bash "$DVP_ROOT/tools/touch_hotspot.sh" setup
