# Rover bring-up: power-on to driving with the phone

Turn on your phone hotspot, log in to orintwo **over the cable** (connecting to the
hotspot changes orintwo's Wi-Fi, which would cut a Wi-Fi session), and type these 3
commands. `scripts/rover_bringup.sh` with no arguments prints the same list.

```bash
ssh orintwo@192.168.1.210
cd /mnt/ssd/pdavid/navigation_ws
```

1. Scan for networks. Your hotspot should be in the list; if it isn't, switch the phone
   hotspot to 2.4 GHz and run the scan again.
   ```bash
   sudo nmcli dev wifi list --rescan yes ifname wlP1p1s0
   ```
2. Connect to your hotspot. Replace `<your hotspot>` (both times) with its name exactly
   as in the list; nmcli then asks for the password. It scans again first: orintwo
   drops a phone hotspot from its list within seconds, and connect then fails with
   "No network with SSID ... found".
   ```bash
   sudo nmcli dev wifi rescan ifname wlP1p1s0 ssid "<your hotspot>" && sleep 3 && sudo nmcli --ask dev wifi connect "<your hotspot>" ifname wlP1p1s0
   ```
3. Start everything. It prints orintwo's hotspot address first and again at the end;
   enter that address in the phone app (`scripts/rover_bringup.sh ip` shows it any time).
   ```bash
   scripts/rover_bringup.sh up
   ```

Command 3 runs `scripts/phone_ctl.sh up` (teleop containers on orintwo, wheels on the
rover, each checked) and then `scripts/phone_ctl.sh camera` (ZED + camera for the app;
the first start can take ~6 min). Each step prints `OK`, `!!` (warning, continues) or
`XX` (stopped).

The scan needs sudo: without it nmcli only shows its old cached list.

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
| hotspot not in the scan list | phone hotspot on? Set it to 2.4 GHz, run the scan (command 1) again |
| connect: "No network with SSID … found" | the hotspot dropped out of the list; run command 2 again (it rescans first) |
| connect fails otherwise | wrong password, or phone hotspot not on 2.4 GHz / WPA2-Personal |
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
