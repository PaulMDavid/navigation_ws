# bag_replay

Stands in for the Ouster when it isn't running: replays a recorded bag on orintwo with
fresh timestamps, so TF ages and Nav2 tolerances look live.

- `player` plays the bag (`/ouster/points`, `/ouster/imu`, `/tf_static`) remapped to
  `/replay/*`, looping, at `RATE` × real time.
- `restamp.py` republishes them on the real names with `header.stamp = now`, patching
  the stamp in the raw CDR bytes instead of deserializing clouds.
- `rate.py 15 /topic ...` counts messages per topic; `show_status.py` prints the bringup
  manager's `/bringup/status`.

## Run (on orintwo)

    BAG=/mnt/ssd/pdavid/bags/lab_bag_Jun22_ouster RATE=1.0 docker compose up -d

## Last result

- 2026-10-24: at `RATE=1.0` the clouds arrive at **4.8 Hz, not 10**
  (`perf_compare` baseline-replay; restamp at 38 % CPU, player at 18 %). The replay
  can't feed real-rate input yet, so treat odometry rates measured with it as a lower bound.
