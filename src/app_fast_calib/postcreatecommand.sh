#!/bin/bash
set -e

# Source ROS
source /opt/ros/noetic/setup.bash

# Build the catkin workspace (livox_ros_driver + fast_calib, mounted at src/fast_calib)
cd /workspace/catkin_ws
catkin_make

# Source the workspace we just built
source devel/setup.bash

# Run whatever command you give (the launch file)
exec "$@"
