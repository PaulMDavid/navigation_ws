# Rover bring-up: from power-on to driving with the phone

Two steps, both run on **orintwo** from a laptop on the wired link:

1. **Hotspot**: orintwo turns its Wi-Fi into the access point `orintwo-teleop`.
2. **Bring-up**: one script starts the teleop containers on orintwo and the wheels
   controller on the rover, checks each part, and then starts the camera.

After that you join the hotspot with the phone, open the app, arm, and drive.

> First time on these robots? Do [One-time setup](#one-time-setup) first. It is
> needed once per robot, not before every drive.

---

## Before you start

- Rover and orintwo are powered, and the ethernet cable between them is plugged in.
- Your laptop is on the same wired switch with a `192.168.1.x` address (the plan is
  `.105`; see the IP list below).
- Log in to orintwo **over the cable**, never over Wi-Fi. Step 1 switches orintwo's
  Wi-Fi, and the script refuses to run from a Wi-Fi session because the switch would cut it.

```bash
ssh orintwo@192.168.1.210
cd /mnt/ssd/pdavid/navigation_ws
```

| machine | wired IP | user |
| --- | --- | --- |
| orintwo (Jetson, runs navigation + teleop) | 192.168.1.210 | `orintwo` |
| rover (wheels controller, MD80 motors) | 192.168.1.230 | `rover` |
| laptop | 192.168.1.105 | |

---

## Step 1: switch orintwo to hotspot

```bash
sudo scripts/teleop_source.sh phone
```

This
- saves `TELEOP_SOURCE=phone` in `/etc/navws/teleop.env`, so orintwo also comes up as a
  hotspot after a reboot,
- brings up the access point `orintwo-teleop` on `10.42.0.1` (the password is
  `AP_PASSWORD` in `/etc/navws/teleop.env`),
- starts the teleop containers in phone mode.

If the access point doesn't come up within 30 s, the script goes back to eduroam and says
so. Check it with:

```bash
scripts/teleop_source.sh status
```

You want `mode: AP` and `ssid: orintwo-teleop`.

---

## Step 2: bring everything up

```bash
scripts/phone_ctl.sh up && scripts/phone_ctl.sh camera
```

`up` runs four steps and stops at the first one that fails:

| step | what it does | green when |
| --- | --- | --- |
| `preflight` | checks orintwo | `/mnt/ssd` mounted, DDS config present, `/` below 95 % (95–99 % is a warning, 100 % fails) |
| `teleop` | `docker compose up` for app_teleop, app_foxglove_bridge, app_rover_arming, app_nav_relay | the mux reports `source: phone` |
| `rover_link` | ping + ssh to the rover | the rover answers |
| `wheels` | starts `rover-wheels.service` on the rover (morpheus_control). If an MD80 fails to come up, it runs `mdtool encoder <id>` and relaunches, up to 3 times | all MD80s added, `/joy` + `/cmd_vel` subscribed |

`camera` then starts the ZED and the camera relay for the app. It's green once the phone
image arrives at ≥ 8 Hz. **The first ZED start after an image rebuild takes about 6 min**
while it optimizes its depth model; later starts take seconds.

Each line of output is JSON. Read the `step`, `state` and `reason` fields. The last line
is `{"done": true, "ok": true}` when everything is up. To check again later without
starting anything:

```bash
scripts/phone_ctl.sh status
```

---

## Drive

1. On the phone, join Wi-Fi `orintwo-teleop`.
2. Open the teleop app. First time only: install it from `http://10.42.0.1:8080` in
   Chrome. The app's robot address is `10.42.0.1`.
3. Arm on the Wheels page (swipe right from Controls), then drive from Controls.
   Press ARM **once**: it is a toggle, and a second press switches the steering back to
   crab mode (issue #50).

---

## When you're done

```bash
scripts/phone_ctl.sh stop                  # wheels off, camera off, arming + nav relay off
sudo scripts/teleop_source.sh ground       # back to eduroam (also after reboots)
```

Run the second line only if orintwo should leave hotspot mode. If you leave it on
`phone`, orintwo starts as a hotspot after the next boot.

---

## If something fails

Show the last log lines of a step (`preflight`, `teleop`, `rover_link`, `wheels`, `camera`):

```bash
scripts/phone_ctl.sh log wheels
```

| symptom | fix |
| --- | --- |
| `teleop_source.sh` says the SSH session runs over Wi-Fi | log in over the cable: `ssh orintwo@192.168.1.210` |
| `AP_PASSWORD (8+ characters) must be set` | `sudoedit /etc/navws/teleop.env`, set `AP_PASSWORD=` |
| `preflight` warns that `/` is at 9x % | the root SD card is nearly full; bags go to `/mnt/ssd`. At 100 % nothing starts |
| `rover_link` fails | cable, rover powered? `ping 192.168.1.230`. If ssh fails, one-time setup is missing |
| `wheels`: `MD80 <id> failed to add after 3 retries` | check the CAN cable (the whole left side, 11/13/21/23, has dropped out before), power-cycle the motors, run `up` again |
| `wheels`: `start refused`, port held | an old `wheels` tmux session on the rover holds `/dev/ttyACM0`: `ssh rover@192.168.1.230 tmux kill-session -t wheels` |
| a wheel steers crooked | re-zero it: hand-align the wheel, then `scripts/phone_ctl.sh zero 14` (ids 11 FL, 12 FR, 13 RL, 14 RR) |
| app shows no data / freezes | `docker restart app_foxglove_bridge_container` (issue #51) |
| camera stays red | `docker restart app_zed2i_camera`; if the kernel log shows `uvcvideo … -71`, replug the ZED USB |
| rover root filesystem read-only | power-cycle the rover |

---

## One-time setup

Once per robot (already done is fine: every script is idempotent). From the laptop, sync
the repo to orintwo first if it isn't there (`scripts/sync_to_robot.sh`), then on orintwo
over the cable:

```bash
cd /mnt/ssd/pdavid/navigation_ws
sudo scripts/robot_setup/apply.sh          # DDS buffers, /etc/navws/teleop.env, boot unit
sudoedit /etc/navws/teleop.env             # set AP_PASSWORD (8+ characters)
scripts/robot_setup/phone_link.sh          # orintwo→rover key + rover-wheels.service on the rover
```

`phone_link.sh` asks for the rover's password and sudo once (for systemd linger). To also
allow the phone app's System page to run `up`/`stop` itself, pass the key the app shows
under "Show public key": `scripts/robot_setup/phone_link.sh phone.pub`.

After a change in `scripts/robot_setup/rover/`, copy it to the rover again with
`scripts/sync_to_robot.sh --rover-files`.

More detail: `src/app_teleop/README.md` (command source, phone link, every `phone_ctl.sh`
verb).
