# app_teleop

Decides what reaches the rover's `/cmd_vel`: Nav2, an operator, or nothing. An
operator is either the ground-station PC (over Zenoh) or a phone (over
foxglove_bridge), and one setting on orintwo, `TELEOP_SOURCE`, picks which.

```
ground PC ──Zenoh tcp/7447 (eduroam)──► app_zenoh_bridge ──► /teleop/ground/* ─┐
                                                                               ├► teleop_mux ─► /cmd_vel ─► morpheus_control (rover)
phone ──WebSocket 8765 (orintwo AP)──► app_foxglove_bridge ─► /teleop/phone/* ─┤
                                       (phone DDS domain 51)                   │
Nav2 velocity_smoother ─► /cmd_vel_auto ───────────────────────────────────────┘
```

No Wi-Fi link carries DDS: the ground station reaches the robot through Zenoh, the
phone through a WebSocket. DDS stays on orintwo and the wired network.

## Modes

| Mode | `/cmd_vel` gets |
| --- | --- |
| `autonomous` | Nav2 (`/cmd_vel_auto`); operators are ignored |
| `manual` | the active operator, clamped to `max_linear` / `max_angular`; Nav2 is ignored |
| `stop` | zero, until someone leaves this mode |

- Mode requests: `/teleop/<source>/set_mode` (`std_msgs/String`). `stop` is accepted from
  every source; the other modes only from the active one.
- **Deadman:** operators publish `/teleop/<source>/cmd_vel` at 10 Hz. A command older than
  `teleop_timeout` (0.5 s) counts as zero, so a dropped link stops the rover. Measured
  stop time: 0.41–0.45 s (`utils/teleop_link`).
- `/cmd_vel` is published at 20 Hz in every mode.
- `/teleop/state` (`std_msgs/String`, JSON, 5 Hz) is the robot's own report: mode, who set
  it, source, how long since each operator was last heard, limits, current output. Both
  operator UIs show this, not what they last sent.
- Changing the source puts the robot in `stop`. Boot starts in `initial_mode`
  (`autonomous`, so Nav2 drives as before).

Parameters: [`config/teleop.yaml`](config/teleop.yaml). The speed limits there are
placeholders until checked against `morpheus_control`.

Nav2's velocity smoother publishes `/cmd_vel_auto` instead of `/cmd_vel`, and
`behavior_server` (spin, backup) goes through the smoother instead of straight to
`/cmd_vel` (`stages_master.yaml`, `app_nav2/launch/navigation.launch.py`). Without this
container running, Nav2's commands reach nothing; the bringup's rover stage checks for it.

## Why the phone has its own DDS domain

foxglove_bridge 3.6.0 (current Humble release) ignores `client_topic_whitelist`: a
WebSocket client can make it publish any topic, `/cmd_vel` included. So
app_foxglove_bridge runs in DDS domain `TELEOP_PHONE_DOMAIN` (51), and teleop_mux is
the only node in both domains: it reads `/teleop/phone/*` there and mirrors
`/teleop/state` there. Whatever a client publishes stays in domain 51.
To give the phone more topics later, relay them into domain 51 (extend teleop_mux, or a
zenoh-bridge-ros2dds pair with an allowlist).

## Command source

`TELEOP_SOURCE` lives in `/etc/navws/teleop.env` on orintwo, next to the access point
password (neither is in the repo; `scripts/robot_setup/apply.sh` creates the file and
installs `navws-teleop.service`, which applies it at boot).

| | `ground` (default) | `phone` |
| --- | --- | --- |
| orintwo Wi-Fi | eduroam (client) | access point `orintwo-teleop`, 10.42.0.1/24 |
| who drives in manual | ground-station PC, Zenoh | phone app, foxglove_bridge |
| containers | app_teleop, app_zenoh_bridge | + app_foxglove_bridge, app_teleop_phone |

```bash
# on orintwo, over the wired link (192.168.1.210), never over Wi-Fi:
sudo scripts/teleop_source.sh phone     # save + apply now (or reboot)
sudo scripts/teleop_source.sh ground
scripts/teleop_source.sh status
```

If the access point fails to come up, `phone` falls back to `ground` for that boot so the
robot stays reachable over eduroam. `scripts/wifi_mode.sh ap|client|status` does the
Wi-Fi part alone.

Live, without restarting anything: `ros2 param set /teleop_mux source phone`.

## Using it

- **Phone:** join `orintwo-teleop`, open `http://10.42.0.1:8080` in Chrome, *Add to Home
  screen*. See `app_teleop_phone/README.md`.
- **Ground PC:** the Teleop panel in `groundstation_navigation`'s bringup GUI (W/S/A/D,
  space = stop). Over eduroam set `GS_LINK=zenoh` and `ROBOT_IP` in its `.env`.

## Tests

`utils/teleop_link/`: the laptop stands in for orintwo and both links are driven
end to end, including the deadman and the bridge loophole.
