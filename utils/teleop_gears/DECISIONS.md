# teleop_gears — WIP status (stopped 2026-11-14 late, agent force-stopped)

Work in progress for #37 (mux part). The agent was stopped before it wrote its own
decision list, so this file only records what is known; read the diff for details.

## State
- Changed: `src/app_teleop/teleop_mux.py`, `config/teleop.yaml`,
  `src/app_foxglove_bridge/config/foxglove_bridge.yaml`; new `src/app_teleop/teleop_drive.py`
  (pure-Python core for gears / ramp / curvature limit, per the issue's plan).
- Tests: the agent had just started writing unit tests. **Not run; nothing verified.**
- No PR opened. README section "Gears and speed-dependent steering" probably not written.

## Decisions fixed by the user / the issue
- Spec = issue #37 (gears 0.15/0.30/0.50/0.80 m/s, a_lat_max 0.5, accel 0.3, decel 0.5,
  min_turn_radius 1.0 placeholder, steer_rate 2.0/s, gear → 1 on boot/stop/source change,
  upshift allowed mid-turn, max_angular stays final clamp, km/h from /odom_wheels).
- The app will **not** fall back to old cmd_vel driving (user, 2026-11-14): orintwo must
  run this mux before app 1.7 drives.

## Next
1. Check the diff against the issue, finish tests in this folder, run them.
2. README contract section, PR "[UNTESTED]" refs #37 (don't close it).
