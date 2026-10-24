#!/bin/bash
# Build the driver/odometry sources this container loads, then run the command
# (by default an empty component container; the bringup manager loads into it).
# src/ is the whole repo mounted read-only, so only NAV_MASTER_PACKAGES are built.
# build/ and install/ are volumes: after the first start this is an incremental no-op.
set -e
source /opt/ros/${ROS_DISTRO}/setup.bash
cd /workspace

paths=()
for p in ${NAV_MASTER_PACKAGES}; do
    [ -d "src/$p" ] && paths+=("src/$p")
done
# --merge-install: ouster_ros's install step breaks under --symlink-install
# One package at a time, 2 jobs: li_slam's scanmatcher and graph_based_slam each need
# 4-8 GB per compile job on arm64, and building them together went over the 16 GB
# container limit (utils/nav_master_startup). colcon's default is nproc x nproc.
export MAKEFLAGS=${MAKEFLAGS:--j2}
colcon build --merge-install --base-paths "${paths[@]}" \
    --parallel-workers "${NAV_MASTER_BUILD_WORKERS:-1}" \
    --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash

exec "$@"
