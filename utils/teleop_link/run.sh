#!/usr/bin/env bash
# The laptop as orintwo: teleop_mux + foxglove_bridge + both Zenoh ends on loopback DDS,
# then probe.py drives the phone path and the ground path. See README.md.
set -euo pipefail
cd "$(dirname "$0")"
export PROBE_UID=$(id -u)
rm -rf results && mkdir -p results

docker compose up -d mux fox zenoh_robot zenoh_ground
trap 'docker compose --profile camera down >/dev/null 2>&1' EXIT
sleep 3
status=0

echo "== phone path (foxglove_bridge) =="
docker compose --profile probe run --rm probe python3 probe.py phone || status=1

if [[ -n ${CAMERA:-} ]]; then
  echo "== camera page (OV9281 standing in for the ZED) =="
  docker compose --profile camera up -d camera ov9281
  sleep 5
  docker compose --profile probe run --rm probe python3 probe.py camera || status=1
fi

echo "== ground path (Zenoh) =="
docker compose --profile probe run --rm probe python3 probe.py ground & probe=$!
for _ in $(seq 300); do [[ -e results/ground_ready ]] && break; sleep 0.1; done
docker compose kill zenoh_ground >/dev/null 2>&1
date +%s.%N > results/ground_killed
wait $probe || status=1

exit $status
