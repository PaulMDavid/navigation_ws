#!/usr/bin/env bash
# Run the real teleop_mux and test_mux_ros.py in one container on loopback DDS.
# Laptop only, no robot. Image: phonetest-app_teleop (the phone stand-in build).
set -euo pipefail
cd "$(dirname "$0")/../.."
docker run --rm --network none --memory 1g \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -e ROS_DOMAIN_ID=0 -e TELEOP_PHONE_DOMAIN=51 \
  -v "$PWD/utils/rover_arming/cyclonedds_lo.xml:/etc/cyclonedds.xml:ro" \
  -v "$PWD/src/app_teleop:/app:ro" -v "$PWD/utils/teleop_gears:/t:ro" \
  "${IMAGE:-phonetest-app_teleop:latest}" bash -c '
    source /opt/ros/humble/setup.bash
    cd /app
    python3 teleop_mux.py --ros-args --params-file config/teleop.yaml -p source:=phone \
      -p initial_mode:=stop > /tmp/mux.log 2>&1 &
    python3 /t/test_mux_ros.py; rc=$?
    echo "--- mux log"; tail -20 /tmp/mux.log; exit $rc'
