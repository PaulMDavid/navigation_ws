#!/usr/bin/env bash
# One-time setup on a robot, run there with sudo:  sudo ./apply.sh
# - DDS socket buffer limits (60-ros2-dds.conf), applied now and at every boot
# - persistent journal, so logs from before a freeze or reboot survive it
set -euo pipefail
cd "$(dirname "$0")"

install -m 0644 60-ros2-dds.conf /etc/sysctl.d/60-ros2-dds.conf
sysctl -p /etc/sysctl.d/60-ros2-dds.conf

mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl --disk-usage
