#!/usr/bin/env bash
# Guided rover bring-up, run on orintwo over the wired link (ssh orintwo@192.168.1.210):
#
#   scripts/rover_bringup.sh            # both steps
#   scripts/rover_bringup.sh wifi       # step 1 only: join your phone hotspot
#   scripts/rover_bringup.sh up         # step 2 only: start everything
#
# Step 1 walks you through the nmcli commands that put orintwo on your phone's hotspot
# (scan, connect with your hotspot name + password). Step 2 runs scripts/phone_ctl.sh up
# and camera. See ROVER_BRINGUP.md.
set -uo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
iface=${WIFI_IFACE:-wlP1p1s0}

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
cmd()  { printf '  \033[36m$ %s\033[0m\n' "$*"; }
ask()  { local a; read -r -p "$1 " a; printf '%s' "$a"; }
pause() { read -r -p "Press Enter to run it (Ctrl-C to quit) "; }

wifi_ip() { ip -4 -o addr show dev "$iface" | awk '{split($4, a, "/"); print a[1]; exit}'; }

# switching the Wi-Fi would cut an ssh session that came in over it
guard_ssh() {
  [[ -n ${SSH_CONNECTION:-} ]] || return 0
  local server_ip=${SSH_CONNECTION% *}; server_ip=${server_ip##* }
  if ip -4 -o addr show dev "$iface" | grep -qw "$server_ip"; then
    echo "You are logged in over orintwo's Wi-Fi ($server_ip); changing it would cut this session."
    echo "Log in over the cable instead: ssh orintwo@192.168.1.210"
    exit 2
  fi
}

step_wifi() {
  bold "Step 1/2: connect orintwo to your phone hotspot"
  echo "Turn on the hotspot on your phone now (2.4 GHz band if the phone lets you choose)."
  ask "Press Enter when it is on." >/dev/null

  bold "1a. Scan for Wi-Fi networks"
  # a scan needs root here (polkit: wifi.scan = auth); without sudo nmcli only lists the cache
  cmd "sudo nmcli dev wifi list --rescan yes ifname $iface"
  pause
  sudo nmcli dev wifi list --rescan yes ifname "$iface" \
    || echo "Scan failed; the list may be old. Wait a few seconds and run the step again."
  echo "Your hotspot must be in this list. If not: check the phone, then run this step again."

  local ssid
  while [[ -z ${ssid:-} ]]; do ssid=$(ask "Hotspot name (SSID), exactly as in the list:"); done

  bold "1b. Connect (nmcli asks for the hotspot password)"
  cmd "sudo nmcli --ask dev wifi connect \"$ssid\" ifname $iface"
  pause
  if ! sudo nmcli --ask dev wifi connect "$ssid" ifname "$iface"; then
    echo "Connecting failed (wrong password, or the hotspot is out of range). Run the step again:"
    echo "  scripts/rover_bringup.sh wifi"
    exit 1
  fi

  bold "1c. Prefer this hotspot over eduroam"
  echo "orintwo has fallen back to eduroam on its own before; a higher priority keeps it on your hotspot."
  cmd "sudo nmcli con modify \"$ssid\" connection.autoconnect yes connection.autoconnect-priority 20"
  pause
  sudo nmcli con modify "$ssid" connection.autoconnect yes connection.autoconnect-priority 20

  local ip; ip=$(wifi_ip)
  bold "orintwo is on \"$ssid\" with address ${ip:-?}"
  echo "Enter ${ip:-this address} as the robot address in the phone app."
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

step_up() {
  bold "Step 2/2: start everything"
  echo "Starts the teleop containers on orintwo and the wheels on the rover, checking each step."
  cmd "scripts/phone_ctl.sh up"
  pause
  "$repo/scripts/phone_ctl.sh" up | pretty
  (( PIPESTATUS[0] == 0 )) || { echo "Logs of a step: scripts/phone_ctl.sh log <step>"; exit 1; }

  bold "Camera for the phone app (first ZED start can take ~6 min)"
  cmd "scripts/phone_ctl.sh camera"
  pause
  "$repo/scripts/phone_ctl.sh" camera | pretty
  (( PIPESTATUS[0] == 0 )) || echo "Camera failed; driving works without it. Logs: scripts/phone_ctl.sh log camera"

  local ip; ip=$(wifi_ip)
  bold "Ready to drive"
  echo "  Phone app robot address: ${ip:-unknown, check: ip -4 addr show $iface}"
  echo "  Wheels page: press ARM once (it is a toggle), then drive from Controls."
  echo "  When done: scripts/phone_ctl.sh stop"
}

case ${1:-all} in
  all)  guard_ssh; step_wifi; step_up ;;
  wifi) guard_ssh; step_wifi ;;
  up)   step_up ;;
  *) echo "usage: $0 [all|wifi|up]" >&2; exit 64 ;;
esac
