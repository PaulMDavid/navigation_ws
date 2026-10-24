# odom_rate_hang

Reproduces the orintwo freeze that appears when the odometry input rate goes up, and
records enough to say what ran out (memory, CPU, I/O, DDS) even if the Jetson locks up.

- `logger.sh start [label]` / `stop`: 1 Hz tegrastats, memory, per-container stats and
  DDS/UDP drop counters, appended and fsync'd to `/mnt/ssd/pdavid/logs/<run>/`, so the
  data written before a freeze survives the reboot.
- `step.sh [--hold 60] [--set 'cmd {}'] 1.0 1.5 2.0`: raises a knob step by step with
  markers in the run's `events.log`. Default knob is `bag_replay`'s `RATE`
  (1.0 = 10 Hz clouds).
- `mark.sh "text"`: adds a marker by hand.
- `summarize.py <run dir>`: per-step table (and plot); "max gap" is the longest stretch
  without a 1 Hz sample, i.e. a freeze seen from inside.

## Run (on orintwo)

    utils/odom_rate_hang/logger.sh start hang
    utils/odom_rate_hang/step.sh 1.0 1.5 2.0 2.5 3.0
    utils/odom_rate_hang/logger.sh stop
    python3 utils/odom_rate_hang/summarize.py /mnt/ssd/pdavid/logs/<run>

Run once with default kernel buffers and once after `scripts/robot_setup/apply.sh`.

## Last result

Not run yet. The harness was finished on 2026-10-24, but the bag replay only reaches
4.8 Hz (see `bag_replay`), so `RATE` steps don't yet reach the rates that hang.
