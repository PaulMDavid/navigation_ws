#!/usr/bin/env bash
# phone_ctl tests in a ROS Humble container (no ROS on the host), memory-capped.
#   ./run.sh          shell tests (fakes) + ROS probe test
#   ./run.sh shell    phone_ctl.sh / rover scripts with fakes only
#   ./run.sh probe    phone_probe.py against the real teleop_mux + rover_arming
#   ./run.sh <pytest args…>
# Output: results/<date>_pytest.txt
set -euo pipefail
cd "$(dirname "$0")"
here=$(pwd)
repo=$(cd ../.. && pwd)
mkdir -p results
docker build -q -t navws/phone_ctl_test . >/dev/null
case ${1:-all} in
  all) tests=(test_phone_ctl.py test_probe.py) ;;
  shell) tests=(test_phone_ctl.py) ;;
  probe) tests=(test_probe.py) ;;
  *) tests=("$@") ;;
esac
out=results/$(date +%F)_pytest.txt
docker run --rm --network host --ipc host --memory 2g --memory-swap 2g \
  -u "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_HOME=/tmp/ros \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -e ROS_DOMAIN_ID=77 -e TELEOP_PHONE_DOMAIN=79 -e PYTHONUNBUFFERED=1 \
  -e APP_DIR=/repo/src/app_teleop -e REPO=/repo -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$here/cyclonedds_lo.xml:/etc/cyclonedds.xml:ro" \
  -v "$repo:/repo:ro" \
  navws/phone_ctl_test \
  bash -c "source /opt/ros/humble/setup.bash && cd /repo/utils/phone_ctl && python3 -m pytest -v -p no:cacheprovider $(printf "%q " "${tests[@]}")" \
  2>&1 | tee "$out"
exit "${PIPESTATUS[0]}"
