# Settings shared by rover_wheels_run.sh and rover_wheels_ctl.sh (sourced, not run).
# Override any of them in ~/.config/rover-wheels.env (KEY=value lines; the unit reads it too).
# shellcheck disable=SC2034
[[ -r ${ROVER_WHEELS_ENV:-$HOME/.config/rover-wheels.env} ]] && \
  source "${ROVER_WHEELS_ENV:-$HOME/.config/rover-wheels.env}"
ROS_SETUP=${ROS_SETUP:-/opt/ros/humble/setup.bash}
# DDS for the launch, set here because systemd and ssh skip ~/.bashrc (issue #49:
# without them the wheels ran Fast DDS and lost most of /cmd_vel from orintwo)
WHEELS_RMW=${WHEELS_RMW:-rmw_cyclonedds_cpp}
WHEELS_DOMAIN_ID=${WHEELS_DOMAIN_ID:-0}
WHEELS_DDS_XML=${WHEELS_DDS_XML:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cyclonedds_rover.xml}
WHEELS_WS=${WHEELS_WS:-$HOME/erc25/wheels_ws}
WHEELS_LOG=${WHEELS_LOG:-/tmp/wheels.log}
WHEELS_STATE=${WHEELS_STATE:-/tmp/rover-wheels.state}
WHEELS_UNIT=${WHEELS_UNIT:-rover-wheels.service}
MD80_PORT=${MD80_PORT:-/dev/ttyACM0}
MDTOOL=${MDTOOL:-mdtool}
MDTOOL_GAP=${MDTOOL_GAP:-3}          # s between mdtool calls / after the controller stops
MD80_RETRIES=${MD80_RETRIES:-3}      # relaunches after "Failed to add MD80"; then give up
MD80_SETTLE=${MD80_SETTLE:-5}        # whole s without new MD80 lines after the last "Added" = ready
MD80_QUIET=${MD80_QUIET:-20}         # whole s alive with no MD80 line at all = "quiet" (warn)
MD80_IDS=${MD80_IDS:-}               # optional: ids that must all show as added, e.g. "11 12 13 14"
# candle's log lines; the failure text is from the field, the success text is a guess
MD80_FAIL_RE=${MD80_FAIL_RE:-'Failed to add MD80 with ID: *([0-9]+)'}
MD80_ADDED_RE=${MD80_ADDED_RE:-'[Aa]dded MD80[^0-9]*([0-9]+)'}
ZERO_IDS_OK=(11 12 13 14)            # steering MD80s FL FR RL RR

# pids that have $MD80_PORT open (only this user's processes are visible, which is enough:
# the controller runs as this user)
port_holders() {
  local fd pids=()
  for fd in /proc/[0-9]*/fd/*; do
    [[ $(readlink "$fd" 2>/dev/null) == "$MD80_PORT" ]] || continue
    fd=${fd#/proc/}; pids+=("${fd%%/*}")
  done
  (( ${#pids[@]} )) && printf '%s\n' "${pids[@]}" | sort -un
  return 0
}

# wait until nothing holds the port; 1 if it is still held after $1 s
wait_port_free() {
  local end=$((SECONDS + ${1:-15}))
  while [[ -n $(port_holders) ]]; do
    (( SECONDS >= end )) && return 1
    sleep 0.5
  done
}
