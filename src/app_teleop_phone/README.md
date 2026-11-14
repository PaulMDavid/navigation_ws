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
**Wheels**, and right again for **System**.

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

Widget tests: `test/wheels_page_test.dart` and `test/system_page_test.dart` (fake ssh
layer) in the app, run in the builder container (`flutter test`).
