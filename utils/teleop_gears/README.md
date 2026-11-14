# teleop_gears

Tests for the phone's gear driving (#37): `src/app_teleop/teleop_drive.py` and its use in
`teleop_mux.py`. No robot needed.

- `test_drive.py`: gears, speed ramp, κ_max, lateral-acceleration bound, steer rate limit,
  `max_angular` clamp, reversing. Pure Python, fake time.
  `uvx --with pytest pytest -q utils/teleop_gears/test_drive.py`
- `test_mux_ros.py` via `run_mux_test.sh`: starts the real `teleop_mux` (teleop.yaml,
  source phone) in the `phonetest-app_teleop` image on loopback DDS, publishes
  `/teleop/phone/{set_mode,gear,stick}` in the phone domain like the app, checks
  `/cmd_vel` and `/teleop/state`: gear 1 and gear 4 top speed, the a_lat bound at 0.8 m/s
  (ω = 0.5/0.8 = 0.625 with `max_angular` 1.0), `angular_sign` −1 flips ω, deadman zeroes,
  STOP resets the gear. `IMAGE=...` overrides the image.

## Results

- 2026-11-21: `test_drive.py` 68 passed. `run_mux_test.sh` ALL PASS (11 checks): vx 0.150
  in gear 1, 0.800 in gear 4, ω +0.625 / −0.625 with `angular_sign` +1 / −1, zero after
  the stick stops. Not yet driven on the rover.
