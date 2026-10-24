#!/usr/bin/env bash
# Choose who drives the rover in manual mode, and bring up what that needs.
#
#   sudo scripts/teleop_source.sh ground   # ground-station PC over Zenoh; orintwo on eduroam
#   sudo scripts/teleop_source.sh phone    # phone app over foxglove_bridge; orintwo as AP
#   sudo scripts/teleop_source.sh apply    # apply the saved choice (run at boot by navws-teleop.service)
#   scripts/teleop_source.sh status
#
# The choice is TELEOP_SOURCE in /etc/navws/teleop.env, on the robot, not in the repo.
# Switching is that one line plus `apply` (or a reboot). If the access point fails to
# come up, phone falls back to ground so the robot stays reachable over eduroam.
# Run it over the wired link, not over Wi-Fi (scripts/wifi_mode.sh refuses otherwise).
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
conf=${NAVWS_TELEOP_ENV:-/etc/navws/teleop.env}
project=${COMPOSE_PROJECT:-navbringup}

log() { echo "teleop_source: $*" >&2; }

compose() { (cd "$repo/src" && docker compose -p "$project" "$@"); }

saved_source() {
  local s=ground
  # shellcheck disable=SC1090
  [[ -r $conf ]] && s=$(source "$conf"; echo "${TELEOP_SOURCE:-ground}")
  echo "$s"
}

save() {
  mkdir -p "$(dirname "$conf")"
  touch "$conf" && chmod 600 "$conf"
  if grep -q '^TELEOP_SOURCE=' "$conf"; then
    sed -i "s/^TELEOP_SOURCE=.*/TELEOP_SOURCE=$1/" "$conf"
  else
    echo "TELEOP_SOURCE=$1" >> "$conf"
  fi
  log "saved TELEOP_SOURCE=$1 in $conf"
}

apply() {
  local source
  source=$(saved_source)
  case $source in
    phone)
      if ! "$repo/scripts/wifi_mode.sh" ap; then
        log "access point failed: falling back to ground for this boot"
        source=ground
      fi ;;
    ground)
      "$repo/scripts/wifi_mode.sh" client ;;
    *) log "unknown TELEOP_SOURCE=$source in $conf"; exit 1 ;;
  esac

  export TELEOP_SOURCE=$source
  compose up -d app_teleop app_zenoh_bridge
  if [[ $source == phone ]]; then
    compose up -d app_foxglove_bridge app_teleop_phone
  else
    # nothing listens for the phone; don't leave port 8765 open on eduroam
    compose stop app_foxglove_bridge app_teleop_phone 2>/dev/null || true
  fi
  log "command source: $source"
}

case ${1:-status} in
  ground|phone) save "$1"; apply ;;
  apply) apply ;;
  status)
    echo "saved source: $(saved_source)"
    docker exec app_teleop_container true 2>/dev/null \
      && docker logs app_teleop_container 2>&1 | grep -m1 'source=' || echo "app_teleop not running"
    "$repo/scripts/wifi_mode.sh" status ;;
  *) echo "usage: $0 ground|phone|apply|status" >&2; exit 64 ;;
esac
