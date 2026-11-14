#!/usr/bin/env bash
# The only thing orintwo's key may run on the rover (command="…/rover_wheels_ctl.sh" in
# ~/.ssh/authorized_keys, installed by install.sh). The verb comes from
# SSH_ORIGINAL_COMMAND, or from the arguments when run by hand:
#
#   start          start rover-wheels.service (no-op if it is running)
#   stop           stop it and wait until /dev/ttyACM0 is free
#   status         key=value lines: active, phase, attempt, failed_id, last_failed, added, reason
#   log            last 50 lines of /tmp/wheels.log
#   zero <ids>     ids from 11 12 13 14: stop the service, `mdtool config zero <id>`, wait,
#                  `mdtool config save <id>`, wait, for each id; start the service again
#
# rover-wheels.service is a systemd *user* unit (linger on, so it runs without a login).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=rover_wheels_common.sh
source "$here/rover_wheels_common.sh"
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
SYSTEMCTL=${SYSTEMCTL:-systemctl}

die() { echo "error: $*"; exit "${2:-1}"; }
sctl() { "$SYSTEMCTL" --user "$@"; }
is_active() { sctl is-active --quiet "$WHEELS_UNIT"; }
holders_desc() {
  local p out=()
  for p in $(port_holders); do out+=("$p ($(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | cut -c1-60))"); done
  echo "${out[*]}"
}

start() {
  if ! is_active && [[ -n $(port_holders) ]]; then
    die "$MD80_PORT is held by $(holders_desc): the hand-started wheels session (tmux) still running?"
  fi
  if is_active; then echo "already running"; return 0; fi
  rm -f "$WHEELS_STATE"
  sctl reset-failed "$WHEELS_UNIT" 2>/dev/null
  sctl start "$WHEELS_UNIT" || die "systemctl --user start $WHEELS_UNIT failed"
  echo "started"
}

stop() {
  sctl stop "$WHEELS_UNIT" || die "systemctl --user stop $WHEELS_UNIT failed"
  wait_port_free 15 || die "$MD80_PORT still held by $(holders_desc)"
  echo "stopped"
}

status() {
  local active
  active=$(sctl is-active "$WHEELS_UNIT" 2>/dev/null); active=${active:-unknown}
  echo "active=$active"
  if [[ -r $WHEELS_STATE ]]; then cat "$WHEELS_STATE"; else echo "phase=none"; fi
}

mdtool_call() {  # args…: one mdtool call, its output prefixed; fails on rc != 0
  local out rc
  out=$(timeout 20 "$MDTOOL" "$@" 2>&1); rc=$?
  printf '%s\n' "$out" >> "$WHEELS_LOG"
  if (( rc != 0 )); then
    echo "error: mdtool $* failed (rc $rc): $(printf '%s\n' "$out" | sed '/^[[:space:]]*$/d' | tail -n 1)"
    return 1
  fi
  echo "mdtool $* ok"
}

zero() {
  local id rc=0
  if ! is_active && [[ -n $(port_holders) ]]; then
    die "$MD80_PORT is held by $(holders_desc): not touching the MD80s"
  fi
  echo "stopping $WHEELS_UNIT"
  sctl stop "$WHEELS_UNIT" || die "systemctl --user stop failed"
  wait_port_free 15 || die "$MD80_PORT still held by $(holders_desc) after the stop"
  sleep "$MDTOOL_GAP"
  for id in "$@"; do
    echo "### zero: mdtool config zero/save $id ($(date -Is))" >> "$WHEELS_LOG"
    mdtool_call config zero "$id" || { rc=1; break; }
    sleep "$MDTOOL_GAP"
    mdtool_call config save "$id" || { rc=1; break; }
    sleep "$MDTOOL_GAP"
  done
  # bring the controller back in every case, so the rover isn't left limp
  rm -f "$WHEELS_STATE"
  sctl reset-failed "$WHEELS_UNIT" 2>/dev/null
  if ! sctl start "$WHEELS_UNIT"; then echo "error: systemctl --user start failed"; return 1; fi
  if (( rc )); then echo "error: zero stopped early; $WHEELS_UNIT started again"; return 1; fi
  echo "zeroed + saved $*; $WHEELS_UNIT started"
}

if [[ -n ${SSH_ORIGINAL_COMMAND+x} ]]; then cmd=$SSH_ORIGINAL_COMMAND; else cmd="$*"; fi
[[ $cmd =~ ^[a-z0-9\ ,]*$ ]] || die "refused: unexpected characters in command" 64
cmd=${cmd//,/ }
read -r -a words <<<"$cmd"
(( ${#words[@]} )) || die "refused: no command (start|stop|status|log|zero <ids>)" 64
verb=${words[0]}; args=("${words[@]:1}")
case $verb in
  start|stop|status|log) (( ${#args[@]} == 0 )) || die "refused: $verb takes no arguments" 64 ;;
  zero)
    (( ${#args[@]} )) || die "refused: zero needs ids from ${ZERO_IDS_OK[*]}" 64
    ids=()
    for a in "${args[@]}"; do
      [[ " ${ZERO_IDS_OK[*]} " == *" $a "* ]] || die "refused: MD80 id $a not in ${ZERO_IDS_OK[*]}" 64
      [[ " ${ids[*]} " == *" $a "* ]] || ids+=("$a")
    done ;;
  *) die "refused: unknown verb $verb (start|stop|status|log|zero <ids>)" 64 ;;
esac

case $verb in
  start) start ;;
  stop) stop ;;
  status) status ;;
  log) tail -n 50 "$WHEELS_LOG" 2>/dev/null || echo "no $WHEELS_LOG" ;;
  zero) zero "${ids[@]}" ;;
esac
