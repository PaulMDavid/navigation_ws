# body_tilt

Checks `app_body_tilt`: the GQ7's orientation → body pitch → `body_tilt_joint` on
`/joint_states` → `robot_state_publisher` turns `drivetrain_link` back by that pitch.

- `test_body_tilt.py enu|ned`: plays a fake GQ7 on `/imu/data` (2 s still and level so
  the node can decide ENU/NED, then pitches 0, −12, −5, +3, +15, −25° at random yaw, 1.5 s
  each) and reads TF `chassis_link → drivetrain_link`. Pass: the drivetrain is turned by
  −pitch about y (±0.1°), with no roll or yaw.
- `fake_gq7.py [mean] [amp] [period] [enu|ned]`: endless rocking for RViz
  (default −8 ± 10°, 8 s). Set RViz's fixed frame to `drivetrain_link` to see the body tip.

## Run

Humble container with `ros-humble-{xacro,robot-state-publisher,tf2-geometry-msgs,rclcpp-components}`,
`src/app_body_tilt` built with colcon:

```bash
xacro src/app_robot_state_publisher/config/URDF/robot.urdf.xacro -o /tmp/robot.urdf
ros2 run robot_state_publisher robot_state_publisher /tmp/robot.urdf &
install/app_body_tilt/lib/app_body_tilt/body_tilt_node &   # start the binary itself, see below
python3 utils/body_tilt/test_body_tilt.py enu
```

Start a fresh node for each mode (it locks ENU/NED once). Kill the node binary, not a
`ros2 run` wrapper: killing the wrapper leaves the node running, and a leftover node
locked to the other mode makes the next run fail with folded signs.

## Results

**2026-11-19** (laptop, ros:humble-perception, fake GQ7, IMU mount = identity):
- ENU: 6/6 OK, NED: 6/6 OK; the node decided ENU/NED from the accelerometer correctly
  both times (50/0 votes).
- RViz (fixed frame `drivetrain_link`): body, lidar and ZED rock with the fake pitch,
  wheels stay level.
- Not yet run against the real GQ7: its axes (`imu_link`, FLU vs the GQ7's FRD, i.e.
  `imu_rpy`) are unmeasured; its position doesn't matter for the tilt. See the TODO in
  `sensorsuite_front.xacro`.
