# record

Tests the phone's bag recording (issue #29): `scripts/record/record_drive.sh` (reached as
`phone_ctl.sh record …`), its helpers `record_helper.py` (presets, silent list, bag info) and
`record_watch.py` (runs beside the recorder), the `topics` check of
`src/app_teleop/phone_probe.py`, and `scripts/record/presets.yaml`. No robot involved.
Uses the image and fakes of `utils/phone_ctl` (fake docker learned `run`/`start`/`stop`/`kill`
and `fakes/fake_recorder`).

- `test_record.py` (fakes, no ROS): every line JSON with `step/state/reason/t`, `t` rising,
  final `{"done", "ok"}`; covers:
  - `presets`: groups/presets/quiet_ok lines; `drive` is the default and contains all 48
    topics of the 2026-11-14 drive bag plus `/robot_description`; `minimal` has no
    image/camera_info topics; `lidar` = drive + `/ouster/points`, `/ouster/imu`; a topic is
    in one group only;
  - `start`: the `docker run` flags (`--rm --init`, host network/IPC, DDS file, `/bags`,
    image `zed2i_rec:2026-11-14`, domain 0) and the recorder command (overlay on
    AMENT_PREFIX_PATH/LD_LIBRARY_PATH, `-s sqlite3`, zstd file mode, 2 GB chunks, QoS file,
    record_watch.py); GQ7 + zed2i_rec started only when down, `app_zed2i_camera` stopped
    before `zed2i_rec`; sensor check with an 8 s window on the right topics per preset;
    refused while recording, below 20 GB free (19.999 fails, 20.000 passes), no NVMe;
    silent sensors → `warn` and records anyway; app_teleop down → `warn`; `+/topic`
    `-/topic`; recorder crash / `docker run` failure → `fail`; lock → `busy` (75);
  - argument and character checks via `SSH_ORIGINAL_COMMAND` (exit 64, nothing runs);
  - `status`: not recording (one line), `once` fields and types, silent topics (quiet_ok
    ones never), no verdict while the watcher is younger than the window, streaming with
    rising `t`, ending when the recording stops, unclosed bag dirs;
  - `stop`: ok with size/duration/messages, idempotent, no metadata → `fail` with the
    reindex line, timeout → `fail` without killing, then a second stop succeeds;
  - `topics`: lines passed through, `null` rates kept, app_teleop down → `fail`.
- `test_record_ros.py` (real ROS on loopback DDS, domain 83): `phone_probe.py topics`
  against publishers (50 Hz Imu, 10 Hz 20 kB CompressedImage, 2 Hz String, latched
  /tf_static): Hz and MB/s, a missing topic, bounded time; then `record_drive.sh` with the
  fake docker running the **real** recorder command (`ros2 bag record` + record_watch.py)
  and the real probe: start → status (`silent` empty, then `/slow` after it stops) → stop →
  `metadata.yaml` says sqlite3, zstd, FILE, `.db3.zstd` files, `/tf_static` recorded once
  (QoS override); and a power cut (SIGKILL) → `status` lists the bag in `unclosed` →
  `ros2 bag reindex -s sqlite3` writes the metadata.

Not covered: the ZED image `zed2i_rec` itself (the test runs the command in
`ros:humble-ros-base`), the microstrain overlay, real containers/compose, the GQ7/ZED/rover,
eno1 DDS, the phone. That is the hardware checklist in `src/app_teleop/README.md`
("Recording from the phone").

## Run

```bash
systemd-run --user --scope -p MemoryMax=8G ./run.sh       # all (≈85 s after the image is built)
./run.sh shell                                             # fakes only
./run.sh ros                                               # real recorder / probe / watcher
./run.sh test_record.py -k stop                            # any pytest args
```

Runs in the `navws/phone_ctl_test` container (2 GB cap, `/bags` = 512 MB tmpfs); the host
needs no ROS. Output goes to `results/<date>_pytest.txt`.

## Last results

**2026-11-14: 50/50 PASS** (46 shell with fakes, 4 ROS), three runs in a row, ≈84 s each.
`results/2026-11-14_pytest.txt`. `utils/phone_ctl` after the shared-lib refactor: 69/69.
