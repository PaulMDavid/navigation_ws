# app_teleop_phone

The phone side of `app_teleop`: the Android app that drives the rover when orintwo's
command source is `phone`. It talks to `app_foxglove_bridge` (port 8765).

- **`flutter/`**: the app (submodule, [rover_teleop](https://github.com/PaulMDavid/rover_teleop)).
- **`build.sh`**: builds it in a container (`builder/`, memory-capped) into
  `www/rover-teleop.apk`, which is not committed. `scripts/sync_to_robot.sh` copies it.
- **`www/`**: a download page for the APK, served by the `app_teleop_phone` compose
  service on port 8080.

## Install in the field

1. Join `orintwo-teleop` (password in `/etc/navws/teleop.env` on orintwo).
2. Open `http://10.42.0.1:8080` in Chrome, download the app and install it (allow
   installs from Chrome once).
3. Open **Rover Teleop**. It connects to `10.42.0.1` by default; tap the address on the
   controls page to change it.

## Pages

Landscape, left to right **System**, **Wheels**, **Controls**, **Camera**, opening on
**Controls** (modes, STOP, joystick). Swipe left for the **Camera**, swipe right for
**Wheels**, and right again for **System**. The Wheels column also goes up and down:
swipe down from **Wheels** (or *⌃ Autonav*) for **Autonav** above it, swipe up (or
*⌄ Record*, bottom left of Wheels) for **Record** below it.

```
              Autonav
                 ↑ swipe down
System  ←  Wheels  ←  Controls  →  Camera
                 ↓ swipe up
              Record
```

### Wheels

- Left: robot_control's modes as orintwo tracks them from the `/joy` presses it sent
  (`/teleop/rover_state`: input, steering, motion, last command and its age, a refused
  command's reason in red), with "⚠ GUESSED STATE" while `tracked`; below, the mux
  (`/teleop/state`): mode, source, output vx/wz, max_angular. "—" when nothing arrived
  for 1 s.
- Right: buttons that send `/teleop/phone/rover_cmd`: *Input → /cmd_vel*
  (`input_auto`), *Crab | Ackermann* (`steer_crab` / `steer_ackermann`, the tracked
  one lit), *Resume* (`resume`), *HOLD TO ARM* (hold 1 s: mux to Manual, then `arm`),
  *Reset* (`reset`, after robot_control restarted; asks first), and the mux STOP.
- The buttons are off, with the reason, without a link or when the mux source isn't
  `phone`. STOP always works. A drag that starts on a button doesn't turn the page.

orintwo's side (the node that presses `/joy` and tracks the state) is in `app_teleop`
(#23).

### System

Brings the robots up from the phone over ssh (#28); orintwo's side is
`scripts/phone_ctl.sh` (#27), which the phone's key may only run.

- Left: each step as `phone_ctl.sh` streams it: ✓ ok with its time, ✗ fail with the
  reason in red, ⟳ running (e.g. `retry 1/3`), ! warn, – skipped. Rows from an earlier
  run are dimmed. Long-press a row for its log (`log <step>`).
- Right: *UP* (`up`), *STOP* (`stop`, always on, also cancels a running verb), *Camera
  on* (`camera`), *Status* (`status`), *Recenter wheels…* (wheels go limp: align by
  hand, tick FL 11 / FR 12 / RL 13 / RR 14, confirm → `zero <ids>`, its steps live) and
  *Show public key* (copy / share).
- ssh as `orintwo` to `orintwo.local`, then an address typed on the page (tap the host
  in the header), then the robot address above. Key: ed25519, generated on the phone,
  kept in Android secure storage; install it with `scripts/robot_setup/phone_link.sh`.
  orintwo's host key is pinned on first connect (MD5, compare with
  `ssh-keygen -l -E md5 -f /etc/ssh/ssh_host_ed25519_key.pub`); a different key refuses
  the connection with a red banner until accepted on the phone.

### Autonav

Nav2 from the phone (#30); orintwo's side is `nav_relay` in `app_teleop` (#32, its
README's "Autonav relay" section has the message contract). The app draws the map itself.

- Map: the PNG from `/teleop/nav/map`, placed by `/teleop/nav/map_meta` (resolution,
  origin, size), with the robot (▲, TF `map → chassis_link`), Nav2's plan (dots) and the
  active goal from `/teleop/nav/state`. *⌖ center on robot*, *fit*.
- **Tap** places a goal (◎, facing away from the robot), **drag from it** sets the heading;
  **two fingers** pan and pinch-zoom. Nothing is sent before **GO**. One-finger gestures
  never turn the page: leave via *⌄ Wheels*.
- **GO**: mux to `autonomous` (`set_mode`), then the goal (`/teleop/phone/nav_cmd`
  `{"cmd": "goal", "x", "y", "yaw"}`, map frame, REP-103 yaw). **CANCEL**: `cancel`, then
  mux to `stop`. The red mux **STOP** is on the page too.
- **NAV UP** / **NAV STOP**: `bringup_go` / `bringup_stop` (app_bringup_manager through
  nav_relay). Below them the stages as one line of icons (✓ ready, ⟳ starting, · pending,
  ! warn, ✗ failed, ⊘ blocked, – stopped); tap it for each stage's reason and failing
  checks.
- Header: Nav2 ● ready (nav2 stage ready and the action server there) / server up / down,
  and the mux mode. Under GO: distance and ETA while driving, else the last goal's status
  and reason. A refused command's reason (`rejected`) shows in red on the map.
- The buttons are off, with the reason, without a link, without nav state, or when the
  mux source isn't `phone` (nav_relay refuses everything then); GO also needs Nav2's
  action server and a goal. STOP always works.
- The nav topics are subscribed only while the page shows. The map is latched; the
  bridge can drop it when its send buffer is full, so the app subscribes to the map and
  meta again on every page open and whenever one half is missing 3 s after asking.

### Record

Bags on orintwo from the phone (#29); orintwo's side is `phone_ctl.sh record …` →
`scripts/record/record_drive.sh` (#35; `app_teleop/README.md`, "Recording from the
phone", has the JSON contract the page parses). Same ssh as System: same key, host
order, host-key pin, same forced command.

```
┌──────────────────────────────────────────────────────┐
│ ⌃ Wheels RECORD ● recording 00:12:41 drive_… [MUX STOP]│
├──────────────────────────┬───────────────────────────┤
│ Preset [Drive ▾]         │   [  ● START  ]           │
│ ☑ GQ7 IMU/GNSS/EKF    20 │   [  ■ STOP   ]           │
│ ☑ ZED left+right compr. 7│ Bag  8.4 GB · 11.0 MB/s   │
│ ☑ wheels / cmd_vel / tf  │ SSD  412 GB free          │
│ ☐ Ouster points        2 │ ≈ 10 h left at this rate  │
│ [ All topics… 52 sel. ]  │ ✗ /zed2i/… NO MESSAGES    │
└──────────────────────────┴───────────────────────────┘
```

- Left: the presets from `record presets`, the default (`drive`) preselected. Every
  group is a checkbox row (the preset's ticked; ▣ when only some of its topics are
  selected). Picking another preset resets the selection to its topics. *All topics…*:
  `record topics` (≈ 10 s; ⟳ to sample again), every live topic with type, Hz and
  MB/s (`?` when orintwo can't load the type), a search box (name or type); the selected
  topics that aren't live are listed too ("not live"). Ticks change the selection.
- **● START** sends `record start <preset>` plus the differences: `+/topic` for each
  selected topic the preset lacks, `-/topic` for each of its topics left out. Its
  progress (`sensors: docker start …`) shows under the status; the result in green, amber
  when sensors stayed silent (recording anyway, with their names), red on a failure.
  Exit 75 shows "Busy: …" (amber), 64 "Refused: …" (red), with the script's reason.
- **■ STOP** asks first, then `record stop`: the closing progress, then the final size,
  duration, messages and files. It only stops the recording. The rover's mux STOP is the
  small red **MUX STOP** in the header, so the two can't be confused.
- Status: `record status` runs while the page shows (closed when it doesn't) and is
  opened again when the page reopens, after its 1 h limit, after START/STOP, and every
  5 s after an ssh error. Header: ● recording + elapsed + bag (○ not recording, last
  bag). Right: bag size · on-disk rate, `/mnt/ssd` free, ≈ hours left, silent topics
  (✗ … NO MESSAGES; ✓ all topics publishing; "… checking topics" before the first
  verdict), an amber banner for unclosed bags (tap: the `ros2 bag reindex` command).
  Tap the header status to ask again (e.g. after a recording was started by hand).
- While recording (or starting) the selection is locked. Buttons and checkboxes don't
  turn the page; a swipe down elsewhere (or *⌃ Wheels*) goes back.

Widget tests: `test/wheels_page_test.dart`, `test/system_page_test.dart` (fake ssh
layer), `test/autonav_page_test.dart` (fake bridge client) and
`test/record_page_test.dart` (fake ssh layer playing the README's record lines and the
real `record presets` output) in the app, run in the builder container (`flutter test`).
