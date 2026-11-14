#!/usr/bin/env bash
# Main process of rover-wheels.service (systemd user unit): runs morpheus_control and
# retries when an MD80 fails to come up.
#
#   ros2 launch morpheus_control morpheus_control.launch.py   (native ROS, no docker)
#
# CYCLONEDDS_URI stays unset: the rover's ~/.config/cyclonedds.xml is malformed and kills
# nodes. Output goes to $WHEELS_LOG (/tmp/wheels.log, emptied at each service start).
# If the log shows "Failed to add MD80 with ID: <id>": stop the launch, wait until
# /dev/ttyACM0 is free, `mdtool encoder <id>` (interrupted with SIGINT after 5 s), wait,
# relaunch; give up after $MD80_RETRIES relaunches. State for rover_wheels_ctl.sh status
# goes to $WHEELS_STATE.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=rover_wheels_common.sh
source "$here/rover_wheels_common.sh"

unset CYCLONEDDS_URI
set +u   # the ROS setup files reference unset variables
# shellcheck disable=SC1090
source "$ROS_SETUP" || { echo "can't source $ROS_SETUP" >&2; exit 1; }
# shellcheck disable=SC1091
source "$WHEELS_WS/install/setup.bash" || { echo "can't source $WHEELS_WS/install/setup.bash" >&2; exit 1; }
set -u

attempt=0 phase=starting failed_id='' last_failed='' added='' reason='' pid=''

save_state() {
  local tmp="$WHEELS_STATE.tmp"
  printf 'phase=%s\nattempt=%s\nfailed_id=%s\nlast_failed=%s\nadded=%s\nreason=%s\n' \
    "$phase" "$attempt" "$failed_id" "$last_failed" "$added" "$reason" > "$tmp" && mv -f "$tmp" "$WHEELS_STATE"
}
log() { echo "### rover-wheels: $*" >> "$WHEELS_LOG"; }

stop_launch() {  # SIGINT to the launch's process group, SIGKILL after 15 s
  [[ -n $pid ]] || return 0
  kill -INT -- "-$pid" 2>/dev/null
  local end=$((SECONDS + 15))
  while kill -0 "$pid" 2>/dev/null && (( SECONDS < end )); do sleep 0.2; done
  kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  pid=''
}

on_signal() {
  log "stop requested"
  stop_launch
  phase=stopped reason='service stopped'; save_state
  exit 0
}
trap on_signal INT TERM

# scan this attempt's part of the log: sets failed_id, added (unique ids, in order)
scan() {
  local line ids=() id
  failed_id=''
  while IFS= read -r line; do
    if [[ $line =~ $MD80_FAIL_RE ]]; then failed_id=${BASH_REMATCH[1]}; break; fi
    if [[ $line =~ $MD80_ADDED_RE ]]; then
      id=${BASH_REMATCH[1]}
      [[ " ${ids[*]} " == *" $id "* ]] || ids+=("$id")
    fi
  done < <(tail -n "+$((mark + 1))" "$WHEELS_LOG")
  added=${ids[*]}
}

all_expected() {
  local id
  for id in $MD80_IDS; do [[ " $added " == *" $id "* ]] || return 1; done
}

: > "$WHEELS_LOG"
while :; do
  attempt=$((attempt + 1)) phase=starting failed_id='' added='' reason=''
  save_state
  log "attempt $attempt ($(date -Is))"
  mark=$(wc -l < "$WHEELS_LOG")
  # own process group (setsid), and SIGINT back to default: bash starts background jobs
  # with SIGINT ignored, and ros2 launch must stop on it
  setsid env --default-signal=INT ros2 launch morpheus_control morpheus_control.launch.py >> "$WHEELS_LOG" 2>&1 &
  pid=$!
  started=$SECONDS last_added='' changed=$SECONDS
  # watch the start-up; once ready, just wait for the launch to end
  while kill -0 "$pid" 2>/dev/null; do
    scan
    [[ -n $failed_id ]] && break
    if [[ $added != "$last_added" ]]; then last_added=$added changed=$SECONDS; fi
    if [[ -n $added ]] && (( SECONDS - changed >= MD80_SETTLE )) && all_expected; then
      phase=ready reason="MD80 $added added"; save_state; break
    fi
    if [[ -z $added ]] && (( SECONDS - started >= MD80_QUIET )) && [[ -z $MD80_IDS ]]; then
      phase=quiet reason="no MD80 lines in the log after $MD80_QUIET s"; save_state; break
    fi
    sleep 0.5
  done

  if [[ -z $failed_id ]] && kill -0 "$pid" 2>/dev/null; then
    wait "$pid"; rc=$?
    pid=''
    phase=exited reason="launch exited (rc $rc)"; save_state
    log "$reason"
    exit 1
  fi
  if [[ -z $failed_id ]]; then
    wait "$pid"; rc=$?
    pid=''
    scan   # it may have printed the failure on its way out
    if [[ -z $failed_id ]]; then
      phase=exited reason="launch exited during start-up (rc $rc)"; save_state; log "$reason"; exit 1
    fi
  fi

  last_failed=$failed_id
  log "MD80 $failed_id failed to add (attempt $attempt)"
  stop_launch
  if (( attempt > MD80_RETRIES )); then
    phase=gave_up reason="MD80 $failed_id failed to add after $MD80_RETRIES retries"
    save_state; log "$reason"; exit 1
  fi
  phase=retrying reason="MD80 $failed_id failed to add; mdtool encoder $failed_id"; save_state
  if ! wait_port_free 15; then
    phase=failed reason="$MD80_PORT still held after the launch stopped (pid $(port_holders | tr '\n' ' '))"
    save_state; log "$reason"; exit 1
  fi
  sleep "$MDTOOL_GAP"
  log "mdtool encoder $failed_id"
  timeout -s INT -k 3 5 "$MDTOOL" encoder "$failed_id" >> "$WHEELS_LOG" 2>&1
  sleep "$MDTOOL_GAP"
done
