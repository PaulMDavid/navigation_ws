# rover_arming

Tests `app_teleop/rover_arming.py`: the node that sends robot_control's mode switches
as `/joy` presses and tracks its state on `/teleop/rover_state`. No robot involved.

- `test_tracker.py`: unit tests of `rover_tracker.py` (plain Python, fake clock). Press
  sequencing (1 → 16 → 2, each press followed by an all-zero Joy, `press_gap` apart),
  idempotent `steer_*`, `arm` skipping 16 when already Ackermann, queued commands not
  interleaving, source gating, `reset`, queue limit, the JSON fields.
- `test_node.py`: the real `teleop_mux.py` + `rover_arming.py` on loopback DDS
  (domain 77 = robot, 79 = phone, as in `utils/teleop_link`). Checks the `/joy`
  messages (8 axes, 17 buttons, gaps), `/teleop/rover_state` in both domains at 2–5 Hz,
  a ground command refused while the phone is the source and accepted after
  `source` switches to ground, and teleop_mux's `max_angular` following the tracked
  steering (1.0 Ackermann, 0.1 crab, 0.1 after `reset`).

Not covered: robot_control itself. Whether the rover reacts to these presses as to
hand-published ones is the hardware checklist in `app_teleop/README.md`.

## Run

```bash
systemd-run --user --scope -p MemoryMax=8G ./run.sh       # all (≈25 s after the image is built)
./run.sh unit                                              # rover_tracker.py only
```

Runs in a `ros:humble-ros-base` container (2 GB cap); the host needs no ROS.
Output goes to `results/<date>_pytest.txt`.

## Last results

**2026-11-14: 26/26 PASS** (19 unit, 7 ROS), three runs in a row, ≈24 s each.
`results/2026-11-14_pytest.txt`.
