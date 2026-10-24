# app_nav_master

The nav stack as composable nodes in **one process**: Ouster, ZED 2i, CV7 IMU, F9P GNSS,
the odometry slot (li_slam now, FAST-LIVO2 later), mapping and Nav2. Heavy topics
(Ouster clouds, ZED images) can then move intra-process instead of being serialized
through DDS between containers.

The container starts **empty** (`nav_master_container`); `app_bringup_manager` loads the
components stage by stage through `/nav_master_container/_container/load_node`, so a
failed stage is unloaded and reloaded without restarting the process.

## Image

`stereolabs/zed:5.1-devel-l4t-r36.4` (same as `app_zed2i_camera`: L4T R36.4, CUDA 12.6
with nvcc, ZED SDK 5.1) plus ROS 2 Humble, rtabmap, Nav2, microstrain, ublox_dgnss,
GTSAM and g2o. The driver sources stay in their own apps and are built at container
start from the read-only `src/` mount (list in `NAV_MASTER_PACKAGES`); build/install
live in volumes, so only the first start compiles.

```bash
# on the robot, from src/
docker compose -p navbringup -f app_nav_master/docker-compose.yaml build
NAV2_MAP_BACKEND=li_slam docker compose -p navbringup -f app_nav_master/docker-compose.yaml up -d
```

Don't run it alongside the separate sensor containers: they drive the same hardware.

## Config

One params file per node, `config/<subsystem>/`:

| File | Node |
| --- | --- |
| `sensors/ouster.yaml` | Ouster driver (self-activating: `auto_start`) |
| `sensors/zed2i.yaml` | ZED 2i; generated, self-contained (wrapper defaults + our launch args) |
| `sensors/microstrain.yaml` | CV7 AHRS |
| `sensors/ublox.yaml` | F9P |
| `robot/robot_state_publisher.yaml` | URDF publisher; `robot_description` is read from `app_robot_state_publisher/config/URDF/robot.urdf` by the loader |
| `robot/gnss_tf.yaml` | `chassis_link → gnss_link` |
| `mapping/rtabmap.yaml` | rtabmap, mapping only (rtabmap backend) |
| `nav2/nav2_params.yaml` | every Nav2 server, keyed by node name |
| `nav2/global_costmap_li_slam.yaml` / `_rtabmap.yaml` | global costmap per map backend |
| `odometry/` | the odometry slot (li_slam), owned separately |

**Odometry slot contract:** `odom → chassis_link` TF and a reliable `nav_msgs/Odometry`
on `/odometry/slot`. Nav2 and rtabmap read that topic.

**Map backend** (`NAV2_MAP_BACKEND`): `li_slam` (default) runs li_slam's graph, which owns
`map → odom`; its map is a point cloud, so the global costmap is a 50 m rolling window of
live lidar. `rtabmap` loads rtabmap mapping-only instead, which owns `map → odom` and
publishes `/rtabmap/map` for the global costmap's static layer.

**Why Nav2's params go to the container:** the costmaps are child nodes that Nav2's
servers create themselves. Parameters passed with `load_node` only reach the component,
while the container's `--params-file` reaches every node in the process, costmaps
included. The servers themselves are loaded with their own section of
`nav2/nav2_params.yaml` (components don't see global arguments).

## Components

Plugin names as listed by `ros2 component types` in this image:

| Stage | Package | Plugin | Namespace / name | Params | Remaps | Intra-process |
| --- | --- | --- | --- | --- | --- | --- |
| robot | robot_state_publisher | `robot_state_publisher::RobotStatePublisher` | robot_state_publisher | robot/robot_state_publisher.yaml + URDF | | no (latched `/robot_description`) |
| robot | tf2_ros | `tf2_ros::StaticTransformBroadcasterNode` | gnss_static_tf | robot/gnss_tf.yaml | | no (`/tf_static`) |
| sensors | ouster_ros | `ouster_ros::OusterDriver` | ouster / os_driver | sensors/ouster.yaml | | yes |
| sensors | zed_components | `stereolabs::ZedCamera` | zed2i / zed_node | sensors/zed2i.yaml | | yes |
| sensors | ublox_dgnss_node | `ublox_dgnss::UbloxDGNSSNode` | ublox_dgnss | sensors/ublox.yaml | | no (small) |
| sensors | ublox_nav_sat_fix_hp_node | `ublox_nav_sat_fix_hp::UbloxNavSatHpFixNode` | ublox_nav_sat_fix_hp | — | | no |
| sensors | microstrain_inertial_driver | MICROSTRAIN_PLUGIN | microstrain_inertial_driver | sensors/microstrain.yaml | | no (small) |
| mapping (rtabmap backend) | rtabmap_slam | `rtabmap_slam::CoreWrapper` | rtabmap / rtabmap | mapping/rtabmap.yaml | `scan_cloud:=/ouster/points`, `odom:=/odometry/slot` | no (latched `/rtabmap/map`) |
| nav2 | nav2_controller | `nav2_controller::ControllerServer` | controller_server | nav2_params.yaml § | `cmd_vel:=cmd_vel_nav` | no |
| nav2 | nav2_smoother | `nav2_smoother::SmootherServer` | smoother_server | § | | no |
| nav2 | nav2_planner | `nav2_planner::PlannerServer` | planner_server | § | | no |
| nav2 | nav2_behaviors | `behavior_server::BehaviorServer` | behavior_server | § | | no |
| nav2 | nav2_bt_navigator | `nav2_bt_navigator::BtNavigator` | bt_navigator | § | | no |
| nav2 | nav2_waypoint_follower | `nav2_waypoint_follower::WaypointFollower` | waypoint_follower | § | | no |
| nav2 | nav2_velocity_smoother | `nav2_velocity_smoother::VelocitySmoother` | velocity_smoother | § | `cmd_vel:=cmd_vel_nav`, `cmd_vel_smoothed:=cmd_vel` | no |
| nav2 | nav2_lifecycle_manager | `nav2_lifecycle_manager::LifecycleManager` | lifecycle_manager_navigation | § | | no |

§ = that node's section of `nav2/nav2_params.yaml`. Humble refuses intra-process on
publishers/subscriptions with transient-local durability, hence "no" on latched topics.
Nav2's costmaps subscribe to `/ouster/points` from child nodes that don't inherit the
component's intra-process setting, so those clouds still go through (in-process) DDS.
