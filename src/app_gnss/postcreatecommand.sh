#!/bin/bash
set -e
source /opt/ros/${ROS_DISTRO}/setup.bash
cd /workspace
colcon build --merge-install
source /workspace/install/setup.bash
exec "$@"
