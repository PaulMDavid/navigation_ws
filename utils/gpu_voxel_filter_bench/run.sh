#!/usr/bin/env bash
# Build src/gpu_voxel_filter + this benchmark and run it on a bag, on the robot.
#   utils/gpu_voxel_filter_bench/run.sh [bag_dir] [clouds] [leaf]
# Builds go to /mnt/ssd/pdavid/gvf_ws; heavy steps hold /mnt/ssd/pdavid/.build.lock
# so they never overlap other builds (orintwo freezes under combined load).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
bag=${1:-/mnt/ssd/rtabmap_database/lab_bag_Jun22}
clouds=${2:-300}
leaf=${3:-0.1}
ws=/mnt/ssd/pdavid/gvf_ws
lock=/mnt/ssd/pdavid/.build.lock
mkdir -p "$ws"

# one lock for the whole script (flock cannot run the shell function below)
exec 9>"$lock"
flock 9

docker build -q -t gvf-bench "$here" >/dev/null

run() {
  docker run --rm --runtime nvidia --network host --memory 8g --memory-swap 8g \
    -v "$repo/src/gpu_voxel_filter:/ws/src/gpu_voxel_filter:ro" \
    -v "$here:/ws/src/gpu_voxel_filter_bench:ro" \
    -v "$ws/build:/ws/build" -v "$ws/install:/ws/install" -v "$ws/log:/ws/log" \
    -v "$bag:/bag:ro" -w /ws --entrypoint bash gvf-bench -c "$1"
}

run "source /opt/ros/humble/setup.bash && \
  colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -3"
run "source /ws/install/setup.bash && \
  ros2 run gpu_voxel_filter_bench bench /bag /ouster/points $clouds $leaf"
