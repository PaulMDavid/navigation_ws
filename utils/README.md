# utils

Every test, benchmark and harness, one folder each, with a README covering what it
measures, how to run it, and the last dated result.

| folder | what |
|---|---|
| `bag_replay/` | replays a bag with fresh stamps in place of the Ouster |
| `build_memory_cap/` | laptop Docker builds can't exhaust host RAM |
| `gpu_voxel_filter_bench/` | GPU vs CPU voxel downsampling on Ouster clouds |
| `manager_component_loading/` | bringup manager loads/unloads components into a container |
| `nav_master_startup/` | app_nav_master first start: build, memory, plugins present |
| `odom_rate_hang/` | reproduce the freeze at higher odometry rates, freeze-proof logging |
| `perf_compare/` | CPU/RAM/GPU/power and topic rates of a running stack |
| `teleop_link/` | teleop modes, deadman, both operator links, with the laptop as orintwo |
