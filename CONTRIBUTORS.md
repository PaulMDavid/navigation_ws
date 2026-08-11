# Contributors

This navigation stack was developed by members of the TU Berlin rover team for the
European Rover Challenge 2025/26. Commit counts below are from this repository's
history; the authorship and dates are the originals, carried over unchanged from the
team's internal GitLab monorepo.

## Paul Mangalam David — 101 commits, Nov 2025 – Aug 2026

Navigation stack architecture and the majority of implementation: the containerised
per-subsystem layout, RTAB-Map SLAM integration, Nav2 bringup, robot_localization EKF
fusion, LIO-SAM integration, ZED 2i and Ouster driver packaging, robot state publisher
and URDF/TF work, ArUco detection, Zenoh bridging, and simulation support.

Commits appear under four addresses used over the project's lifetime: `pdavid`
(`pdavid@atb-potsdam.de`), `paulmdavid95` (`paulmangalam@proton.me`),
`Paul Mangalam David` (`p.david@campus.tu-berlin.de`), and `pdavid`
(`paulmdavid95@gmail.com`).

## Patrick Ugwu — 16 commits, May – Jul 2026

RTAB-Map and ZED 2i camera integration, including the composable-node launch path in
`app_rtab_zed2i` that runs SLAM and the camera driver in a single process. Also QoS
tuning and camera topic work across `app_zed2i_camera` and `app_lidar_ouster_ros`.

## Antonio Aristizabal (`wantuto`) — 5 commits, Jan 2026

Initial LiDAR integration: Ouster Docker setup and configuration, plus the Foxglove
bridge used for remote visualisation during testing.

## M. Sutarto (`tarto89`) — 4 commits, Jan – Mar 2026

ZED 2i container bring-up and validation, camera parameter adjustments, rosbag mounting
for offline testing, and ArUco detector fixes for compressed image and `camera_info`
handling.

## Taha Mahmoud Mousa Mohammed — 1 commit, Jul 2026

EKF bring-up integration into the navigation branch.

---

## Upstream projects

This stack builds on substantial open-source work:

- [RTAB-Map](https://github.com/introlab/rtabmap_ros) — RGB-D SLAM
- [Nav2](https://github.com/ros-navigation/navigation2) — navigation framework
- [robot_localization](https://github.com/cra-ros-pkg/robot_localization) — EKF state estimation
- [li_slam_ros2](https://github.com/rsasaki0109/li_slam_ros2) — LiDAR-inertial SLAM
- [zed-ros2-wrapper](https://github.com/stereolabs/zed-ros2-wrapper) — Stereolabs ZED driver
- [ouster-ros](https://github.com/ouster-lidar/ouster-ros) — Ouster LiDAR driver
- [Zenoh](https://github.com/eclipse-zenoh/zenoh) — network middleware
