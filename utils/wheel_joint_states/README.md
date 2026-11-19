# wheel_joint_states

Checks `app_wheel_joint_states`: the rover's `/Motor_pos` (wheels_cpp, 8 MD80 positions in
rad: steer FL FR RL RR, drive FL FR RL RR) → `/joint_states` → `robot_state_publisher`
places the steering and wheel links. Mapping and signs are aizzaf's
`motor_controller/joint_state_node.py` (git.tu-berlin.de/rover/erc25, branch `test_teleop`,
59b8f93): right-side drive motors (22, 24) negated, shafts published as 0.

- `test_wheel_joint_states.py`: first checks nothing is published without `/Motor_pos`
  or for a malformed one (a NaN, 7 values), then publishes all zeros, then
  `[0.30, -0.20, 0.10, -0.40, 1.00, 2.00, -0.50, 0.70]`; checks `/joint_states` (shafts 0,
  signs) and that TF turns each steering/wheel link about its joint's z axis by exactly
  that angle.
- `fake_motors.py [steer_amp] [speed]`: endless fake wheels_cpp for RViz (steering swings,
  wheels roll forward with the right side counter-rotating like the real motors).

## Run

Humble container with `ros-humble-{xacro,robot-state-publisher,rclcpp-components}`,
`src/app_wheel_joint_states` built with colcon:

```bash
xacro src/app_robot_state_publisher/config/URDF/robot.urdf.xacro -o /tmp/robot.urdf
ros2 run robot_state_publisher robot_state_publisher /tmp/robot.urdf &
install/app_wheel_joint_states/lib/app_wheel_joint_states/wheel_joint_states_node &
python3 utils/wheel_joint_states/test_wheel_joint_states.py
```

## Results

**2026-11-19 (cleanup)**: the node publishes only on valid `/Motor_pos` (no zeros before
data, no timer re-stamping old values, NaN / wrong-size messages dropped). 13/13 OK
(3 "nothing published" checks + the 10 below).

**2026-11-19** (laptop, ros:humble-perception, fake /Motor_pos):
- 10/10 OK: shafts 0; steering = motor value; drive FL/RL = motor, FR/RR = −motor; TF
  rotation about each joint's z matches to 1e-4 rad, no off-axis rotation.
- RViz with fake_motors + fake_gq7 (utils/body_tilt): steering and wheels move, body tilts.
- Not yet run against the real rover. The signs are aizzaf's (checked by them in RViz,
  2026-05); whether +steering turns the real wheels the way RViz shows is unverified here.
