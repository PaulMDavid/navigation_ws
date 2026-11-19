# urdf_xacro_check

Checks that the xacro robot model (`src/app_robot_state_publisher/config/URDF/robot.urdf.xacro`)
keeps the reference URDF's links and joints unchanged, and that it loads in
`robot_state_publisher`.

`check_urdf.py NEW.urdf REFERENCE.urdf` compares every link and joint of the new model
with the reference (attributes compared numerically, to 1e-9), lists the dropped ones,
and checks that `chassis_link` is the only root. It exits 1 on any difference.

## Run

```bash
# render (on the host: python3 -m venv v && v/bin/pip install xacro)
xacro src/app_robot_state_publisher/config/URDF/robot.urdf.xacro > /tmp/new.urdf
# reference = the last generated URDF from the sim model (removed in the xacro commit)
git show 06dc3e7:src/app_robot_state_publisher/config/URDF/robot.urdf > /tmp/ref.urdf
python3 utils/urdf_xacro_check/check_urdf.py /tmp/new.urdf /tmp/ref.urdf
```

ROS check (Humble container, `ros-humble-xacro` installed): `xacro ... -o /tmp/robot.urdf`,
`ros2 run robot_state_publisher robot_state_publisher /tmp/robot.urdf`, then
`ros2 run tf2_ros tf2_echo chassis_link <frame>`.

`check_urdf.py --shift DZ NEW REF` is for a moved root frame: with all joints at zero,
every link frame and visual/collision pose must be where it was in the reference, i.e.
new pose = reference pose + (0, 0, DZ).

## Results

**2026-11-19 (later)**: `chassis_link` moved down 0.114 m onto the shaft pivot axis
(it sat 2 cm above the chassis box). Box and shaft pivots changed by +0.114 m in z so the
drivetrain stays put; the sensor suite keeps its offsets from `chassis_link` (lidar 0.17,
ZED2i 0.106, IMU 0.10), i.e. it comes down 0.114 m with the frame. li_slam's
`lio_base_to_chassis` and the GNSS placeholder are unchanged.
- `check_urdf.py --shift 0.114`: the 44 drivetrain/box frames and visuals are where they
  were; only the 14 sensor-suite entries differ, each by exactly 0.114 m.
- `check_urdf.py --shift 0`: no sensor-suite entry differs (same pose w.r.t. `chassis_link`).
- From `chassis_link`: shaft pivots z +0.0010 / −0.0013; wheel centres z ≈ −0.27 (joints at 0).

**2026-11-19**: split into `base_link.xacro` + `sensorsuite_front.xacro`.
- check_urdf.py: 25 links + 24 joints kept, all identical to the reference; dropped the
  arm (arm_base … gripper_*), drill, sample_box_1/2 and zed_mini. Root `chassis_link`. OK.
- robot_state_publisher (ros:humble-perception + xacro): loads. TF from `chassis_link`:
  `os_sensor` 0.285 −0.155 0.170; `zed2i_left_camera_frame_optical` 0.340 0.060 0.121,
  RPY −90 0 −90; `imu_link` 0.150 0 0.100. Wheel/steering frames have no TF (no
  `/joint_states`, issue #15), same as before.
- The bringup manager's path (`xacro.process_file`) renders the same file.
- Not yet tested on orintwo.
