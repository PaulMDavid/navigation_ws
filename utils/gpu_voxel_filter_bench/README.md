# gpu_voxel_filter_bench

Times `src/gpu_voxel_filter` (CUDA voxel grid) against PCL's CPU `VoxelGrid` on the same
Ouster clouds from a bag, read directly (no playback-rate limit), and checks both give
the same number of points.

## Run (on orintwo)

    utils/gpu_voxel_filter_bench/run.sh [bag_dir] [clouds] [leaf]

Defaults: `/mnt/ssd/rtabmap_database/lab_bag_Jun22`, 300 clouds, 0.1 m leaf, 0.3–50 m
crop. Builds into `/mnt/ssd/pdavid/gvf_ws`, holds `/mnt/ssd/pdavid/.build.lock` for the
whole run, and caps the container at 8 GB.

## Last result

2026-10-24, orintwo at 30 W, 131072 points/cloud → 13490 on both paths:

| path | mean ms | p95 ms |
|---|---|---|
| GPU, including host↔device copies | 7.00 | 7.20 |
| CPU crop + VoxelGrid | 4.33 | 4.95 |
| CPU PointCloud2 → PCL conversion | 2.48 | 3.12 |

The GPU path is no faster than the CPU path (7.0 vs 6.8 ms). The copies dominate on a
cloud this small. What it does buy is moving ~7 % of one core (at 10 Hz) off the CPU;
downsampling before ICP and the costmaps is the real saving, wherever it runs.
