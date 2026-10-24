#!/usr/bin/env bash
# One-time setup on a robot, run there with sudo:  sudo ./apply.sh
# - DDS socket buffer limits (60-ros2-dds.conf), applied now and at every boot
# - persistent journal, so logs from before a freeze or reboot survive it
# - teleop: /etc/navws/teleop.env and the navws-teleop boot unit
set -euo pipefail
cd "$(dirname "$0")"

install -m 0644 60-ros2-dds.conf /etc/sysctl.d/60-ros2-dds.conf
sysctl -p /etc/sysctl.d/60-ros2-dds.conf

mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl --disk-usage

# teleop: settings file (stays on the robot; holds the AP password) and the boot unit
# that applies the saved command source (scripts/teleop_source.sh)
repo=$(cd ../.. && pwd)
install -d -m 0755 /etc/navws
if [[ ! -e /etc/navws/teleop.env ]]; then
  install -m 0600 /dev/null /etc/navws/teleop.env
  cat > /etc/navws/teleop.env <<'ENV'
# ground | phone   (scripts/teleop_source.sh)
TELEOP_SOURCE=ground
# access point for the phone (scripts/wifi_mode.sh); set a password before using phone
AP_SSID=orintwo-teleop
AP_PASSWORD=
ENV
  echo "created /etc/navws/teleop.env: set AP_PASSWORD before switching to phone"
fi
sed "s|@REPO@|$repo|" navws-teleop.service > /etc/systemd/system/navws-teleop.service
systemctl daemon-reload
systemctl enable navws-teleop.service
