# perf_compare: baseline-replay

2026-10-24, 60 s

## System (tegrastats)

CPU avg 34.8 % · RAM 4721 MB · GPU 0.0 % · power 9.0 W

## Containers (docker stats, mean)

| container | CPU % | memory MiB |
|---|---|---|
| app_bringup_manager_container | 6.7 | 37 |
| app_nav2_container | 68.8 | 303 |
| app_odom_relay_container | 1.5 | 34 |
| app_robot_state_publisher_container | 0.1 | 35 |
| app_rtab_map_container | 64.5 | 474 |
| bag_replay_player | 18.1 | 696 |
| bag_replay_restamp | 38.4 | 62 |
| determined_blackburn | 20.9 | 48 |

## Topics

| topic | Hz | latency p50 ms | latency p95 ms |
|---|---|---|---|
| /ouster/points | 4.8 | 57.2 | 65.2 |
| /ouster/imu | 82.5 | 0.6 | 7.6 |
| /rtabmap/odom_reliable | 4.5 | 100.4 | 127.0 |
| /rtabmap/map | 0.0 | — | — |
| /local_costmap/costmap | 1.7 | — | — |
