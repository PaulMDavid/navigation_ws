# navigation_ws

Autonomous navigation stack for the TU Berlin rover, built for the European Rover
Challenge 2025/26. ROS 2 Humble, containerised per subsystem with Docker Compose.

Each navigation subsystem is an independent ROS 2 package with its own Dockerfile and
Compose service, so sensors, SLAM, and planning can be brought up in isolation while
testing, or together on the rover.

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
| `app_zenoh_bridge` | Zenoh bridge for links over unreliable WiFi |
| `app_template` | Scaffold for new navigation subsystems |

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

## Repository history

This workspace was extracted from the TU Berlin rover team's internal GitLab monorepo
(`git.tu-berlin.de/rover/erc25`), preserving the original commits, authors, and dates
from November 2025 onward. Only the navigation packages were carried over; other rover
subsystems remain in the internal repository.

Paths changed during extraction: what was `navigation_ws/src/<pkg>` in the monorepo is
`src/<pkg>` here.

## Contributors

See [CONTRIBUTORS.md](CONTRIBUTORS.md). This stack is the work of several people on the
TU Berlin rover team, not one person.
