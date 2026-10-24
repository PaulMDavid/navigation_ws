#!/usr/bin/env bash
# Push this checkout to a robot for testing. Edits and git happen here only;
# the robot copy is a plain file tree (no .git) that gets overwritten each sync.
#
#   scripts/sync_to_robot.sh                 # orintwo:/mnt/ssd/pdavid/navigation_ws
#   scripts/sync_to_robot.sh rover /home/rover/pdavid/navigation_ws
set -euo pipefail

host=${1:-orintwo}
dest=${2:-/mnt/ssd/pdavid/navigation_ws}
repo=$(cd "$(dirname "$0")/.." && pwd)

# data/ and rosbags/ hold runtime output on the robot, so they are neither sent nor deleted;
# recorded bags and point clouds (FAST-Calib's calib data is GBs) stay off the robot too.
rsync -az --delete --info=stats1 \
  --exclude='.git' --exclude='.gitmodules' \
  --exclude='build/' --exclude='install/' --exclude='log/' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='.dart_tool/' --exclude='.gradle/' \
  --exclude='data/' --exclude='rosbags/' \
  --exclude='calib_data/' --exclude='*.bag' --exclude='*.pcd' --exclude='*.db3' \
  --rsync-path="mkdir -p '$dest' && rsync" \
  "$repo/" "$host:$dest/"

echo "synced $repo -> $host:$dest"
