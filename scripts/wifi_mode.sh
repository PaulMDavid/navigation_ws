#!/usr/bin/env bash
# Switch orintwo's Wi-Fi between eduroam (client) and its own access point, so a phone
# can join it in the field. One radio (RTL8822CE, wlP1p1s0): either mode, not both.
#
#   sudo scripts/wifi_mode.sh ap       # hotspot: SSID/password from /etc/navws/teleop.env
#   sudo scripts/wifi_mode.sh client   # back to eduroam
#   scripts/wifi_mode.sh status
#
# Idempotent. Run it over the wired link (eno1, 192.168.1.210) or the console, never
# over the Wi-Fi it is about to switch: it refuses to. If the AP is not up within
# AP_TIMEOUT seconds it reverts to client by itself.
#
# Settings (all optional except AP_PASSWORD) in /etc/navws/teleop.env, which stays on
# the robot (scripts/robot_setup/apply.sh creates it):
#   AP_SSID=orintwo-teleop  AP_PASSWORD=...  AP_ADDRESS=10.42.0.1/24
#   WIFI_IFACE=wlP1p1s0  CLIENT_CON=eduroam  AP_TIMEOUT=30
set -euo pipefail

conf=${NAVWS_TELEOP_ENV:-/etc/navws/teleop.env}
# shellcheck disable=SC1090
[[ -r $conf ]] && source "$conf"
iface=${WIFI_IFACE:-wlP1p1s0}
client_con=${CLIENT_CON:-eduroam}
ap_con=${AP_CON:-navws-ap}
ap_ssid=${AP_SSID:-orintwo-teleop}
# 10.42.0.0/24: clear of the wired 192.168.1.0/24 and Docker's 172.16.0.0/12
ap_address=${AP_ADDRESS:-10.42.0.1/24}
ap_timeout=${AP_TIMEOUT:-30}

log() { echo "wifi_mode: $*" >&2; }

active_con() { nmcli -g GENERAL.CONNECTION dev show "$iface" 2>/dev/null || true; }

status() {
  local con mode
  con=$(active_con)
  mode=$(iw dev "$iface" info 2>/dev/null | awk '/type/ {print $2}')
  echo "interface: $iface"
  echo "connection: ${con:-none}"
  echo "mode: ${mode:-unknown}"
  ip -4 -o addr show dev "$iface" | awk '{print "address: " $4}'
  [[ $con == "$ap_con" ]] && echo "ssid: $ap_ssid (phone app: http://${ap_address%/*}:8080)"
  return 0
}

# Refuse to switch the link this shell arrived on.
guard_ssh() {
  [[ -n ${SSH_CONNECTION:-} ]] || return 0
  local server_ip=${SSH_CONNECTION% *}
  server_ip=${server_ip##* }
  if ip -4 -o addr show dev "$iface" | grep -qw "$server_ip"; then
    log "this SSH session runs over $iface ($server_ip); switching would cut it."
    log "connect over the wired link (192.168.1.210) or the console instead."
    exit 2
  fi
}

client() {
  if [[ $(active_con) == "$ap_con" ]]; then
    nmcli con down "$ap_con" >/dev/null
  fi
  if [[ $(active_con) == "$client_con" ]]; then
    log "already on $client_con"
    return 0
  fi
  # eduroam may be out of range in the field: not an error for the switch itself
  if nmcli -w 30 con up "$client_con" >/dev/null 2>&1; then
    log "connected to $client_con"
  else
    log "$client_con not reachable; $iface left to NetworkManager autoconnect"
    nmcli dev set "$iface" autoconnect yes || true
  fi
}

ap() {
  if [[ -z ${AP_PASSWORD:-} || ${#AP_PASSWORD} -lt 8 ]]; then
    log "AP_PASSWORD (8+ characters) must be set in $conf"
    exit 1
  fi
  local props=(
    connection.interface-name "$iface" connection.autoconnect no
    802-11-wireless.ssid "$ap_ssid" 802-11-wireless.mode ap 802-11-wireless.band bg
    ipv4.method shared ipv4.addresses "$ap_address" ipv6.method disabled
    wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp wifi-sec.group ccmp
    wifi-sec.pmf disable wifi-sec.psk "$AP_PASSWORD"
  )
  if nmcli -t -f NAME con show | grep -qx "$ap_con"; then
    nmcli con modify "$ap_con" "${props[@]}"
  else
    nmcli con add type wifi con-name "$ap_con" ssid "$ap_ssid" "${props[@]}" >/dev/null
  fi

  if [[ $(active_con) == "$ap_con" ]]; then
    log "access point already up"
    return 0
  fi
  local current
  current=$(active_con)
  [[ -n $current && $current != "--" ]] && nmcli con down "$current" >/dev/null || true

  if nmcli -w "$ap_timeout" con up "$ap_con" >/dev/null 2>&1 \
      && [[ $(iw dev "$iface" info | awk '/type/ {print $2}') == AP ]]; then
    log "access point $ap_ssid up on ${ap_address%/*}"
  else
    log "access point did not come up within ${ap_timeout}s; reverting to client"
    nmcli con down "$ap_con" >/dev/null 2>&1 || true
    client
    exit 1
  fi
}

if ! ip link show "$iface" >/dev/null 2>&1; then
  log "no interface $iface (set WIFI_IFACE in $conf)"
  exit 1
fi

case ${1:-status} in
  ap) guard_ssh; ap ;;
  client) guard_ssh; client ;;
  status) status ;;
  *) echo "usage: $0 ap|client|status" >&2; exit 64 ;;
esac
