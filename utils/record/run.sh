#!/usr/bin/env bash
# record tests in a ROS Humble container (no ROS on the host), memory-capped. Reuses the
# image and fakes of utils/phone_ctl.
#   ./run.sh          shell tests (fakes) + ROS tests (real recorder, probe, watcher)
#   ./run.sh shell    record_drive.sh / phone_ctl.sh record with fakes only
#   ./run.sh ros      real ros2 bag record / phone_probe topics / record_watch.py on loopback DDS
#   ./run.sh <pytest args…>
# Output: results/<date>_pytest.txt
set -euo pipefail
cd "$(dirname "$0")"
here=$(pwd)
repo=$(cd ../.. && pwd)
mkdir -p results
docker build -q -t navws/phone_ctl_test ../phone_ctl >/dev/null
case ${1:-all} in
  all) tests=(test_record.py test_record_ros.py) ;;
  shell) tests=(test_record.py) ;;
  ros) tests=(test_record_ros.py) ;;
  *) tests=("$@") ;;
esac
out=results/$(date +%F)_pytest.txt
# /bags and /navws_record exist as on orintwo's recorder container, so the real recorder
# command record_drive.sh builds runs unchanged. Domain 83, loopback only.
docker run --rm --init --network host --ipc host --memory 2g --memory-swap 2g \
  -u "$(id -u):$(id -g)" -e HOME=/tmp -e ROS_HOME=/tmp/ros \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -e ROS_DOMAIN_ID=83 -e PYTHONUNBUFFERED=1 -e PYTHONDONTWRITEBYTECODE=1 \
  -e APP_DIR=/repo/src/app_teleop -e REPO=/repo \
  --tmpfs "/bags:uid=$(id -u),gid=$(id -g),size=512m" \
  -v "$repo/utils/phone_ctl/cyclonedds_lo.xml:/etc/cyclonedds.xml:ro" \
  -v "$repo:/repo:ro" -v "$repo/scripts/record:/navws_record:ro" \
  navws/phone_ctl_test \
  bash -c "source /opt/ros/humble/setup.bash && cd /repo/utils/record && python3 -m pytest -v -p no:cacheprovider $(printf "%q " "${tests[@]}")" \
  2>&1 | tee "$out"
exit "${PIPESTATUS[0]}"
