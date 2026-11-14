#!/usr/bin/env bash
# rover_arming tests in a ROS Humble container (no ROS on the host), memory-capped.
#   ./run.sh          unit tests (rover_tracker.py) + ROS test with the real teleop_mux
#   ./run.sh unit     unit tests only
# Output: results/<date>_pytest.txt
set -euo pipefail
cd "$(dirname "$0")"
here=$(pwd)
app=$(cd ../../src/app_teleop && pwd)
mkdir -p results
docker build -q -t navws/rover_arming_test . >/dev/null
tests=(test_tracker.py)
[[ ${1:-all} == unit ]] || tests+=(test_node.py)
out=results/$(date +%F)_pytest.txt
docker run --rm --network host --ipc host --memory 2g --memory-swap 2g \
  -u "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_HOME=/tmp/ros \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -e ROS_DOMAIN_ID=77 -e TELEOP_PHONE_DOMAIN=79 -e PYTHONUNBUFFERED=1 \
  -e APP_DIR=/workspace/app_teleop -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$here/cyclonedds_lo.xml:/etc/cyclonedds.xml:ro" \
  -v "$app:/workspace/app_teleop:ro" -v "$here:/test/rover_arming:ro" \
  navws/rover_arming_test \
  bash -c "source /opt/ros/humble/setup.bash && cd /test/rover_arming && python3 -m pytest -v -p no:cacheprovider ${tests[*]}" \
  2>&1 | tee "$out"
exit "${PIPESTATUS[0]}"
