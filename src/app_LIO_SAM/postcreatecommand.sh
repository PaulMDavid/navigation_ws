#!/bin/bash
set -e

# Source ROS
source /opt/ros/${ROS_DISTRO}/setup.bash

sed -i 's/g2o::make_unique/std::make_unique/g' \
    /workspace/src/li_slam_ros2/graph_based_slam/src/graph_based_slam_component.cpp

sed -i 's/pointCloudTopic, 5, lc_callback/pointCloudTopic, rclcpp::SensorDataQoS(), lc_callback/' \
    /workspace/src/li_slam_ros2/scanmatcher/src/image_projection.cpp

# Fix QoS for odometry subscription in imu_preintegration
sed -i 's/"odometry", 5, odom_callback/"odometry", rclcpp::SensorDataQoS(), odom_callback/' \
    /workspace/src/li_slam_ros2/scanmatcher/src/imu_preintegration.cpp
    
# Install any deps declared in package.xml that aren't already present
cd /workspace
rosdep install --from-paths src --ignore-src -yr \
    --skip-keys "ament_python libg2o"

# Build the workspace
colcon build --symlink-install

# Source the workspace we just built
source /workspace/install/setup.bash

# Run whatever command you give (the launch file)
exec "$@"