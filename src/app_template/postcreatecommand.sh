#!/bin/bash
set -e

# Source ROS
source /opt/ros/${ROS_DISTRO}/setup.bash

# Build the workspace
cd /workspace
colcon build --symlink-install

# Source the workspace we just built
source /workspace/install/setup.bash

# Run whatever command you give (the launch file)
exec "$@"
