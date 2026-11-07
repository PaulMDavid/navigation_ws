# gq7_rtk

Checks that the 3DM-GQ7 in `app_microstrain` tracks satellites on both antennas, gets
SAPOS Berlin RTK corrections over NTRIP, and resolves dual-antenna heading.

## Setup

- GQ7 connected with **two** USB cables: MAIN (MIP data, `...Sensor_0000_...`) and AUX
  (`...Sensor_2-00_...`, RTCM in / GGA out). The GQ7 only accepts corrections on AUX.
- SAPOS login in `/etc/navws/sapos.env` (see `src/app_microstrain/config/sapos.env.example`;
  on the laptop point `SAPOS_ENV` at a file outside the repo). One login per robot.
- Antennas with sky view. Indoors both receivers report `fix_type: 4` and 0 satellites.

## Run

    cd src && SAPOS_ENV=/path/to/sapos.env docker compose up app_microstrain
    # in another shell
    docker exec -it app_microstrain_container bash
    ros2 topic echo /mip/gnss_1/fix_info --field fix_type      # and gnss_2
    ros2 topic echo /nmea --field sentence                      # GGA going up to SAPOS
    ros2 topic hz /rtcm                                         # corrections coming down
    ros2 topic echo /mip/ekf/gnss_dual_antenna_status

Log line `[ntrip_client]: Connected to http://www.sapos-be-ntrip.de:2101/VRS_3_4G_BE`
means the login worked.

Values: receiver `fix_type` 0 = 3D, 3 = none, 4 = invalid, 5 = RTK float, 6 = RTK fixed.
Dual antenna `fix_type` 0 = none, 1 = float, 2 = fixed. `/mip/ekf/status` `filter_state`
4 = full navigation.

## Results

- 2026-10-27, laptop bench, antennas at a window (partial sky), placeholder lever arms,
  login `saposbe1179-2`, `VRS_3_4G_BE`: NTRIP connected, `/rtcm` ~5.7 msg/s, GGA uplink
  quality 5. Both receivers RTK float (19 / 17 satellites). Dual-antenna heading fixed,
  uncertainty 0.019 rad (1.1°). EKF full navigation, filter condition stable, no warnings.
  GNSS2 reached RTK fixed after ~3.5 min; GNSS1 stayed float (one brief dropout).
  21:31 GNSS2 lost its antenna (BIT `GNSS Antenna 2 Open`, 0 satellites): loose connector.
  After pressing it back in (21:35): both receivers RTK fixed (24-25 / 21-23 satellites),
  position 1σ 2.2 cm horizontal / 2.7 cm vertical, dual-antenna heading fixed ±0.9°.
  Remaining BIT flag `RTK Dongle Fault` is expected (corrections via AUX, no dongle).
