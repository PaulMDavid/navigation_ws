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
./phone_session.sh start # hands-on with a real phone; prints the URL to open
./phone_session.sh stop  # stops and prints record.py's report
```

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
  **Leaving the app or losing Wi-Fi mid-drive is still to be tested.**

Not covered here: `scripts/wifi_mode.sh ap` (turning the laptop into an access point
cuts its internet), and the rover itself.
