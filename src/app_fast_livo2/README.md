# app_fast_livo2

ZED2i + Ouster + [FAST-LIVO2](https://github.com/hku-mars/FAST-LIVO2) (LiDAR-Inertial-Visual
Odometry) in one Docker container, built around ROS 2 composable nodes so the camera and
LiDAR drivers hand data to each other with **zero-copy intra-process** transport instead of
serializing across separate Docker services (which is what `app_zed2i_camera` +
`app_lidar_ouster_ros` + a downstream consumer do today, and what was causing freezes on
the Jetson under load).

**Extrinsics are not filled in yet** — see the TODOs in `config/zed2i_ouster.yaml`. This app
is set up to be ready the moment `app_fast_calib` produces a real calibration for this rig;
until then it will build and launch but won't fuse correctly.

## Why this shape

- **Base image**: `stereolabs/zed:5.1-devel-l4t-r36.4`, the same one `app_zed2i_camera` and
  `app_rtab_zed2i` use. It's the most particular image in this repo — Jetson L4T + CUDA +
  the ZED SDK baked in — so everything else (ROS 2, Ouster driver, FAST-LIVO2 and its
  dependency chain) is layered on top of it rather than the other way around.
- **FAST-LIVO2 fork**: [`Rhymer-Lcy/FAST-LIVO2-ROS2-MID360-Fisheye`](https://github.com/Rhymer-Lcy/FAST-LIVO2-ROS2-MID360-Fisheye)
  (vendored as the `FAST-LIVO2/` submodule). The official hku-mars repo is ROS 1 only.
  Picked over the other ROS 2 ports (`deepalcoholic/FAST-LIVO2_ROS2`,
  `VIS4ROB-lab/FAST-LIVO2-ROS2`) because it's the most active upstream (62 stars, pushed
  within the month at the time of writing) and — critically — it ships a ready-made
  `lidar_type: 3` (Ouster) config and launch example (`NTU_VIRAL.yaml` +
  `mapping_ouster_ntu.launch.py`) alongside its Livox/MID360 ones. `config/zed2i_ouster.yaml`
  and `launch/fast_livo2.launch.py` are adapted directly from that example.

## What's actually composable, and what isn't

Loaded into one `ComposableNodeContainer` (`fast_livo2_container`), same process,
intra-process zero-copy:

- **Ouster driver** — `ouster_ros::OusterDriver`, the single all-in-one component upstream
  recommends (see `ouster-ros`'s own `driver_params.yaml` comment: "consider migrating to
  combined node/component os_driver"). Publishes `/ouster/points`, `/ouster/imu` — same
  topics as the non-composed `app_lidar_ouster_ros`.
- **ZED2i driver** — joined into the same container via `zed_wrapper`'s own launch file and
  its `container_name`/`enable_ipc` args, exactly the trick `app_rtab_zed2i` already uses in
  this repo (`launch/rtab_zed2i.launch.py`).

**Not composable: FAST-LIVO2 itself.** Its `fastlivo_mapping` executable runs its own
`while (rclcpp::ok()) { rclcpp::spin_some(...) }` loop inside `LIVMapper::run()` instead of
handing control to an external executor — that's fundamentally incompatible with being
loaded as an `rclcpp_components` plugin into a container that also has to service the ZED
and Ouster callbacks. It runs as a normal ROS 2 node, in the same Docker container, talking
to the composed nodes over a regular (same-host) DDS hop rather than intra-process
zero-copy. Turning it into a real composable node means rewriting that loop into a
timer/executor-driven callback in the upstream fork — a real code change to someone else's
core estimation loop, which isn't something to do speculatively without hardware to
validate it against. Tracked as follow-up work once the rest of this is proven out.

So: the serialize/deserialize overhead between the camera and LiDAR drivers is gone. The
overhead between those drivers and FAST-LIVO2's fusion step is reduced (one Docker
container instead of three, one DDS domain hop instead of crossing container network
namespaces) but not eliminated.

## The Livox dependency you don't actually need

FAST-LIVO2's `CMakeLists.txt`/`package.xml` unconditionally `find_package(livox_ros_driver2
REQUIRED)`, even though we run with `preprocess.lidar_type: 3` (Ouster,
`sensor_msgs/PointCloud2`) and never touch the Livox `CustomMsg` code path. There's no
Livox hardware involved — `livox_ros_driver2` and its C-library prerequisite
`Livox-SDK2` are pulled in purely to satisfy the build, then never exercised at runtime.
Same pattern `app_fast_calib` already uses for its own (ROS 1) Livox dependency.

Both are baked into the image (`Dockerfile`) rather than mounted, because
`livox_ros_driver2`'s own `build.sh` deletes `build/`, `install/`, and `devel/` in its
*parent* workspace — destructive if run against the shared `/workspace` this app actually
builds (FAST-LIVO2, vikit, `ouster_ros`, `zed_wrapper`). It's built once, in its own
throwaway workspace at `/opt/ws_livox`, and that workspace's `install/setup.bash` is
sourced ahead of the real build in `postcreatecommand.sh`.

## Filling in the extrinsics

Two separate transforms, both currently identity/zero placeholders in
`config/zed2i_ouster.yaml`:

- **`Rcl`/`Pcl` (camera ← LiDAR)**: run `app_fast_calib` on *this rig's* own board scans and
  photos, and copy its output in. Do not reuse the numbers recorded in
  `app_fast_calib/README.md` — those came from hku-mars's sample dataset, run only to prove
  the calibration pipeline itself works end to end, not a calibration of this hardware.
- **`extrinsic_T`/`extrinsic_R` (IMU ← LiDAR)**: internal to the Ouster unit, small and
  fixed. Pull the real value from the sensor's own metadata
  (`imu_to_sensor_transform`) once it's connected, rather than guessing.

Also check `config/camera_zed2i.yaml` — the pinhole intrinsics are zeroed placeholders;
read the real ones off `/zed2i/zed_node/rgb/color/rect/camera_info` once the camera is
connected, and set `preprocess.scan_line` in `config/zed2i_ouster.yaml` to the real Ouster
channel count.

## Using the docker container

```bash
cd app_fast_livo2
docker compose build
docker compose up -d
docker compose exec app_fast_livo2 bash
ros2 launch app_fast_livo2 fast_livo2.launch.py
```

Or from the repo's top-level `docker-compose.yaml` (service is present but defaults to
`tail -f /dev/null` until the extrinsics above are real — swap in the commented `command:`
when ready). Don't run this alongside `app_zed2i_camera`, `app_lidar_ouster_ros`, or
`app_rtab_zed2i` — they all drive the same physical camera and LiDAR.
