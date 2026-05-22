#!/bin/bash
set -e

source /opt/ros/${ROS_DISTRO}/setup.bash

cd /workspace
colcon build

source /workspace/install/setup.bash

# Make ros2 available in any future exec shells
echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc
echo "source /workspace/install/setup.bash" >> /root/.bashrc

exec "$@"