# li_slam odometry (and optional graph backend)

[li_slam_ros2](../../../../app_LIO_SAM/li_slam_ros2) on its `composable` branch, where
all four nodes are rclcpp components. Everything runs in namespace `lio`.

## Components

| Node | Package | Plugin | Params | Remaps |
| --- | --- | --- | --- | --- |
| `image_projection` | `scanmatcher` | `ImageProjection` | `lidar_imu.yaml` | — |
| `imu_preintegration` | `scanmatcher` | `IMUPreintegration` | `lidar_imu.yaml` | `odometry` → `odom` |
| `scan_matcher` | `scanmatcher` | `graphslam::ScanMatcherComponent` | `scanmatcher.yaml` | `input_cloud` → `cloud_deskewed` |
| `graph_based_slam` *(optional)* | `graph_based_slam` | `graphslam::GraphBasedSlamComponent` | `graph_based_slam.yaml` | — |
| `lio_base_to_chassis` | `tf2_ros` | `tf2_ros::StaticTransformBroadcasterNode` | `lio_base_to_chassis.yaml` | — |
| `map_to_odom` *(with graph backend)* | `tf2_ros` | `tf2_ros::StaticTransformBroadcasterNode` | `map_to_odom.yaml` | — |

Data flow: `/ouster/points` + `/ouster/imu` → `image_projection` → `/lio/cloud_deskewed`
→ `scan_matcher` → `/lio/odom` → `imu_preintegration` → `/lio/preintegrated_odom` → back
into `image_projection` (deskew) and `scan_matcher` (initial guess).

## Output contract

- **TF** `odom → base_link → chassis_link`. `base_link` is li_slam's lidar pose
  (= `os_sensor`), and the static `base_link → chassis_link` is the URDF lidar mount
  inverted. Consumers look up `odom → chassis_link` through it.
- **Odometry** `/lio/odom`, `nav_msgs/Odometry`, **RELIABLE**, keep-last 1. Its pose is
  the lidar's, its `child_frame_id` is empty, and its twist comes from IMU preintegration.
  Use it for velocity, as Nav2 does, but take poses from TF: in rtabmap set
  `odom_frame_id: odom` rather than subscribing to the topic.
- **Map** (graph backend) `/lio/modified_map`, `sensor_msgs/PointCloud2` in `map`, not an
  occupancy grid. That's the architectural gap in ARCHITECTURE.md, left open on purpose.

## Requirements on the Ouster driver

- `point_cloud_frame: os_sensor`. li_slam assumes its robot frame is the lidar. With the
  default `os_lidar` (rotated 180° about z) the IMU extrinsic would be a yaw flip and
  `/lio/odom`'s velocities would point backwards relative to the chassis.
- `point_type: original` (the default), which carries `ring` and `t`.
- Any QoS works: the cloud and IMU subscriptions are best-effort.

## Things to know

- **graph_based_slam publishes no TF.** Its loop closures only correct `/lio/modified_map`
  and `/lio/modified_path`, so with li_slam as the map backend `map → odom` is a static
  identity (`map_to_odom.yaml`) and drift is never corrected in TF. Owning `map → odom`
  would mean adding code to graph_based_slam.
- **image_projection drops every point closer than 1 m** (hard-coded), and stamps deskewed
  clouds `base_link` (hard-coded). That's why `scan_matcher`'s `robot_frame_id` must stay
  `base_link`.
- The IMU noise values are upstream defaults, not identified for this unit.
- The `base_link velodyne` static TF in upstream's `lio.launch.py` isn't needed: our clouds
  are never in a `velodyne` frame.
