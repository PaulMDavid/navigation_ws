# app_teleop

Decides what reaches the rover's `/cmd_vel`: Nav2, an operator, or nothing. An
operator is either the ground-station PC (over Zenoh) or a phone (over
foxglove_bridge), and one setting on orintwo, `TELEOP_SOURCE`, picks which.

```
ground PC ──Zenoh tcp/7447 (eduroam)──► app_zenoh_bridge ──► /teleop/ground/* ─┐
                                                                               ├► teleop_mux ─► /cmd_vel ─► morpheus_control (rover)
phone ──WebSocket 8765 (orintwo AP)──► app_foxglove_bridge ─► /teleop/phone/* ─┤
                                       (phone DDS domain 51)                   │
Nav2 velocity_smoother ─► /cmd_vel_auto ───────────────────────────────────────┘
```

No Wi-Fi link carries DDS: the ground station reaches the robot through Zenoh, the
phone through a WebSocket. DDS stays on orintwo and the wired network.

## Modes

| Mode | `/cmd_vel` gets |
| --- | --- |
| `autonomous` | Nav2 (`/cmd_vel_auto`); operators are ignored |
| `manual` | the active operator, clamped to `max_linear` / `max_angular`; Nav2 is ignored |
| `stop` | zero, until someone leaves this mode |

- Mode requests: `/teleop/<source>/set_mode` (`std_msgs/String`). `stop` is accepted from
  every source; the other modes only from the active one.
- **Deadman:** operators publish `/teleop/<source>/cmd_vel` at 10 Hz. A command older than
  `teleop_timeout` (0.5 s) counts as zero, so a dropped link stops the rover. Measured
  stop time: 0.41–0.45 s (`utils/teleop_link`).
- `/cmd_vel` is published at 20 Hz in every mode.
- `/teleop/state` (`std_msgs/String`, JSON, 5 Hz) is the robot's own report: mode, who set
  it, source, how long since each operator was last heard, limits, current output. Both
  operator UIs show this, not what they last sent.
- Changing the source puts the robot in `stop`. Boot starts in `initial_mode`
  (`autonomous`, so Nav2 drives as before).

Parameters: [`config/teleop.yaml`](config/teleop.yaml). The speed limits there are
placeholders until checked against `morpheus_control`.

Operators send a plain `Twist` (forward speed, turn rate), like Nav2. Wheel kinematics
are `morpheus_control`'s business on the rover. Full stick sideways asks for a turn in
place (as Nav2's `use_rotate_to_heading` does); if `morpheus_control` is Ackermann-only,
both need adapting.

Nav2's velocity smoother publishes `/cmd_vel_auto` instead of `/cmd_vel`, and
`behavior_server` (spin, backup) goes through the smoother instead of straight to
`/cmd_vel` (`stages_master.yaml`, `app_nav2/launch/navigation.launch.py`). Without this
container running, Nav2's commands reach nothing; the bringup's rover stage checks for it.

## Camera for the phone

`teleop_camera.py` (compose service `app_teleop_camera`, phone source only) relays a
compressed image into the phone domain as `/teleop/camera/compressed` for the app's
camera page.
- Input: the first of `input_topics` (`config/teleop.yaml`) that exists: the ZED 2i's
  `/zed2i/zed_node/rgb/color/rect/image/compressed`, or the older wrapper naming
  `…/rgb/image_rect_color/compressed`. The log says which one it picked.
- Capped at `max_rate` (10 Hz). Frames wider than `max_width` (960 px) are re-encoded at
  `jpeg_quality` (60). Measured: 960x600, about 22 KiB per frame, ~1.8 Mbit/s.
- Lazy: it subscribes to the camera only while the camera page is open.
- It runs in its own process, so JPEG work never delays teleop_mux.
- foxglove_bridge's `send_buffer_limit` (1 MB, about 10 frames) makes a slow link drop
  frames instead of building up video lag.

## Arming the rover (robot_control)

> ⚠️ **Untested on hardware.** Only the unit and loopback-DDS tests in
> `utils/rover_arming` have run; the rover has not seen these presses yet (checklist
> below).

`rover_arming.py` (compose service `app_rover_arming`, runs with either source) arms and
switches the rover's `robot_control` from the phone or the ground PC, without touching
the rover. robot_control takes its mode switches as `/joy` presses
(`sensor_msgs/Joy`, exactly 17 buttons, shorter crashes it); this node publishes them
and **tracks (guesses) robot_control's state from the presses it sent**. It never reads
the rover.

robot_control boots in **manual input** (`/manual_cmd_vel`, 5 % speed), **crab**
steering, **stopped**. Button 1 = input → autonomous (`/cmd_vel`, what teleop_mux
publishes), 16 = toggle Ackermann-only, 2 = resume.

- Commands: `/teleop/phone/rover_cmd` (phone domain) and `/teleop/ground/rover_cmd`
  (main domain, over Zenoh), `std_msgs/String`. Accepted only from teleop_mux's active
  source (read from `/teleop/state`; if that is older than `mux_state_timeout`, 2 s,
  everything is refused), the same rule as `set_mode`.

| command | /joy presses | tracked state after |
| --- | --- | --- |
| `input_auto` | 1 | input = autonomous |
| `steer_ackermann` | 16 only if tracked steering is crab | steering = ackermann |
| `steer_crab` | 16 only if tracked steering is ackermann | steering = crab |
| `resume` | 2 | motion = running |
| `arm` | 1, 16 (if crab), 2 | autonomous / ackermann / running |
| `reset` | none | boot defaults (manual / crab / stopped); use after robot_control restarts |

- Each press is one Joy with that button = 1, then one all-zero Joy (8 axes, 17
  buttons), `press_gap` (0.2 s) between messages. Commands run one at a time; one that
  arrives mid-sequence waits in the queue (up to 8), and what it presses is decided
  when it starts, so `steer_ackermann` twice presses 16 once.
- Steering sets teleop_mux's `max_angular` through `/teleop_mux/set_parameters`:
  `ackermann_max_angular` (1.0; 0.1 steers only ~7°) or `crab_max_angular` (0.1).
  Every `steer_*`, `arm` and `reset` sends it, also when no press was needed, and it is
  retried every second until teleop_mux takes it. A teleop_mux restart goes back to
  the yaml value (0.1) until the next such command.
- `/teleop/rover_state` (`std_msgs/String`, JSON, 4 Hz and on every change, both
  domains):

```json
{"tracked": true, "input": "manual|autonomous", "steering": "crab|ackermann",
 "motion": "stopped|running", "last_cmd": "arm", "last_cmd_age": 3.2,
 "last_cmd_by": "phone", "presses": 3, "rejected": null}
```

`tracked: true` = guessed from the presses sent. `last_cmd*` and `presses` describe
the command that ran last (`presses` = /joy presses it sent). `rejected` is the reason
the most recent command was refused, `null` once one is accepted.

Known gaps: the tracked state goes wrong if someone presses `/joy` on the rover or
robot_control restarts (send `reset`). robot_control's own STOP and whether pressing 1
again returns to manual are unknown, so neither is offered. Ackermann-only ignores
robot_control's own /joy STOP; the mux STOP (zero `/cmd_vel` at 20 Hz) and the deadman
still apply.

The robot's Zenoh router (`app_zenoh_bridge`) routes `/teleop/ground/rover_cmd` in and
`/teleop/rover_state` out. The ground PC's side
(`groundstation_navigation/config/zenoh_bridge_ground.json5`, a submodule) still has to
list them before the ground PC can use this.

Parameters: `rover_arming` in [`config/teleop.yaml`](config/teleop.yaml). Tests:
`utils/rover_arming/`.

**To do on hardware (@PaulMDavid):**
- [ ] On the rover: check the installed `robot_control.py` reacts to the
  orintwo-published /joy exactly as to the hand-published one (log lines in
  `/tmp/wheels.log`: "Switching to autonomous mode", "only Ackerman mode",
  "Resuming motion").
- [ ] Check Ackermann mode follows the mux's zero /cmd_vel (phone STOP + deadman);
  robot_control's own STOP is ignored there.
- [ ] Decide whether the rover should publish its real state later instead of the
  spoof.

## Why the phone has its own DDS domain

foxglove_bridge 3.6.0 (current Humble release) ignores `client_topic_whitelist`: a
WebSocket client can make it publish any topic, `/cmd_vel` included. So
app_foxglove_bridge runs in DDS domain `TELEOP_PHONE_DOMAIN` (51). Only teleop_mux,
teleop_camera and rover_arming are in both domains: teleop_mux reads `/teleop/phone/*` there and mirrors
`/teleop/state` there, teleop_camera publishes `/teleop/camera/compressed` there, and rover_arming
reads `/teleop/phone/rover_cmd` and mirrors `/teleop/rover_state` there. Whatever a client publishes stays in domain 51.
To give the phone more topics later, relay them into domain 51 (extend teleop_mux, or a
zenoh-bridge-ros2dds pair with an allowlist).

## Command source

`TELEOP_SOURCE` lives in `/etc/navws/teleop.env` on orintwo, next to the access point
password (neither is in the repo; `scripts/robot_setup/apply.sh` creates the file and
installs `navws-teleop.service`, which applies it at boot).

| | `ground` (default) | `phone` |
| --- | --- | --- |
| orintwo Wi-Fi | eduroam (client) | access point `orintwo-teleop`, 10.42.0.1/24 |
| who drives in manual | ground-station PC, Zenoh | phone app, foxglove_bridge |
| containers | app_teleop, app_rover_arming, app_zenoh_bridge | + app_foxglove_bridge, app_teleop_phone, app_teleop_camera |

```bash
# on orintwo, over the wired link (192.168.1.210), never over Wi-Fi:
sudo scripts/teleop_source.sh phone     # save + apply now (or reboot)
sudo scripts/teleop_source.sh ground
scripts/teleop_source.sh status
```

If the access point fails to come up, `phone` falls back to `ground` for that boot so the
robot stays reachable over eduroam. `scripts/wifi_mode.sh ap|client|status` does the
Wi-Fi part alone.

Live, without restarting anything: `ros2 param set /teleop_mux source phone`.

## Using it

- **Phone:** join `orintwo-teleop`, open `http://10.42.0.1:8080` in Chrome, *Add to Home
  screen*. See `app_teleop_phone/README.md`.
- **Ground PC:** the Teleop panel in `groundstation_navigation`'s bringup GUI (W/S/A/D,
  space = stop). Over eduroam set `GS_LINK=zenoh` and `ROBOT_IP` in its `.env`.

## First run on orintwo

From the laptop:

```bash
src/app_teleop_phone/build.sh     # APK into www/, which the sync copies
scripts/sync_to_robot.sh
```

On orintwo (`ssh` over the wired link, 192.168.1.210), in `/mnt/ssd/pdavid/navigation_ws`:

```bash
sudo scripts/robot_setup/apply.sh          # once: /etc/navws/teleop.env + boot unit
sudoedit /etc/navws/teleop.env             # set AP_PASSWORD (8+ characters)
sudo scripts/teleop_source.sh phone        # AP up, teleop + bridge + camera containers
scripts/teleop_source.sh status
```

Then the ZED: bring it up as usual (bringup GUI or the camera stage), join
`orintwo-teleop` on the phone, install from `http://10.42.0.1:8080`, open the app.
`docker logs app_teleop_camera_container` shows which camera topic it uses once the
camera page is open. `sudo scripts/teleop_source.sh ground` goes back to eduroam.

## Tests

`utils/teleop_link/`: the laptop stands in for orintwo and both links are driven
end to end, including the deadman and the bridge loophole. `utils/rover_arming/`: the
/joy press sequencing and tracked state.
