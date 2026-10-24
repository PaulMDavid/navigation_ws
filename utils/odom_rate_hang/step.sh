#!/usr/bin/env bash
# Raise a rate knob step by step, holding each value, with markers in the logger's
# events.log so summarize.py can split the run per step.
#
#   ./step.sh [--hold 60] [--set 'CMD with {}'] 1.0 1.5 2.0 2.5
#
# Default knob: bag replay speed (utils/bag_replay, RATE), i.e. the cloud rate fed to
# odometry: 1.0 = 10 Hz, 2.0 = 20 Hz. For another knob, pass a command where {} is the
# value, e.g. --set 'docker exec app_rtab_map_container ros2 param set /rtabmap/icp_odometry ... {}'
# Start ./logger.sh first, and the stack under test.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
hold=60
set_cmd="cd $here/../bag_replay && RATE={} docker compose up -d player"
while [[ ${1:-} == --* ]]; do
  case $1 in
    --hold) hold=$2; shift 2 ;;
    --set) set_cmd=$2; shift 2 ;;
    *) echo "unknown option $1"; exit 1 ;;
  esac
done
(( $# )) || { echo "usage: $0 [--hold s] [--set cmd] value..."; exit 1; }

for v in "$@"; do
  "$here/mark.sh" "step $v"
  echo "$(date +%T) step $v (hold ${hold}s)"
  bash -c "${set_cmd//\{\}/$v}" > /dev/null 2>&1
  sleep "$hold"
done
"$here/mark.sh" "end"
echo "$(date +%T) done"
