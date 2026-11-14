# phone_standin

Try the phone app's Autonav page at home: the laptop stands in for orintwo, with a fake
world in place of SLAM, Nav2 and the bringup manager. Nothing here touches a robot.

`fake_world.py` (main domain): a latched `/rtabmap/map` (20 x 14 m room, walls, two
boxes, an unexplored corner, 5 cm cells), TF `map → chassis_link` for a fake robot that
drives straight to each goal at 0.5 m/s, `/plan` (straight line while navigating), a
`/navigate_to_pose` action server (feedback, cancel; goals inside an obstacle abort) and
`/bringup/go|stop` + latched `/bringup/status` (all stages ready / stopped).

## Run (laptop)

Next to the teleop stand-in (`teleop_mux`, `foxglove_bridge` on loopback DDS, phone
source; compose project `phonetest`), using the `navws/nav_relay_test` image from
`utils/nav_relay/run.sh`:

```bash
L=utils/rover_arming/cyclonedds_lo.xml   # loopback-only DDS
common=(--network host --ipc host --memory 1g -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  -e CYCLONEDDS_URI=file:///etc/cyclonedds.xml -e ROS_DOMAIN_ID=0 -e TELEOP_PHONE_DOMAIN=51
  -v $PWD/$L:/etc/cyclonedds.xml:ro -v $PWD/src/app_teleop:/workspace/app_teleop:ro
  -v $PWD/utils/phone_standin:/standin:ro)
docker run -d --name phonetest_fake_world "${common[@]}" navws/nav_relay_test \
  bash -c 'source /opt/ros/humble/setup.bash; python3 /standin/fake_world.py'
docker run -d --name phonetest_nav_relay "${common[@]}" -w /workspace navws/nav_relay_test \
  bash -c 'source /opt/ros/humble/setup.bash; python3 app_teleop/nav_relay.py --ros-args --params-file app_teleop/config/teleop.yaml'
```

Then point the app at the laptop's Wi-Fi IP.

## Results

- 2026-11-14: relay sent the 400x280 map (772 B PNG, 248 ms on the laptop); `/teleop/nav/state`
  showed pose (1, 1), `nav2_ready: true`, all bringup stages ready.
