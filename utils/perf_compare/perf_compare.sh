#!/usr/bin/env bash
# Record how a running stack performs, for comparing stacks against each other.
#
#   ./perf_compare.sh LABEL [SECONDS]      e.g. ./perf_compare.sh baseline-replay 120
#
# Run on the robot with the stack under test already up. Writes
# results/<date>-<label>.md and appends a row to this folder's README table.
# Topics measured are in topics.txt (one per line).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
label=${1:?usage: $0 LABEL [SECONDS]}
secs=${2:-120}
src=$here/../../src
work=$(mktemp -d /mnt/ssd/pdavid/logs/perf-XXXX)

tegrastats --interval 1000 > "$work/tegrastats.log" 2>&1 &
teg=$!
( end=$((SECONDS + secs))
  while (( SECONDS < end )); do
    docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' >> "$work/docker_stats.log"
  done ) &
dstats=$!

image=$(docker images --format '{{.Repository}}' | grep -m1 -x 'bag_replay-restamp\|navbringup-app_bringup_manager')
docker run --rm --network host --ipc host -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -v "$src/config/dds/cyclonedds.xml:/etc/cyclonedds.xml:ro" -v "$here/record.py:/record.py:ro" \
  "$image" python3 /record.py "$secs" $(grep -v '^#' "$here/topics.txt") \
  2>/dev/null | tail -1 > "$work/topics.json"

kill $teg 2>/dev/null; wait $dstats 2>/dev/null || true
python3 "$here/report.py" "$label" "$secs" "$work" "$here"
