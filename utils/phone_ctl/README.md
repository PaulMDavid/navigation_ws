# phone_ctl

Tests the phone one-button bring-up (issue #27): `scripts/phone_ctl.sh` on orintwo,
`scripts/robot_setup/rover/rover_wheels_ctl.sh` + `rover_wheels_run.sh` (the
`rover-wheels.service` runner) on the rover, and `src/app_teleop/phone_probe.py` (the ROS
checks phone_ctl runs inside `app_teleop_container`). No robot involved.

- `test_phone_ctl.py`: the whole chain with fakes (`fakes/`) for ssh, docker, ping,
  mountpoint, df, systemctl, ros2 and mdtool. The fake ssh runs the real
  `rover_wheels_ctl.sh` as the restricted key would (`SSH_ORIGINAL_COMMAND`); its fake
  `systemctl --user` runs the real `rover_wheels_run.sh`; the fake `ros2 launch` holds a
  fake `/dev/ttyACM0` open and prints candle's MD80 lines. Covers:
  - every output line is JSON with `step/state/reason/t`, `t` rising, final `{"done", "ok"}`;
  - `up` all green; stop at the first failing step (preflight, ping, ssh, compose,
    wrong teleop source), later steps `skipped`, nothing started after the failure;
  - `/` at 95–99 % = warn and `up` goes on, 100 % = fail;
  - MD80 retry: `Failed to add MD80 with ID: 12` once → launch stopped, `mdtool encoder 12`
    only after the port is free and `MDTOOL_GAP` apart, relaunch, green, `retry 1/3` line;
    always failing → gives up after 3 retries (4 launches) with the id;
  - no "Added MD80" lines = warn; launch crash = fail; `start` refused while another
    process holds the port (the old tmux session);
  - `up` twice leaves running wheels alone and sends no `reset`;
  - `zero 14 11`: stop → zero/save 14 → zero/save 11 → start, gaps ≥ `MDTOOL_GAP`, mdtool
    never while the port is held, then wheels check + `reset`; a failing mdtool call stops
    the sequence but the wheels service is started again;
  - `SSH_ORIGINAL_COMMAND` parsing on both scripts: anything but the verbs, ids outside
    11–14, extra arguments, shell metacharacters are refused (exit 64) and nothing runs;
    commas and duplicate ids accepted;
  - `status` starts nothing; `stop` order and best effort; `camera` ok / warn (low rate) /
    fail; `log` lines escaped (quotes, backslash, tab, ANSI); lock (`busy`).
- `test_probe.py`: `phone_probe.py` against the real `teleop_mux.py` + `rover_arming.py`
  on loopback DDS (domain 77 = robot, 79 = phone): `mux_source`, `subs`, `rover_cmd arm`
  then `reset` (sent as the active source, confirmed on `/teleop/rover_state`), a refused
  command, `rate` of `/teleop/camera/compressed` in the phone domain (~10 Hz fed), no mux.

Not covered: real ssh/sshd forced commands, systemd user units and linger, the real
morpheus_control / candle log text, mdtool, the hotspot and `orintwo.local`. That is the
hardware checklist in `src/app_teleop/README.md`.

## Run

```bash
systemd-run --user --scope -p MemoryMax=8G ./run.sh       # all (≈2 min after the image is built)
./run.sh shell                                             # fakes only
./run.sh probe                                             # ROS probe only
./run.sh test_phone_ctl.py -k zero                         # any pytest args
```

Runs in a `ros:humble-ros-base` container (2 GB cap); the host needs no ROS.
Output goes to `results/<date>_pytest.txt`.

## Last results

**2026-11-24 (2): 69/69 PASS** after two orintwo findings: the camera step starts
`app_robot_state_publisher` (the ZED waited for static TF forever), and the `rate` probe
subscribes best-effort (the relay is best-effort, so a reliable probe never got a frame;
`test_probe.py` now publishes best-effort too). On orintwo: probe `ok 10.1` Hz, `status`
all green with 8 MD80s added.

**2026-11-24: 69/69 PASS** after the rover DDS fix (#49): the fake launch now checks the
wheels see `rmw_cyclonedds_cpp`, domain 0 and `cyclonedds_rover.xml`. 109 s.
`results/2026-11-24_pytest.txt`. The XML itself was checked on the rover: `ros2 topic
list` with it sees orintwo's topics over eth0, no config warnings.

**2026-11-14: 69/69 PASS** (62 shell with fakes, 7 ROS probe), three runs in a row,
≈110 s each. `results/2026-11-14_pytest.txt`.
