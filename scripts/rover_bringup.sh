#!/usr/bin/env bash
# Rover bring-up, run on orintwo over the wired link (ssh orintwo@192.168.1.210):
#
#   scripts/rover_bringup.sh        # prints the 3 commands to type: scan, connect, up
#   scripts/rover_bringup.sh up     # starts everything (scripts/phone_ctl.sh up + camera)
#   scripts/rover_bringup.sh ip     # orintwo's Wi-Fi network + address, for the phone app
#
# See ROVER_BRINGUP.md.
set -uo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
iface=${WIFI_IFACE:-wlP1p1s0}

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
cmd()  { printf '  \033[36m$ %s\033[0m\n' "$*"; }
pause() { read -r -p "Press Enter to run it (Ctrl-C to quit) "; }

wifi_ip() { ip -4 -o addr show dev "$iface" | awk '{split($4, a, "/"); print a[1]; exit}'; }

step_wifi() {
  bold "Run these 3 commands on orintwo (over the cable), in $repo:"
  echo
  echo "1. Scan for networks. Your hotspot should be in the list; if it isn't, switch the"
  echo "   phone hotspot to 2.4 GHz and run the scan again."
  cmd "sudo nmcli dev wifi list --rescan yes ifname $iface"
  echo
  echo "2. Connect to your hotspot. Replace <your hotspot> (all 3 times) with its name exactly"
  echo "   as in the list; nmcli then asks for the password. This saves a connection and brings"
  echo "   it up (it scans by itself): a plain 'nmcli dev wifi connect' often says \"No network"
  echo "   ... found\" because orintwo drops a phone hotspot from its list within seconds."
  echo "   Next time the connection exists already: sudo nmcli --ask con up \"<your hotspot>\""
  cmd "sudo nmcli con add type wifi ifname $iface con-name \"<your hotspot>\" ssid \"<your hotspot>\" wifi-sec.key-mgmt wpa-psk && sudo nmcli --ask con up \"<your hotspot>\""
  echo
  echo "3. Start everything. It prints orintwo's hotspot address at the end; enter that"
  echo "   address in the phone app."
  cmd "scripts/rover_bringup.sh up"
  echo
}

# phone_ctl.sh prints one JSON object per line; show them as plain lines
pretty() { python3 -u -c "$pretty_py"; }
read -r -d '' pretty_py <<'PY'
import json, sys
mark = {"running": "..", "ok": "OK", "warn": "!!", "fail": "XX", "skipped": "--"}
for line in sys.stdin:
    try:
        d = json.loads(line)
    except ValueError:
        print(line, end="")
        continue
    if "done" in d:
        print("\n  ALL GOOD" if d["ok"] else "\n  STOPPED: fix the XX line, then run this step again")
        continue
    state = mark.get(d.get("state"), d.get("state"))
    print("  [%s] %-10s %s" % (state, d.get("step", ""), d.get("reason", "")), flush=True)
PY

show_address() {
  local net ip
  net=$(nmcli -g GENERAL.CONNECTION dev show "$iface" 2>/dev/null)
  ip=$(wifi_ip)
  bold "orintwo Wi-Fi: ${net:-not connected}   address: ${ip:-none}"
  if [[ -z $ip || -z $net || $net == eduroam ]]; then
    echo "  !! not on your phone hotspot yet: run commands 1 and 2 first (scripts/rover_bringup.sh)"
  else
    echo "  Enter $ip as the robot address in the phone app."
  fi
}

step_up() {
  show_address
  bold "Starting everything"
  echo "Starts the teleop containers on orintwo and the wheels on the rover, checking each step."
  cmd "scripts/phone_ctl.sh up"
  pause
  "$repo/scripts/phone_ctl.sh" up | pretty
  (( PIPESTATUS[0] == 0 )) || { echo "Logs of a step: scripts/phone_ctl.sh log <step>"; show_address; exit 1; }

  bold "Camera for the phone app (first ZED start can take ~6 min)"
  cmd "scripts/phone_ctl.sh camera"
  pause
  "$repo/scripts/phone_ctl.sh" camera | pretty
  (( PIPESTATUS[0] == 0 )) || echo "Camera failed; driving works without it. Logs: scripts/phone_ctl.sh log camera"

  bold "Ready to drive"
  show_address
  echo "  Wheels page: press ARM once (it is a toggle), then drive from Controls."
  echo "  When done: scripts/phone_ctl.sh stop"
}

case ${1:-help} in
  help|wifi) step_wifi ;;
  up) step_up ;;
  ip) show_address ;;
  *) echo "usage: $0 [up|ip]" >&2; exit 64 ;;
esac
