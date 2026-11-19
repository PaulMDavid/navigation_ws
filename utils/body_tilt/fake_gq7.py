#!/usr/bin/env python3
"""Fake GQ7 for looking at the body tilt in RViz: /imu/data (frame imu_link) with the
body pitching as mean + amp * sin(2 pi t / period), still otherwise (accelerometer = g).
ROS pitch convention: negative = nose up (the rover usually tips back down, front up).

usage: fake_gq7.py [mean_deg=-8] [amp_deg=10] [period_s=8] [enu|ned]
"""
import math
import sys
import time

import rclpy

from test_body_tilt import Harness


def main():
    mean, amp, period = (float(a) for a in (sys.argv[1:4] + ['-8', '10', '8'][len(sys.argv[1:4]):]))
    frame = sys.argv[4] if len(sys.argv) > 4 else 'enu'
    rclpy.init()
    h = Harness(frame)
    t0 = time.time()
    while rclpy.ok():
        p = math.radians(mean + amp * math.sin(2 * math.pi * (time.time() - t0) / period))
        h.send(p, 0.4)
        rclpy.spin_once(h, timeout_sec=0.01)


if __name__ == '__main__':
    main()
