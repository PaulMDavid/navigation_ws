# app_teleop_phone

The phone side of `app_teleop`: how a phone drives the rover when orintwo's command
source is `phone`. Both talk to `app_foxglove_bridge` (port 8765).

- **`flutter/`**: the Android app (submodule,
  [rover_teleop](https://github.com/PaulMDavid/rover_teleop)). This is the one to use.
  Build with `./build.sh`, which writes `www/rover-teleop.apk` (not committed).
- **`www/`**: a single web page doing the same, served by the `app_teleop_phone` compose
  service on port 8080. It also hosts the APK download link. It is a fallback: in
  Chrome it can't pin itself to a Wi-Fi network without internet, and it kept sending
  while backgrounded in one test (`utils/teleop_link/README.md`).

## Install in the field

1. Join `orintwo-teleop` (password in `/etc/navws/teleop.env` on orintwo).
2. Open `http://10.42.0.1:8080/rover-teleop.apk` in Chrome and install it (allow installs
   from Chrome once).
3. Open **Rover Teleop**. It connects to `10.42.0.1` by default.

To test elsewhere (e.g. the laptop standing in for orintwo, `utils/teleop_link`), tap
the address at the bottom of the app and enter that machine's IP.
