# Rover bring-up: power-on to driving with the phone

Log in to orintwo **over the cable** (step 1 changes its Wi-Fi, which would cut a Wi-Fi
session) and run the guided script:

```bash
ssh orintwo@192.168.1.210
cd /mnt/ssd/pdavid/navigation_ws
scripts/rover_bringup.sh
```

It walks you through two steps, shows every command before it runs it, and waits for Enter.

## Step 1: connect orintwo to your phone hotspot

Turn on the hotspot on your phone. The script then:

1. scans for Wi-Fi networks so you can find your hotspot (needs sudo: without it
   nmcli only shows the old cached list):
   ```bash
   sudo nmcli dev wifi list --rescan yes ifname wlP1p1s0
   ```
2. asks for your hotspot name (SSID) and connects; nmcli asks for the password:
   ```bash
   sudo nmcli --ask dev wifi connect "<your hotspot>" ifname wlP1p1s0
   ```
3. gives the hotspot priority over eduroam, so orintwo doesn't drop back to it:
   ```bash
   sudo nmcli con modify "<your hotspot>" connection.autoconnect yes connection.autoconnect-priority 20
   ```
4. prints orintwo's address on the hotspot. Enter it as the robot address in the phone app.

Only this step: `scripts/rover_bringup.sh wifi`.

## Step 2: start everything

The script runs:

```bash
scripts/phone_ctl.sh up       # teleop containers on orintwo, wheels on the rover, each checked
scripts/phone_ctl.sh camera   # ZED + camera for the app (first start can take ~6 min)
```

Every step prints `OK`, `!!` (warning, continues), or `XX` (stopped). Only this step:
`scripts/rover_bringup.sh up`.

## Drive

1. Open the teleop app on the phone (which is on its own hotspot) and set the robot
   address the script printed.
2. Wheels page (swipe right from Controls): press ARM **once**. It is a toggle; a second
   press switches back to crab steering.
3. Drive from Controls.

When done: `scripts/phone_ctl.sh stop`.

## If something fails

Logs of a step: `scripts/phone_ctl.sh log <preflight|teleop|rover_link|wheels|camera>`.

| symptom | fix |
| --- | --- |
| "logged in over orintwo's Wi-Fi" | log in over the cable: `ssh orintwo@192.168.1.210` |
| hotspot not in the scan list | phone hotspot on? Set it to 2.4 GHz, run `scripts/rover_bringup.sh wifi` again |
| connect fails | wrong password or out of range; run `scripts/rover_bringup.sh wifi` again |
| `rover_link` XX | ethernet cable to the rover, rover powered? `ping 192.168.1.230` |
| `wheels` XX: MD80 failed after 3 retries | check the CAN cable, power-cycle the motors, run `scripts/rover_bringup.sh up` |
| `wheels` XX: port held | an old tmux session holds the motors: `ssh rover@192.168.1.230 tmux kill-session -t wheels` |
| app freezes / no data | `docker restart app_foxglove_bridge_container` |
| camera XX | `docker restart app_zed2i_camera`; replug the ZED USB if it keeps failing |

## One-time setup (once per robot)

`phone_ctl.sh` reaches the rover with its own key and starts the wheels as a service.
Install both once, on orintwo over the cable (asks for the rover password once):

```bash
scripts/robot_setup/phone_link.sh
```
