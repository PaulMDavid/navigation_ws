#!/usr/bin/env bash
# Run on the laptop. Starts a bare component container on orintwo, points the bringup
# manager at stages_test.yaml, presses go, prints the status, then restores everything.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
"$here/../../scripts/sync_to_robot.sh" >/dev/null
robot=/mnt/ssd/pdavid/navigation_ws/src
# data/ is excluded from syncs, so a sync running meanwhile can't delete the test files
ssh orintwo "mkdir -p $robot/app_bringup_manager/data"
scp -q "$here/stages_test.yaml" "$here/rsp_test.yaml" orintwo:$robot/app_bringup_manager/data/
ssh orintwo bash -s <<REMOTE
set -e
cd $robot
docker rm -f test_container >/dev/null 2>&1 || true
docker run -d --name test_container --network host --ipc host -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml \
  -v $robot/config/dds/cyclonedds.xml:/etc/cyclonedds.xml:ro \
  --entrypoint /ros_entrypoint.sh navbringup-app_robot_state_publisher \
  ros2 run rclcpp_components component_container --ros-args -r __node:=test_container >/dev/null
BRINGUP_STAGES=data/stages_test.yaml docker compose -p navbringup up -d --no-build app_bringup_manager 2>&1 | tail -1
sleep 8
docker exec app_bringup_manager_container bash -c "source /opt/ros/humble/setup.bash
  ros2 service call /bringup/go std_srvs/srv/Trigger >/dev/null; sleep 12
  echo '--- after go'; ros2 component list
  ros2 service call /bringup/stop std_srvs/srv/Trigger >/dev/null; sleep 6
  echo '--- after stop'; ros2 component list" 2>&1 | grep -v deprecated
docker logs --since 40s app_bringup_manager_container 2>&1 | grep -v deprecated | grep -E "INFO|WARN|ERROR" | sed 's/.*\]: //'
docker rm -f test_container >/dev/null
REMOTE
ssh orintwo "rm -f $robot/app_bringup_manager/data/stages_test.yaml $robot/app_bringup_manager/data/rsp_test.yaml"
ssh orintwo "cd $robot && docker compose -p navbringup up -d --no-build app_bringup_manager 2>&1 | tail -1"
