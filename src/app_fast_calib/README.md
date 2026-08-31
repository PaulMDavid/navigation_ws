# app_fast_calib

Runs [FAST-Calib](https://github.com/hku-mars/FAST-Calib) (hku-mars) — target-based
LiDAR-camera extrinsic calibration in ~1 second, no initial guess needed. It's a ROS1
(catkin) tool, so unlike the rest of this workspace it does not join the ROS 2 graph; it's
a standalone offline utility that reads one recorded rosbag + one image per scene and
writes out the extrinsics.

`FAST-Calib/` is a git submodule pinned to upstream. Everything else (Livox-SDK,
livox_ros_driver, the catkin build) happens inside the container.

## Using the docker container

```bash
cd app_fast_calib
docker compose build
docker compose up -d
docker compose exec ros bash
```

Inside the container the workspace is already built (`postcreatecommand.sh` runs
`catkin_make` on start) and sourced. `FAST-Calib/` on the host is mounted at
`/workspace/catkin_ws/src/fast_calib` — edit config on the host, it's live in the
container; nothing gets baked into the image.

Run a single-scene calibration:

```bash
roslaunch fast_calib calib.launch
```

Run the multi-scene joint calibration (after you have at least 3 single-scene results):

```bash
roslaunch fast_calib multi_calib.launch
```

Both default to opening rviz, which needs `DISPLAY` set and (usually) `xhost
+local:docker` run on the host first. Pass `rviz:=false` to skip it.

To rebuild after changing `qr_params.yaml` or the source, just restart the container
(`docker compose restart`) — the entrypoint rebuilds every time.

## Recording data

FAST-Calib does not subscribe live — `calib.launch` reads one static `.bag` and one
`.jpg`/`.png` per scene, paths set in `FAST-Calib/config/qr_params.yaml`
(`bag_path`, `image_path`). So "recording" means: point the sensor rig at the
calibration target, and capture exactly one LiDAR scan and one photo, per scene.

1. **Get or build the target.** CAD model is linked from the [FAST-Calib
   README](https://github.com/hku-mars/FAST-Calib#3-run-on-your-own-sensor-suite). It's
   the same board used by `velo2cam_calibration` — an AprilTag/ArUco-cornered board with
   4 circular cutouts.

2. **Record one LiDAR scan** on the topic your sensor publishes (e.g. `/livox/lidar` or
   `/ouster/points` — set as `lidar_topic` in `qr_params.yaml`). This rover runs ROS 2, so
   record it the normal way:

   ```bash
   ros2 bag record -o calib_data/<scene_name>_ros2 /ouster/points
   ```

   A short recording is fine — the tool only needs one message.

   **This produces a ROS 2 bag, which FAST-Calib (ROS1) cannot read directly** — its
   `rosbag.Bag()`/`rosbag::Bag` reader expects the old rosbag1 container format, and a
   ROS 2 bag is a different sqlite3/mcap format entirely. Convert it with
   [`rosbags`](https://ternaris.gitlab.io/rosbags/) (pure Python, no ROS install needed,
   run via `uvx` so there's nothing to set up):

   ```bash
   uvx --from rosbags rosbags-convert \
     --src calib_data/<scene_name>_ros2 \
     --dst calib_data/<scene_name>.bag \
     --src-typestore ros2_humble
   ```

   (If recording with native ROS1 tooling is ever an option instead, skip the conversion:
   `rosbag record -O calib_data/<scene_name>.bag /ouster/points --duration=2`.)

3. **Capture one image** from the camera, in the same pose, saved as
   `calib_data/<scene_name>.jpg` (or `.png`). Grab a frame from the ROS 2 camera topic
   (e.g. via the ground station, or `ros2 run image_view image_saver`) and copy it in.

4. **Drop both files into `FAST-Calib/calib_data/`** (this directory is bind-mounted, so
   just copy them in from the host — no need to go through the container).

5. **Point `qr_params.yaml` at them**: set `bag_path` and `image_path` to the new files,
   and fill in your camera's intrinsics (`fx/fy/cx/cy/k1/k2/p1/p2`) and the
   `x_min/x_max/y_min/y_max/z_min/z_max` distance filter so only the target board
   survives the crop. Use `FAST-Calib/scripts/distance_filter_tool.py` to sanity-check
   the filter bounds against your scan before running the real calibration.

6. For **multi-scene** calibration, repeat steps 2-5 three times with the target facing
   forward, left, and right (see the placement diagram in the upstream README), running
   `calib.launch` once per scene, then `multi_calib.launch` at the end.

Results land in `FAST-Calib/output/` on the host.

## Sample datasets (tested end to end)

Upstream provides sample data on Google Drive:
[single-scene (Mid360/Avia/Ouster)](https://drive.google.com/drive/folders/1W87Dx3MUuPhTpCLvaavWqNUJZV03yU6L),
[multi-scene (Avia)](https://drive.google.com/drive/folders/1g__plgFqp5tsk-TY7Ioh4RXru62AdLmr).

`gdown` can enumerate the folders (avia/mid360/ouster, each with numbered `.bag`/`.png`
pairs plus a `camera_pinhole.yaml`) and small files download fine, but every `.bag` file
hits Google Drive's shared-quota error ("Too many users have viewed or downloaded this
file recently... try again in 24 hours"). That's Drive rate-limiting the file itself, not
this app — the fix is downloading through a browser instead, which isn't quota-limited the
same way.

That's what actually got this tested: the `ouster/` set (`11.bag`, `22.bag`, `33.bag` +
matching images + `camera_pinhole.yaml`) was downloaded via browser as two split zips,
extracted into `FAST-Calib/calib_data/ouster/`, and `qr_params.yaml` was pointed at
`ouster/11.bag` / `ouster/11.png` with the ouster intrinsics from `camera_pinhole.yaml`
(already filled in — see the file). Ran inside the container:

```bash
roslaunch fast_calib calib.launch rviz:=false
```

Result: the full pipeline runs — loads the bag (30.9M points, all 118 lidar messages
merged, not just one scan), depth-filters, RANSAC-fits a plane, extracts edge points,
clusters, finds 4 circle candidates — but scene 11's candidates didn't match the target's
expected geometry, so the SVD-based extrinsic solve degenerated (garbage matrix in the
output, not a crash).

I dug into *why* rather than just calling it a tuning issue: I pulled the raw cloud out of
the bag directly (`sensor_msgs.point_cloud2` + numpy) and it spans roughly x:[-28, 16],
y:[-23, 10] meters — this Ouster recording is a full 360-degree scan of a real room, not a
tight shot of just the board. The upstream comment-hint box
(`x:[1.5,5] y:[-0.5,3] z:[-0.8,2]`) and a second box I derived from clustering
high-reflectivity points (`x:[3.5,7] y:[-1,2] z:[-1.5,2]`) both landed on a wall/floor —
RANSAC returned planes of 655k and 146k points respectively, both far too large for a
~0.5x0.4m board. Reflectivity alone doesn't cleanly separate the board from other
reflective surfaces in this room (the room has a big high-reflectivity blob right at the
sensor's own near-range too, likely the mount). So the honest state: this needs a human
to actually look at the point cloud and click near the board — there's no shortcut through
the data I could find in the time I spent on it.

That's exactly what `scripts/distance_filter_tool.py` is for, so I made sure it's usable
rather than stopping at "run this yourself": added `open3d` to the Dockerfile (it wasn't
there), and confirmed inside the container that the script's non-interactive half works —
it correctly detects the bag's message type, reads all 118 `/ouster/points` messages, and
writes a merged intensity-tagged PCD (1.7GB for this bag). The interactive point-picking
window past that point needs a real display and a human clicking — I have neither from
here, so I can't finish that step directly.

I did try a scripted substitute for the click, rather than stopping at "you need a GUI":
merged the full 30.9M-point accumulated cloud, RANSAC-stripped the 4 dominant room-scale
planes (floor, ceiling, two walls), then DBSCAN-clustered what was left and kept clusters
whose planar bounding box was close to the board's known size
(`delta_width_circles`/`delta_height_circles` → ~0.64m diagonal). That produced a ranked
list of candidate locations across the room. I validated the top 10 (2 earlier hand
guesses + 8 from clustering) against the *real* `fast_calib` binary, not just eyeballing
the numbers — none converged to a valid 4-circle match. Best lead:
`x:[4.22,5.18] y:[-0.29,0.41] z:[-1.04,-0.39]` found 11 circle-like features (need exactly
4 matching the target's layout) — something real is plausibly nearby, but I couldn't
narrow it further without seeing the cloud. That's the actual ceiling of what's
automatable here; the rest needs eyes on the data.

**Update: found the board, still didn't crack it.** Asked "can't you screenshot it" — fair
question, and it unlocked more than the room-scale renders did: I looked at
`calib_data/ouster/11.png` directly (I can read images, just not interact with a live
GUI). It's a lobby (station signage in the background reads "深圳北 SHENZHENBEI" —
Shenzhen North), and the board is right there in frame, standing on a pedestal in front of
a large dark reflective glass wall. Measuring the board's circle spacing in the photo
against the known `delta_width_circles`/`delta_height_circles` (0.5m/0.4m) and the camera
intrinsics gives a distance of ~2.5m — nowhere near the 4-5m region every earlier attempt
searched. That alone explains why nothing converged before.

First correction attempt: cross-referencing against the plane-stripped clustering turned
up what looked like a strong size match — a fragment at `(0.76, 1.83, 0.04)`, diagonal
0.637m vs. the target's circle-spacing diagonal of 0.640m. That match was wrong in a way
worth calling out: 0.64m is the distance *between circle centers*, not the board's actual
footprint. Measuring the board's outer edges in the photo (not just the circles) at the
~2.5m distance gives a real panel size of roughly **1.4m x 1.1m** — the "match" I'd found
was a small, unrelated fragment, not the board.

Redid it at the right scale: a box roughly matching that true footprint
(`x:[0,1.3] y:[1.4,2.6] z:[-0.6,0.6]`) does consistently find exactly 4 circle-like
blobs (not 12, not a random count) — sounded promising. But pulling their actual 3D
coordinates off the `/center_z0_cloud` topic and checking pairwise distances killed it:
a real board should show two ~0.5m edges, two ~0.4m edges, two ~0.64m diagonals. These
four are 0.10, 0.10, 0.26, 0.26, 0.60, 0.80m apart — three of them nearly coincident,
one far outlier. Not a rectangle. Confirmed noise, not the target, most likely reflections
off the glass wall the board is standing in front of in the photo.

So: real progress (board's true distance corrected from ~4-5m to ~2.5m; general direction
narrowed from the whole room to one corner) but the exact crop remains unresolved — every
candidate found in that neighborhood turned out to be glass-reflection noise when checked
against the real geometry, not guessed at. Separating the board's own returns from a glass
wall directly behind it is exactly the kind of judgment call `distance_filter_tool.py`'s
interactive picker exists for; I don't have a way to make that call blind.

**Final update: it's calibrated.** The container's `distance_filter_tool.py` never worked —
its GL driver doesn't support this host's GPU (`libGL error: failed to load driver: iris`),
producing a broken window. The fix was running the picker natively on the host instead,
outside Docker entirely, since it doesn't actually need ROS — only the already-exported PCD:

```bash
uv venv --python 3.11 /path/to/venv   # Open3D has no wheel for very new Python versions
uv pip install --python /path/to/venv/bin/python open3d
env -u WAYLAND_DISPLAY DISPLAY=:0 /path/to/venv/bin/python pick_board.py  # force XWayland;
  # native Wayland GLFW backend failed here. Also: vis.run() rendered nothing on this
  # setup — drive the loop manually instead:
  #   while vis.poll_events(): vis.update_renderer()
  # and call vis.reset_view_point(True) + set point_size/background_color, or you get an
  # all-black window even with real geometry loaded.
```

One more quirk: `VisualizerWithEditing` segfaults after every single Shift+click on this
host — reliably, not intermittently. Workaround: relaunch for each pick. Since each click
prints `[Open3D INFO] Picked point #... (x,y,z)` to stdout immediately, nothing is lost —
one relaunch-and-click cycle per point, four times, reading the coordinates back out of
the log.

Doing that (on the solid panel surface, not the holes — a hole is an absence of points,
there's nothing there to click) gave 4 real coordinates that fit a plane to within **2.2cm**
and spanned 1.1m — matching the board's real width from the photo. Built a box around them
(`x:[2.2,2.9] y:[-0.9,0.7] z:[-0.6,0.7]`, already in `qr_params.yaml`) and ran it for real:

```
[Result] RMSE: 0.0013 m
Rcl: [-0.014625, -0.999890, -0.002428,
      -0.022608,  0.002758, -0.999741,
       0.999637, -0.014566, -0.022646]
Pcl: [ 0.050039,  0.164900, -0.013942]
```

1.3mm RMSE, and a translation of (5cm, 16.5cm, -1.4cm) — small and physically sensible for
a camera mounted near a LiDAR on the same rig, not a garbage fit. `Rcl` is a valid rotation
matrix (orthonormal rows). This is a genuine, working calibration of `ouster/11.bag`.

**Recap of the whole trail**, since it's a useful map if you hit the same wall on a
different scene: generic distance-filter defaults are wrong for room-scale mechanical
LiDAR scans → photo-based distance triangulation narrows the search correctly but isn't
precise enough alone → automated plane-stripping/clustering finds candidates but can't
distinguish real target from noise/reflections without ground truth → the only thing that
actually worked was a human looking at the real 3D data and clicking on it, which needed
fixing three separate rendering bugs (container GL driver, Wayland GLFW backend, missing
view-reset) plus a workaround for a crash-on-pick bug, to get from "you need a GUI" to an
actual working pick.

The two downloaded zip files are sitting in the repo root
(`ouster-20260831T150817Z-1-00{1,2}.zip`, ~3.5GB) — not tracked by git, already extracted
into `calib_data/` which is gitignored inside the submodule. Safe to delete once you don't
need them as a backup; ask if you'd like me to remove them.
