# teleop_link

The laptop stands in for orintwo and drives `app_teleop` through both operator links:
phone (foxglove_bridge) and ground station (Zenoh). Checks the mode logic, speed
limits, the deadman, and that a WebSocket client can't reach anything but the teleop
topics.

Everything runs on loopback DDS (`cyclonedds_lo.xml`) in three domains: 77 = robot,
79 = phone (foxglove_bridge), 78 = ground station. Only teleop_mux (77↔79) and the Zenoh
link (77↔78) connect them, as on the robot.

## Run

```bash
./run.sh                 # automated: probe.py phone, then probe.py ground
CAMERA=1 ./run.sh        # + probe.py camera; needs the Arducam OV9281 plugged in
./phone_session.sh start # hands-on with a real phone; prints the URL to open
./phone_session.sh stop  # stops and prints record.py's report
```

The laptop has no ZED, so the camera page is fed by an Arducam OV9281 (USB, `0c45:6366`)
running the `taojue/app_ov9281_driver` image as-is (Fast DDS; it interoperates with the
Cyclone containers on loopback). `OV9281_DEVICE` (default `/dev/video2`) and
`OV9281_DIR` (its checkout, for the params file) override the defaults. The relay's input
is pointed at `/ov9281/image_raw/compressed` here only; its default is the ZED topic.

`run.sh` kills the ground Zenoh bridge mid-drive to cut that link. The phone deadman
is tested as a silent drop: the socket stays open and commands just stop, which is
what a Wi-Fi drop looks like to the robot.

## Last results

**2026-10-24, `run.sh`: 20/20 PASS.**
- Phone path:
  - `/cmd_vel` at 20.0 Hz with no input.
  - Joystick commands clamped: sent 2.0 m/s, got 0.5 m/s.
  - Deadman stop after the phone goes quiet, 5 runs: 0.409, 0.421, 0.434, 0.425, 0.423 s.
  - Manual ignores Nav2, autonomous ignores the phone.
  - The inactive source can stop but can't take manual; stop holds against Nav2.
- Ground path:
  - State and commands cross Zenoh.
  - Killing the ground bridge mid-drive → `/cmd_vel` zero after 0.448 s.
- Found on the way: **foxglove_bridge 3.6.0 ignores `client_topic_whitelist`.** A client
  advertising `/cmd_vel` or any made-up topic got a real publisher. Fixed by isolating the
  bridge in its own DDS domain (`app_teleop/README.md`); the leak check now passes with 0
  messages through.
- Also found: zenoh-bridge-ros2dds needs `ROS_DISTRO=humble`, or it misreads Humble's
  24-byte GIDs and creates no routes.

**2026-10-24, phone sessions (Pixel, home Wi-Fi, laptop as orintwo).**
- Web page, 121 s: modes set from the phone, joystick drove at 10.0 Hz, peak 0.49 m/s /
  1.00 rad/s, STOP worked. The steps for leaving the app and airplane mode left no gap
  in the stream (largest gap 0.44 s), so the browser kept sending or the steps didn't
  register. Untested.
- Flutter app, 681 s: connected after setting the
  address, manual driving at 10.0 Hz, peak 0.50 m/s / 1.00 rad/s. No stop caused by the
  phone going quiet was recorded (largest gap 1.10 s, while not driving).
  **Leaving the app or losing Wi-Fi mid-drive is still to be tested** (also not
  exercised in the camera session: every stop there was the phone sending zeros).

**2026-10-24, `probe.py camera` (OV9281, 1280x800 at 30 Hz in): 6/6 PASS.**
- The topic is advertised to the phone, and no frames flow until the page subscribes.
- 9.8 Hz out (`max_rate` 10), downscaled to 960x600 JPEG, about 22 KiB per frame
  (~1.8 Mbit/s).
- After the page unsubscribes, the relay drops its input subscription and sends 0 frames.
- Fixed on the way: the throttle gave 7.8 Hz from 30 Hz input (frames arriving a hair
  early lost their slot). It now allows a quarter period of slack.

**2026-10-24, phone session with the camera page (app 1.2.0, landscape), 1062 s.**
- Driving from the camera page: three drives in Manual with hold-to-drive held,
  output up to 0.50 m/s and 1.00 rad/s. Between drives the phone kept sending zeros at
  10 Hz.
- Joystick commands sent in Autonomous were ignored: non-zero from the phone, zero out.
- The page stayed subscribed once opened.
- Found on the way: app 1.1.0 switched to landscape only on the camera page. The
  rotation resized the PageView mid-swipe and bounced it back to the controls page
  (subscribe then unsubscribe 60 ms later). From 1.2.0 the whole app is locked to
  landscape.

Not covered here: `scripts/wifi_mode.sh ap` (turning the laptop into an access point
cuts its internet), and the rover itself.
