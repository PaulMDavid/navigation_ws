# nav_relay

Tests `app_teleop/nav_relay.py`, the backend of the phone app's Autonav page (#30):
`/teleop/phone/nav_cmd` → Nav2 / bringup manager, and the map, pose, plan and Nav2 state
to the phone. Message formats: `app_teleop/README.md`, "Autonav relay". No robot involved.

- `test_core.py`: unit tests of `nav_relay_core.py` (plain Python). nav_cmd parsing and
  every refusal, yaw ↔ quaternion (CCW from +x), map downsampling (size limit, block
  rule occupied > free > unknown, padding, thresholds, row flip), PNG round trip,
  plan thinning (≤ 200, ends kept), the compact `/bringup/status` copy.
- `test_node.py`: the real `teleop_mux.py` + `nav_relay.py` on loopback DDS, domains
  **81 = robot, 83 = phone** (not 0/51, which the laptop's stand-in phone stack uses, and
  not 77/79 of the other tests). Fakes in the main domain: a latched `/rtabmap/map`
  (2500×1800 at 0.05 m), TF `map → chassis_link`, `/plan` with 1000 poses, a
  `NavigateToPose` server on `/navigate_to_pose` (feedback, succeeds after 2 s, aborts
  x < 0, accepts cancel), `/bringup/go|stop` and a latched `/bringup/status` with logs.
  Checks: state in both domains at 4–6.5 Hz and its exact key set; pose from TF; plan
  thinned to 200; bringup copy without logs; map meta + PNG (834×600, ×3, 0.15 m,
  pixels equal to the expected downsampling, a known wall at the right row); the map
  latched for a late subscriber; an unchanged map not re-sent; a map changing at 5 Hz
  sent ≤ 0.5 Hz with the newest one left latched; goal → Nav2 gets the pose (map frame,
  yaw → quaternion), feedback, succeeded; cancel → canceled; abort; refusals (no goal
  to cancel, bad JSON, missing yaw); bringup_go/stop call the services and the reply
  shows; with the mux source switched to ground, goal / bringup_go / cancel are refused
  and nothing reaches Nav2 or the manager.
- `bench_map.py`: time of the map work (downsample + PNG) for some map sizes.

Not covered: the real rtabmap / Nav2 / bringup manager, foxglove_bridge and the app.
That is the hardware checklist in `app_teleop/README.md`.

## Run

```bash
systemd-run --user --scope -p MemoryMax=8G ./run.sh         # all (≈30 s after the image is built)
./run.sh unit                                                # nav_relay_core.py only
./run.sh bench                                               # bench_map.py
```

Runs in a `ros:humble-ros-base` container (+ `ros-humble-nav2-msgs`, `python3-opencv`;
2 GB cap); the host needs no ROS. Output goes to `results/<date>_pytest.txt` /
`results/<date>_bench_map.txt`.

## Last results

**2026-11-14: 45/45 PASS** (31 unit, 14 ROS), three runs in a row, ≈29 s each.
`results/2026-11-14_pytest.txt`.

Map bench, 2026-11-14, laptop, random 3 % obstacles (worst case for PNG):

| map | sent as | PNG | time |
| --- | --- | --- | --- |
| 800×600 | 800×600 (×1) | 24 KiB | 9 ms |
| 2000×2000 | 1000×1000 (×2) | 102 KiB | 77 ms |
| 2500×1800 | 834×600 (×3) | 66 KiB | 57 ms |
| 4000×4000 | 1000×1000 (×4) | 139 KiB | 145 ms |

At most once per 2 s (`map_max_rate` 0.5 Hz). orintwo not measured.
