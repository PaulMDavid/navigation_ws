#!/usr/bin/env bash
# First start of app_nav_master on orintwo: the container builds the mounted sources
# (Ouster, ZED, li_slam, gpu_voxel_filter), then we check the component plugins the
# stages load are all present. Tracks peak container memory and lowest host
# MemAvailable; the odom_rate_hang logger keeps a 1 Hz record that survives a freeze.
#   utils/nav_master_startup/run.sh [--fresh]   (--fresh wipes the build volumes first)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
name=app_nav_master_container
compose="docker compose -p navbringup -f $repo/src/app_nav_master/docker-compose.yaml"

exec 9>/mnt/ssd/pdavid/.build.lock
flock 9

if [[ ${1:-} == --fresh ]]; then
  $compose down -v >/dev/null 2>&1 || true
fi
"$repo/utils/odom_rate_hang/logger.sh" start nav_master_startup || true
trap '"$repo/utils/odom_rate_hang/logger.sh" stop >/dev/null || true' EXIT

start=$(date +%s); peak=0; low=999999
$compose up -d --no-build app_nav_master
while docker ps -q -f name=$name | grep -q . \
      && ! docker logs $name 2>&1 | grep -qE '^Summary:'; do
  mib=$(docker stats --no-stream --format '{{.MemUsage}}' $name | awk '{v=$1; if (v ~ /GiB/) v*=1024; print int(v)}')
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  (( mib > peak )) && peak=$mib; (( avail < low )) && low=$avail
  sleep 5
done
echo "== build ($(( $(date +%s) - start )) s, container peak ${peak} MiB, host MemAvailable low ${low} MiB)"
docker logs $name 2>&1 | grep -E 'Finished|Failed|Summary|Killed|error:' | head -30
docker ps -q -f name=$name | grep -q . || { echo "container exited"; docker logs --tail 30 $name; exit 1; }
sleep 5

echo "== plugins"
types=$(docker exec $name bash -c 'source /workspace/install/setup.bash && ros2 component types')
missing=0
for p in ouster_ros::OusterDriver stereolabs::ZedCamera \
         ImageProjection IMUPreintegration graphslam::ScanMatcherComponent \
         graphslam::GraphBasedSlamComponent gpu_voxel_filter::VoxelFilter \
         robot_state_publisher::RobotStatePublisher rtabmap_slam::CoreWrapper \
         nav2_controller::ControllerServer nav2_planner::PlannerServer \
         nav2_bt_navigator::BtNavigator behavior_server::BehaviorServer \
         nav2_lifecycle_manager::LifecycleManager; do
  if grep -qx "  $p" <<<"$types"; then echo "ok      $p"; else echo "MISSING $p"; missing=1; fi
done
grep -iE 'microstrain|ublox' <<<"$types" || echo "(no microstrain/ublox components registered)"
$compose stop >/dev/null
exit $missing
