#!/bin/bash
set -e

source /opt/ros/${ROS_DISTRO}/setup.bash
# livox_ros_driver2 lives in its own throwaway workspace baked into the image (see
# Dockerfile) — merge it in so `find_package(livox_ros_driver2 REQUIRED)` resolves
# when FAST-LIVO2 builds below, even though it's unused at runtime with the Ouster.
source /opt/ws_livox/install/setup.bash

# Build the workspace: FAST-LIVO2, vikit_common/vikit_ros, ouster_ros, zed_wrapper —
# all mounted from the host, see docker-compose.yaml.
cd /workspace
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release

# Source the workspace we just built
source /workspace/install/setup.bash

# Run whatever command you give (the launch file)
exec "$@"
