# app_bringup_manager

Brings the Nav2 stack up in order, one stage at a time, and reports what is
wrong and where. The ground station panel (`groundstation_navigation`) is its
front end; the big red button calls `/bringup/go`.

## Stages

Defined in [`stages.yaml`](stages.yaml). A stage starts only after every earlier
stage passed its checks, never after a fixed sleep; it fails when its timeout
runs out first, or immediately if one of its containers exits.

| Stage | Services | Ready when |
| --- | --- | --- |
| Preflight | — | `/mnt/ssd` is really mounted; DDS config present |
| Robot model | `app_robot_state_publisher` | `/robot_description`; TF `chassis_link → os_sensor` |
| Ouster lidar | `app_lidar_ouster_ros` | lidar answers ping first; `/ouster/points` ≥ 8 Hz, `/ouster/imu` ≥ 50 Hz, TF `os_sensor → os_lidar` |
| SLAM | `app_rtab_map`, `app_odom_relay` | `/rtabmap/odom` and `/rtabmap/odom_reliable` ≥ 5 Hz, `/rtabmap/map`, TF `map → chassis_link` < 1 s old |
| Nav2 | `app_nav2` | lifecycle manager active; local costmap ≥ 1 Hz |
| Rover link (optional) | — | rover pings; `/cmd_vel` has a subscriber; app_teleop takes `/cmd_vel_auto` |

After everything is up, the checks keep running every couple of seconds. A stage
that fails three sweeps in a row turns red, with the reason and its container logs.

**`/bringup/go`** starts from the first required stage that isn't ready: stages
before it stay up, everything from it onwards is stopped and started again.
Note that restarting SLAM wipes the map (`--delete_db_on_start`).

## Composable nodes

A stages file can name a component container (`container:`) and give stages a
`components:` list instead of, or as well as, `services:`. Each entry is loaded through
the container's `load_node` service, with parameters flattened from its YAML file under
`config_dir`, and unloaded on stop or recover, so a failed stage reloads only its own
nodes while the process keeps running:

```yaml
container: /nav_master_container
config_dir: app_nav_master/config
stages:
  - name: lidar
    components:
      - {package: ouster_ros, plugin: ouster_ros::OusterDriver, name: os_driver,
         namespace: ouster, params: sensors/ouster.yaml, intra_process: true,
         remaps: {/ouster/points: /ouster/points}}
```

`file_params: {param: path under src/}` sets a string parameter to a file's contents
(robot_state_publisher's `robot_description` from the URDF). A `node` check
(`{type: node, node: /nav_master_container}`) waits for a node to appear, which is how
the container stage waits out the first-start compile.

Every component also gets an implicit check that its node is in the graph. Pick the
stages file with `BRINGUP_STAGES` (default `stages.yaml`, the separate-container stack):

```bash
BRINGUP_STAGES=stages_master.yaml docker compose -p navbringup up -d app_bringup_manager
```

Tested in `utils/manager_component_loading/`.

## Running it

On the robot, from `src/`, once:

```bash
docker compose -p navbringup build app_bringup_manager app_robot_state_publisher \
    app_lidar_ouster_ros app_rtab_map app_odom_relay app_nav2
docker compose -p navbringup up -d app_bringup_manager
```

`restart: unless-stopped` brings it back after every reboot. It drives the other
services through the host's Docker socket, under its own compose project, so a
second checkout of this repo on the same machine (project `src`) is left alone.
Container names are fixed, though: if the other copy has one of them **running**,
the stage fails and says so; **stopped** leftovers are removed.

Images are never built by the manager (`--no-build`); rebuild by hand after
changing a Dockerfile.

## Interface

| Name | Type | |
| --- | --- | --- |
| `/bringup/go` | `std_srvs/Trigger` | bring up / recover |
| `/bringup/stop` | `std_srvs/Trigger` | stop all stages, last first |
| `/bringup/status` | `std_msgs/String` (JSON, transient local, 1 Hz) | stages, checks, containers, logs at failure, events |
| `/bringup/log_request` → `/bringup/logs` | `std_msgs/String` | container name → last 200 log lines |

From any ROS 2 shell on the network:

```bash
ros2 service call /bringup/go std_srvs/srv/Trigger
ros2 topic echo --once /bringup/status | head
```
