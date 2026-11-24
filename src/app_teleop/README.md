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
| `input_auto` | 1 only if tracked input is manual | input = autonomous |
| `steer_ackermann` | 16 only if tracked steering is crab | steering = ackermann |
| `steer_crab` | 16 only if tracked steering is ackermann | steering = crab |
| `resume` | 2 | motion = running |
| `arm` | 1 (if manual), 16 (if crab), 2 | autonomous / ackermann / running |
| `reset` | none | boot defaults (manual / crab / stopped); use after robot_control restarts |

- Each press is one Joy with that button = 1, then one all-zero Joy (8 axes, 17
  buttons), `press_gap` (0.2 s) between messages. Commands run one at a time; one that
  arrives mid-sequence waits in the queue (up to 8), and what it presses is decided
  when it starts, so `steer_ackermann` twice presses 16 once and `input_auto` twice presses 1 once.
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

## Autonav relay (nav_relay)

> ⚠️ **Untested on hardware.** Only the unit and loopback-DDS tests in
> `utils/nav_relay` have run, against fake SLAM / Nav2 / bringup manager (checklist
> below).

`nav_relay.py` (compose service `app_nav_relay`, container `app_nav_relay_container`,
phone source only) is the backend of the app's **Autonav** page (#30). It lives in the
main domain and the phone domain (`phone_domain.py`): it takes Nav2 goals and bringup
commands from the phone, and hands the phone the SLAM map, the robot pose, the plan and
Nav2's state. The phone sees nothing else of Nav2.

| topic | type | dir | domain(s) | QoS |
| --- | --- | --- | --- | --- |
| `/teleop/phone/nav_cmd` | `std_msgs/String` (JSON) | phone → orintwo | phone | reliable, volatile, depth 10 |
| `/teleop/nav/map` | `sensor_msgs/CompressedImage` (PNG) | orintwo → phone | both | reliable, **transient local**, depth 1 |
| `/teleop/nav/map_meta` | `std_msgs/String` (JSON) | orintwo → phone | both | reliable, **transient local**, depth 1 |
| `/teleop/nav/state` | `std_msgs/String` (JSON) | orintwo → phone | both | reliable, volatile, depth 10 |

What it uses in the main domain: the map `map_topic` (`/rtabmap/map`, what Nav2's global
costmap static layer reads), TF `map → chassis_link` (Nav2's `global_frame` /
`robot_base_frame`), Nav2's global plan `/plan` (`nav_msgs/Path`), the
`NavigateToPose` action `/navigate_to_pose`, `app_bringup_manager`'s `/bringup/go`,
`/bringup/stop` (`std_srvs/Trigger`) and `/bringup/status`, and teleop_mux's
`/teleop/state` (for the source rule).

### Conventions

- **Frame:** every x, y, yaw in these messages is in the `map` frame (`frame_id` says so),
  metres and radians.
- **Yaw:** REP-103, rotation about +z, **counter-clockwise from the map's +x axis**,
  radians, in (−π, π] when sent by orintwo (the phone may send any finite value).
  0 = facing +x, π/2 = facing +y.
- Times: `stamp` values are ROS time on orintwo (Unix seconds, float). `*_age` values are
  seconds before the state message's `stamp`.
- Floats in the state are rounded to 0.001 (plan points to 0.01 m).

### Phone → orintwo: `/teleop/phone/nav_cmd`

One JSON object per message:

| JSON | does |
| --- | --- |
| `{"cmd": "goal", "x": <number>, "y": <number>, "yaw": <number>}` | sends a Nav2 `NavigateToPose` goal at (x, y) facing yaw, `map` frame. A new goal preempts the running one (Nav2 does this); the state then follows the new goal only. |
| `{"cmd": "cancel"}` | cancels the goal this relay sent (also while Nav2 has not accepted it yet). |
| `{"cmd": "bringup_go"}` | calls `/bringup/go` |
| `{"cmd": "bringup_stop"}` | calls `/bringup/stop` |

- `cmd` is case-insensitive. `x`, `y`, `yaw` must be finite JSON numbers (not strings,
  not booleans); all three are required.
- **Accepted only while teleop_mux's active source is `phone`** (`source` in
  `/teleop/state`; if that is older than `mux_state_timeout`, 2 s, everything is refused).
  This applies to all four commands, `cancel` included. Mux STOP
  (`/teleop/phone/set_mode` `stop`) works from every source and stops the rover in any
  case.
- A goal does **not** change the mux mode. The app sends `set_mode autonomous` before the
  goal, otherwise Nav2 plans and "drives" but teleop_mux never passes its `/cmd_vel_auto`
  on.
- A refused command leaves the state as it was and sets `rejected` in the next
  `/teleop/nav/state` (published right away). Reasons (exact text):
  - `nav_cmd refused: not JSON: '…'`, `nav_cmd refused: expected a JSON object with a "cmd" string`,
    `nav_cmd refused: unknown cmd '…'`, `nav_cmd refused: goal needs finite numbers x, y, yaw; <k> = <v>`
  - `<cmd> refused: active source is <source>`, `<cmd> refused: teleop_mux source unknown (no /teleop/state)`
  - `goal refused: Nav2 action server /navigate_to_pose not available`
  - `cancel refused: no active goal`
  - `bringup_go refused: /bringup/go not available (app_bringup_manager running?)` (same for stop)

### orintwo → phone: the map

`/teleop/nav/map` (`sensor_msgs/CompressedImage`) + `/teleop/nav/map_meta`
(`std_msgs/String`, JSON). Both are latched (transient local), so a client that
subscribes late gets the last map at once. They are re-sent only when the picture changes
(the downsampled PNG or its meta differ), at most `map_max_rate` (0.5 Hz); a change in
between goes out when the interval is over, so the latched one is always the newest.
meta is published just before its image.

CompressedImage: `format: "png"`, `header.frame_id: "map"`, `header.stamp` = the meta's
`stamp` (pair them by that, or take the latest of each). `data` is an 8-bit greyscale
PNG:

| pixel value | meaning |
| --- | --- |
| 254 | free (OccupancyGrid 0..`free_thresh` 25) |
| 0 | occupied (≥ `occupied_thresh` 65) |
| 205 | unknown (−1 and 26..64) |

(map_server's trinary values, so it looks like RViz / a saved map.)

meta JSON, all keys always present:

```json
{"seq": 3, "stamp": 1763130000.12, "map_stamp": 1763129999.80, "frame_id": "map",
 "resolution": 0.15, "width": 834, "height": 600,
 "origin": {"x": -60.0, "y": -40.0, "yaw": 0.0},
 "downsample": 3, "source_resolution": 0.05, "source_width": 2500, "source_height": 1800,
 "encoding": "png", "values": {"free": 254, "occupied": 0, "unknown": 205}, "bytes": 67812}
```

| key | type | |
| --- | --- | --- |
| `seq` | int | 1, 2, … per map sent since the relay started |
| `stamp` | float | when the relay sent it (= image `header.stamp`) |
| `map_stamp` | float | the source OccupancyGrid's header stamp |
| `frame_id` | string | `"map"` |
| `resolution` | float | m per **PNG pixel** (= `source_resolution × downsample`) |
| `width`, `height` | int | PNG size in pixels, each ≤ `map_max_size` (1000) |
| `origin` | {x, y, yaw} floats | the map's origin = the **outer corner of the bottom-left cell** (lowest x, lowest y), in `map`; yaw of the grid (0 for rtabmap) |
| `downsample` | int | cells per pixel side, `ceil(max(source_width, source_height) / 1000)` |
| `source_*` | float / int | the SLAM grid before downsampling |
| `encoding` | string | `"png"` |
| `values` | {free, occupied, unknown} ints | the pixel values above |
| `bytes` | int | PNG size |

**Pixel ↔ map.** PNG row 0 is the **top = highest y** (the grid's rows are flipped, as in
a saved map), column 0 is the lowest x. With `r = resolution`, `(ox, oy, θ) = origin`, the
centre of pixel (column u, row v) is

```
gx = (u + 0.5) * r                  # in the grid's own axes
gy = (height - v - 0.5) * r
x  = ox + gx*cos θ - gy*sin θ       # in map; θ = 0 → x = ox + gx, y = oy + gy
y  = oy + gx*sin θ + gy*cos θ
```

and the other way (θ = 0): `u = (x - ox) / r`, `v = height - (y - oy) / r` (pixel edges).
Downsampling: each `downsample × downsample` block of cells becomes one pixel, occupied if
any cell in it is occupied, else free if any is free, else unknown. The grid is padded
with unknown on its +x / +y side to a multiple of `downsample`, so `origin` is unchanged
and `width × resolution` may exceed the source map's extent by up to one pixel.

### orintwo → phone: `/teleop/nav/state`

JSON at `state_rate` (5 Hz), plus right after every command and every goal result. All
keys are always present; `null` where noted.

```json
{"stamp": 1763130001.2, "frame_id": "map",
 "pose": {"x": 1.5, "y": -2.0, "yaw": 0.7, "age": 0.03}, "pose_error": null,
 "nav2_ready": true,
 "status": "navigating", "reason": null,
 "goal": {"x": 3.0, "y": 4.0, "yaw": 1.0, "age": 2.4},
 "distance_remaining": 7.5, "eta": 15.0, "navigation_time": 2.0, "recoveries": 0,
 "plan": [[1.5, -2.0], [1.55, -1.97], [3.0, 4.0]], "plan_age": 0.4,
 "bringup": {"overall": "ready", "stamp": 1763130000.9, "age": 0.3,
             "stages": [{"name": "slam", "title": "SLAM (rtabmap)", "state": "ready",
                         "required": true, "message": "",
                         "checks": [{"label": "TF map → chassis_link", "ok": true,
                                     "value": "0.05 s old (max 1.0)", "hint": ""}]}]},
 "bringup_reply": {"cmd": "bringup_go", "success": true, "message": "bringup queued", "age": 5.1},
 "last_cmd": "goal", "last_cmd_age": 2.4, "rejected": null}
```

| key | type | |
| --- | --- | --- |
| `stamp` | float | ROS time when published |
| `frame_id` | string | `"map"`: frame of pose, goal and plan |
| `pose` | {x, y, yaw, age} or null | robot = TF `map → chassis_link`, latest; `age` = s since that transform's stamp. `null` while TF has no such transform (SLAM not up) |
| `pose_error` | string or null | first line of the TF error when `pose` is null |
| `nav2_ready` | bool | the `/navigate_to_pose` action server is there |
| `status` | string | `"idle"` (no goal sent since the relay started), `"navigating"`, `"succeeded"`, `"aborted"`, `"canceled"`: the goal this relay sent last. Goals sent by others (RViz, ground station) are not tracked. |
| `reason` | string or null | why, for `status`: `"waiting for Nav2 to accept"` (navigating, not yet accepted), `"cancel requested"` (navigating, cancel sent, no result yet), `"Nav2 rejected the goal"` / `"Nav2 aborted the goal"` / `"Nav2 ended the goal with status <n>"` / `"sending the goal failed: …"` / `"no result from Nav2: …"` (aborted); `null` otherwise. Humble's NavigateToPose result has no error code, so there is no finer reason for an abort. |
| `goal` | {x, y, yaw, age} or null | the last goal sent (stays after it ended, so the app can show where it went); `age` = s since sent. `null` before the first goal. |
| `distance_remaining` | float or null | m, Nav2 feedback; `null` unless `status` is `"navigating"` and feedback has arrived |
| `eta` | float or null | s, Nav2's `estimated_time_remaining`; same rule |
| `navigation_time` | float or null | s since Nav2 started the goal; same rule |
| `recoveries` | int or null | Nav2's `number_of_recoveries`; same rule |
| `plan` | [[x, y], …] | Nav2's global plan (`/plan`), first and last point kept, evenly thinned to ≤ `plan_max_points` (200). `[]` when no plan newer than `plan_max_age` (3 s) exists. Shows any plan Nav2 is following, also one from a goal sent elsewhere. |
| `plan_age` | float or null | s since that plan arrived; `null` when `plan` is `[]` |
| `bringup` | object or null | the last `/bringup/status` from app_bringup_manager, cut down: `overall` (`"idle"`, `"bringing_up"`, `"ready"`, `"failed"`, `"stopping"`), its `stamp`, `age` (s since the relay received it; the manager publishes at 1 Hz, so > 3 s = manager gone), `stages` = [{`name`, `title`, `state` (`pending` `starting` `ready` `warn` `failed` `blocked` `stopped`), `required`, `message` (the reason when not ready), `checks` = [{`label`, `ok` (true/false/null = measuring), `value`, `hint`}]}]. Logs, events and containers are left out. `null` until the manager has been seen. |
| `bringup_reply` | {cmd, success, message, age} or null | the manager's answer to the last `bringup_go`/`bringup_stop` (`"bringup queued"` / `"stop queued"`; the real progress is in `bringup`) |
| `last_cmd` | string or null | the last command name received (`goal`, `cancel`, `bringup_go`, `bringup_stop`), refused or not; unparseable messages don't count |
| `last_cmd_age` | float or null | s since it arrived |
| `rejected` | string or null | why the most recent message was refused (texts above); `null` once one is accepted |

Green / red for the app: Nav2 stage up = `bringup.stages[name == "nav2"].state == "ready"`
(or `bringup.overall == "ready"` for the whole stack) and `nav2_ready`.

### Notes

- foxglove_bridge's `client_topic_whitelist` allows `/teleop/phone/nav_cmd` (it is
  ignored by 3.6.0 anyway; the phone domain is the real gate).
- A map PNG is 10–150 KiB (`utils/nav_relay` bench); foxglove_bridge drops messages for
  a client whose `send_buffer_limit` (1 MB) is full, e.g. while the camera page streams.
  A dropped map isn't re-sent until the map changes: the app can unsubscribe and
  subscribe `/teleop/nav/map` again to get the latched one.
- The map work (downsample + PNG) runs at most every 2 s, ~60–150 ms on the laptop for
  2500×1800 to 4000×4000 maps; the relay subscribes to the full map, so its DDS traffic
  is one copy of every map rtabmap publishes.
- Parameters: `nav_relay` in [`config/teleop.yaml`](config/teleop.yaml). Tests:
  `utils/nav_relay/`.

**To do on hardware (@PaulMDavid):**
- [ ] With the Nav2 stack up on orintwo: map shows, robot pose and plan line up with RViz.
- [ ] Tap goal + heading → GO → rover drives there; CANCEL stops it.
- [ ] NAV UP from the phone brings the stages up green.
- [ ] Map relay doesn't hurt SLAM/Nav2 rates on orintwo.

## One-button bring-up from the phone (`scripts/phone_ctl.sh`)

> ⚠️ **Untested on hardware.** Only the fakes and loopback-DDS tests in
> `utils/phone_ctl` have run (checklist below).

The phone (on the user's hotspot `Pixel_6105`, orintwo joined to it, found as
`orintwo.local`) ssh's into orintwo with a key that may run only `scripts/phone_ctl.sh`;
orintwo ssh's into the rover over the wired link with a key that may run only
`scripts/robot_setup/rover/rover_wheels_ctl.sh`. The verb is the ssh command:

| verb | does |
| --- | --- |
| `up` | `preflight` → `teleop` → `rover_link` → `wheels`, stops at the first failing step |
| `camera` | `app_zed2i_camera` + `app_teleop_camera`; green when `/teleop/camera/compressed` arrives at ≥ 8 Hz (ZED first start ~6 min) |
| `stop` | rover-wheels.service, camera, `app_rover_arming` + `app_nav_relay`; app_teleop and the bridge stay up |
| `status` | every check, starts nothing |
| `zero <ids>` | ids from 11 12 13 14 (FL FR RL RR): wheels off → `mdtool config zero/save` each, 3 s apart → wheels on → wheels check → `reset` |
| `log <step>` | last 50 log lines of that step |

Steps of `up`:
- `preflight`: `/mnt/ssd` mounted, `src/config/dds/cyclonedds.xml` present, `/` below 95 %
  (warn from 95 %, fail at 100 %).
- `teleop`: `TELEOP_SOURCE=phone docker compose -p navbringup up -d app_teleop
  app_foxglove_bridge app_rover_arming app_nav_relay`; green when `/teleop/state` says `source: phone`.
- `rover_link`: 192.168.1.230 answers ping, and the ssh key works (`rover_wheels_ctl.sh status`).
- `wheels`: starts `rover-wheels.service` on the rover; green when its runner has seen the
  MD80s added (no "Failed to add MD80" for 5 s after the last "Added MD80" line) and
  `/joy` + `/cmd_vel` have a subscriber; then `reset` to rover_arming. If the service is
  already running and healthy, it is left alone and no `reset` is sent.

ROS checks run as `src/app_teleop/phone_probe.py` inside `app_teleop_container`
(`docker exec`), so orintwo's host needs no ROS.

Output, one JSON object per line as the steps run:

```json
{"step": "wheels", "state": "running", "reason": "retry 1/3: MD80 11 failed to add; mdtool encoder, relaunch", "t": 9.4}
{"step": "wheels", "state": "ok", "reason": "MD80 11 12 13 14 added; /joy + /cmd_vel subscribed; rover_arming reset", "t": 21.0}
{"done": true, "ok": true}
```

`state` is `running|ok|fail|warn|skipped`; `t` is seconds since the command started. A
refused command gives `{"step": "command", "state": "fail", "reason": "refused: …"}`.
`log` gives one line per log line with `"state": "ok"`, the line in `reason` and
`"log": true`. `up`, `stop`, `camera` and `zero` take a lock; a second one meanwhile gets
`busy`.

**Rover side** (`scripts/robot_setup/rover/`): `rover-wheels.service` is a systemd user
unit (linger on) that runs `rover_wheels_run.sh`: `ros2 launch morpheus_control
morpheus_control.launch.py` from `~/erc25/wheels_ws/install` with Cyclone DDS pinned to
eth0 (`cyclonedds_rover.xml`, set in the runner because the unit skips `~/.bashrc`, #49),
logging to `/tmp/wheels.log`. If the log shows `Failed to add MD80 with ID: <id>` it stops
the launch, waits until `/dev/ttyACM0` is free, runs `mdtool encoder <id>` (SIGINT after
5 s) with 3 s before and after, and relaunches; after 3 retries it gives up with that id.
Settings (paths, gaps, the expected MD80 ids) can be overridden in
`~/.config/rover-wheels.env`, see `rover_wheels_common.sh`. It replaces the `wheels` tmux
session: stop that first (`start` refuses while something else holds `/dev/ttyACM0`).

**Setup, once**, on orintwo after `scripts/sync_to_robot.sh`:

```bash
scripts/robot_setup/phone_link.sh phone.pub   # the key from the app's "Show public key"
```

It installs the phone's key (restricted to `phone_ctl.sh`), creates
`~/.ssh/navws_rover_ed25519` and installs it on the rover (restricted to
`rover_wheels_ctl.sh`), copies `scripts/robot_setup/rover/` to
`rover:/home/rover/pdavid/navws_rover` and installs the unit there (asks for the rover
password and sudo once, for linger). Later changes to the rover files:
`scripts/sync_to_robot.sh --rover-files`. Tests: `utils/phone_ctl/`.

**To do on hardware (@PaulMDavid):**
- [ ] Run `phone_link.sh` at the robots; add the phone's public key.
- [ ] `rover-wheels.service` starts robot_control like the tmux launch did; MD80 retry
  recovers a "Failed to add MD80". Check the success line in `/tmp/wheels.log` matches
  `MD80_ADDED_RE` (`[Aa]dded MD80[^0-9]*([0-9]+)`, a guess); if not, `wheels` shows a
  warn ("no 'Added MD80' lines") instead of ok.
- [ ] `phone_ctl.sh up` all green → HOLD ARM → drive.
- [ ] `zero 14` on one hand-aligned wheel; the wheel tracks straight after.
- [ ] `orintwo.local` resolves on the hotspot.

## Why the phone has its own DDS domain

foxglove_bridge 3.6.0 (current Humble release) ignores `client_topic_whitelist`: a
WebSocket client can make it publish any topic, `/cmd_vel` included. So
app_foxglove_bridge runs in DDS domain `TELEOP_PHONE_DOMAIN` (51). Only teleop_mux,
teleop_camera, rover_arming and nav_relay are in both domains: teleop_mux reads `/teleop/phone/*` there and mirrors
`/teleop/state` there, teleop_camera publishes `/teleop/camera/compressed` there, rover_arming
reads `/teleop/phone/rover_cmd` and mirrors `/teleop/rover_state` there, and nav_relay reads
`/teleop/phone/nav_cmd` and publishes `/teleop/nav/*` there. Whatever a client publishes stays in domain 51.
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
| containers | app_teleop, app_rover_arming, app_zenoh_bridge | + app_foxglove_bridge, app_teleop_phone, app_teleop_camera, app_nav_relay |

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
/joy press sequencing and tracked state. `utils/nav_relay/`: the Autonav relay against fake
SLAM / Nav2 / bringup manager.
