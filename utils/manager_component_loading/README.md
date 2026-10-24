# manager_component_loading

Checks that `app_bringup_manager` can drive a component container: load a composable
node with parameters from a YAML file, gate the stage on its checks, and unload it again
on stop, without restarting the container.

## Run

From the laptop: `./run.sh`. It starts a bare `component_container` on orintwo (from the
robot_state_publisher image), restarts the manager with `stages_test.yaml`, presses go and
stop, prints `ros2 component list` after each, then puts the manager back on its normal
stages. Test files go to `app_bringup_manager/data/` on the robot, which syncs never
touch, so a sync running at the same time can't pull them away mid-test.

## Results

**2026-10-24**: pass. `/test/test_rsp` loaded with `robot_description` from
`rsp_test.yaml`, stage ready after 0 s (node in graph + TF `test_base → test_link`), and
gone from the container after stop while the container kept running.

Bugs this test found in the manager, fixed:
- LoadNode needs an absolute namespace (`/test`); `test` fails with a remap parse error.
- A missing params file crashed the whole bringup instead of failing the one stage.
