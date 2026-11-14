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

Landscape, opening on **Controls** (modes, STOP, joystick). Swipe left for the
**Camera**, swipe right for **Wheels**:

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
(#23). Widget tests: `test/wheels_page_test.dart` in the app, run in the builder
container (`flutter test`).
