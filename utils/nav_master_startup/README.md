# nav_master_startup

First start of `app_nav_master` on orintwo. The container compiles the mounted sources
(Ouster, ZED wrapper, li_slam, gpu_voxel_filter); then the test checks that every
component plugin `stages_master.yaml` loads is registered. It records the build time,
the container's peak memory and the host's lowest MemAvailable, and runs the
`odom_rate_hang` logger so a freeze leaves a record.

## Run (on orintwo)

    utils/nav_master_startup/run.sh [--fresh]

`--fresh` deletes the build/install volumes first, which is the worst case. Holds
`/mnt/ssd/pdavid/.build.lock`.

## Last result

2026-10-24, `--fresh`, orintwo at 30 W: **PASS**. All 14 plugins registered (plus the
u-blox ones); microstrain registers no component.

| build settings | time | container peak | host MemAvailable low | result |
|---|---|---|---|---|
| colcon default (8 packages × 8 jobs) | 380 s | 16.3 GB (at the 16 GB limit) | 11.6 GB | scanmatcher OOM-killed |
| 1 package × 2 jobs (current `entrypoint.sh`) | 1125 s | 7.4 GB | 20.5 GB | all 10 packages built |

The first row is what ran before `entrypoint.sh` was mounted into the container (the
image had a copy of the old, unlimited one). The limit killed the build, not the Jetson.
