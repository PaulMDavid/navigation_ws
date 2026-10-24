# navigation_ws

Autonomous navigation stack for the TU Berlin rover, built for the European Rover
Challenge 2025/26. ROS 2 Humble, containerised per subsystem with Docker Compose.

Each navigation subsystem is an independent ROS 2 package with its own Dockerfile and
Compose service, so sensors, SLAM, and planning can be brought up in isolation while
testing, or together on the rover.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full topic graph, the transform tree, and
how the SLAM back-end is swapped without touching anything downstream.

## Packages

| Package | Role |
| --- | --- |
| `app_zed2i_camera` | ZED 2i stereo camera driver (Stereolabs ROS 2 wrapper) |
| `app_lidar_ouster_ros` | Ouster LiDAR driver and rover-specific config |
| `app_microstrain` | MicroStrain IMU driver |
| `app_rtab_map` | RTAB-Map RGB-D SLAM — produces map and odometry |
| `app_rtab_zed2i` | Combined RTAB-Map + ZED 2i composable launch (single-process, lower latency) |
| `app_LIO_SAM` | LiDAR-inertial odometry and mapping (`li_slam_ros2`) |
| `app_robot_localization` | EKF sensor fusion (`robot_localization`) |
| `app_nav2` | Nav2 planning and control — consumes map + odom from SLAM |
| `app_robot_state_publisher` | Rover URDF, TF tree, joint states |
| `app_aruco_detector` | ArUco marker detection with pose and distance estimation |
| `app_zenoh_bridge` | Zenoh bridge for links over unreliable WiFi (ground station ↔ robot) |
| `app_teleop` | Decides what reaches `/cmd_vel`: Nav2, an operator (ground PC or phone), or nothing; deadman |
| `app_foxglove_bridge` | The phone's link (Foxglove WebSocket), isolated in its own DDS domain |
| `app_teleop_phone` | Android teleop app (Flutter, submodule), served to the phone as an APK |
| `app_template` | Scaffold for new navigation subsystems |

### Ground station

These run on the operator's desktop, not the rover, and subscribe to the same topics
over the network. Both forward X11 so RViz2 opens a window on your machine.

| Package | Role |
| --- | --- |
| `ground_station/rtabmap_viz` | RTAB-Map map and graph viewer |
| `ground_station/nav2_viz` | RViz2 with the Nav2 displays |

They use host networking so CycloneDDS discovery can reach the Jetson directly. Set
`ROS_DOMAIN_ID` to match the rover side or you will see an empty RViz and no error.

## Requirements

- Docker and Docker Compose
- A ROS 2 Humble host if you intend to run nodes outside containers
- All services use `network_mode: host` — expect direct access to host network
  interfaces, and ensure your `ROS_DOMAIN_ID` does not collide on a shared network

## Getting started

```bash
git clone --recurse-submodules https://github.com/PaulMDavid/navigation_ws.git
cd navigation_ws/src
```

If you cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

Bring up a single subsystem:

```bash
docker compose up app_rtab_map
```

Or the full stack:

```bash
docker compose up
```

Simulation and camera-only variants have their own Compose files:

```bash
docker compose -f docker-compose.simulation.yaml up
docker compose -f docker-compose.rtabmap_camera.yaml up
```

## Submodules

| Path | Upstream |
| --- | --- |
| `src/app_lidar_ouster_ros` | [PaulMDavid/ouster-ros-erc25](https://github.com/PaulMDavid/ouster-ros-erc25) |
| `src/app_zed2i_camera/zed-ros2-wrapper` | [PaulMDavid/zed-ros2-wrapper-erc](https://github.com/PaulMDavid/zed-ros2-wrapper-erc) |
| `src/app_robot_localization/robot_localization_erc26` | [PaulMDavid/robot_localization_erc26](https://github.com/PaulMDavid/robot_localization_erc26) |
| `src/app_LIO_SAM/li_slam_ros2` | [rsasaki0109/li_slam_ros2](https://github.com/rsasaki0109/li_slam_ros2) |

## Used as a submodule

The TU Berlin rover monorepo mounts this repository as a submodule at
`navigation_ws/navigation_stack`. A submodule records one fixed commit, so pushing here
does **not** update that repo — someone has to bump the pin:

```bash
cd navigation_ws/navigation_stack
git checkout main && git pull      # submodules check out detached; do this first
cd ../..
git add navigation_ws/navigation_stack
git commit -m "chore: bump navigation_stack submodule"
git push
```

Working from the monorepo instead? `git submodule update --init --recursive` after
pulling, or the directory stays empty.

## Repository history

This workspace was extracted from the TU Berlin rover team's internal GitLab monorepo
(`git.tu-berlin.de/rover/erc25`), preserving the original commits, authors, and dates
from November 2025 onward.

Paths changed during extraction: what was `navigation_ws/src/<pkg>` in the monorepo is
`src/<pkg>` here.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md). 