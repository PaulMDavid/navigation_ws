#!/usr/bin/env bash
# nav_relay tests in a ROS Humble container (no ROS on the host), memory-capped.
#   ./run.sh          unit tests (nav_relay_core.py) + ROS test with the real teleop_mux and fake Nav2/SLAM/bringup
#   ./run.sh unit     unit tests only
#   ./run.sh bench    time the map downsample + PNG work (bench_map.py)
# Output: results/<date>_pytest.txt
set -euo pipefail
cd "$(dirname "$0")"
here=$(pwd)
app=$(cd ../../src/app_teleop && pwd)
mkdir -p results
docker build -q -t navws/nav_relay_test . >/dev/null
tests=(test_core.py)
[[ ${1:-all} == unit ]] || tests+=(test_node.py)
cmd="python3 -m pytest -v -p no:cacheprovider ${tests[*]}"
out=results/$(date +%F)_pytest.txt
if [[ ${1:-all} == bench ]]; then cmd="python3 -I bench_map.py"; out=results/$(date +%F)_bench_map.txt; fi
docker run --rm --network host --ipc host --memory 2g --memory-swap 2g \
  -u "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_HOME=/tmp/ros \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -e ROS_DOMAIN_ID=81 -e TELEOP_PHONE_DOMAIN=83 -e PYTHONUNBUFFERED=1 \
  -e APP_DIR=/workspace/app_teleop -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$here/cyclonedds_lo.xml:/etc/cyclonedds.xml:ro" \
  -v "$app:/workspace/app_teleop:ro" -v "$here:/test/nav_relay:ro" \
  navws/nav_relay_test \
  bash -c "source /opt/ros/humble/setup.bash && cd /test/nav_relay && $cmd" \
  2>&1 | tee "$out"
exit "${PIPESTATUS[0]}"
