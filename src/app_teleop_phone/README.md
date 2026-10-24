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
