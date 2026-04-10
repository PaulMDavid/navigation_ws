# Aruco Detector – Quick Verification Guide

## 1. Start the ZED camera first
The aruco detector subscribes to ZED topics, so the camera must be running.
```bash
cd navigation_ws/src
docker compose up app_zed2i_camera
```

## 2. Start the aruco detector
```bash
docker compose up app_aruco_detector --build
```
Expected startup log:
```
[INFO] [aruco_detector]: Subscribing to camera_info: /zed2i/zed_node/rgb/color/rect/camera_info
[INFO] [aruco_detector]: Subscribing to image: /zed2i/zed_node/rgb/color/rect/image/compressed
```
Then, once a frame arrives:
```
[INFO] [aruco_detector]: Camera intrinsics received — fx=..., fy=..., cx=..., cy=...
```
If you see the "Waiting for camera_info…" warning repeated, the ZED camera is not publishing (step 1 failed).

## 3. Verify the ZED topics exist (from host or another container)
```bash
ros2 topic list | grep zed2i
```
You should see, among others:
- `/zed2i/zed_node/rgb/color/rect/image/compressed`
- `/zed2i/zed_node/rgb/color/rect/camera_info`

Check they are actively publishing:
```bash
ros2 topic hz /zed2i/zed_node/rgb/color/rect/image/compressed
```

## 4. Check for detections
```bash
ros2 topic echo /aruco_detections
```
Hold a **DICT_5X5_100** marker (0.15 m printed size) in front of the camera.  
You should see messages with `id`, `pose`, and `corners` fields populated.

If the topic exists but is empty, check:
- The marker is a valid **5×5** ArUco (not 4×4 or AprilTag).
- The printed marker size matches `marker_size: 0.15` in `config/params.yaml`.
- Lighting is adequate and the marker is not blurry.

## 5. Quick config reference (`config/params.yaml`)
| Parameter | Value | Notes |
|---|---|---|
| `aruco_dict` | `DICT_5X5_100` | Must match the physical markers used |
| `marker_size` | `0.15` | Metres – affects pose estimation accuracy |
| `image_topic` | `/zed2i/zed_node/rgb/color/rect/image/compressed` | |
| `camera_info_topic` | `/zed2i/zed_node/rgb/color/rect/camera_info` | |
