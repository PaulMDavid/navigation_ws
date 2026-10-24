# perf_compare

How much a running stack costs and how fast its data moves, so different stacks can be
compared on the same scenario. Built for "does the all-in-one composable container
(`app_nav_master`) beat the separate containers?"

## What it measures

Over `SECONDS` (default 120), with the stack under test already running:

- **System:** CPU (mean over online cores), RAM, GPU and power from `tegrastats`
- **Containers:** mean CPU % and memory per container from `docker stats`
- **Topics** (`topics.txt`): rate, and latency = receive time − `header.stamp` (p50/p95)
  for topics that have a header. The stamp is read from the serialized bytes, so the
  probe doesn't deserialize 2.6 MB clouds. Latched topics (the map) get a rate only.

With the bag replay standing in for the lidar, the clouds are stamped when the
restamper republishes them, so the odometry latency includes processing and the DDS
hops after that point, not the sensor's own delay. Fine for comparing stacks; label such
runs `-replay`.

## Running it

On orintwo, from this folder in the synced copy:

```bash
./perf_compare.sh baseline-replay 120
```

Results land in `results/` and as a row below **on the robot copy**. Pull them back to
the laptop before the next `scripts/sync_to_robot.sh` (which would delete them):

```bash
rsync -a orintwo:/mnt/ssd/pdavid/navigation_ws/utils/perf_compare/{README.md,results} utils/perf_compare/
```

## Results

| date | label | s | CPU % | RAM MB | GPU % | power W | points Hz | odom Hz | odom latency p50 / p95 ms | costmap Hz | details |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-24 | baseline-replay | 60 | 34.8 | 4721 | 0.0 | 9.0 | 4.8 | 4.5 | 100.4 / 127.0 | 1.7 | [2026-10-24-baseline-replay.md](results/2026-10-24-baseline-replay.md) |
<!-- perf_compare rows above -->
