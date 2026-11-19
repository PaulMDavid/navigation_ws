#!/usr/bin/env python3
"""Fake wheels_cpp for RViz: /Motor_pos at 20 Hz, steering swinging +-amp (Ackermann-ish:
front and rear opposite), drive motors rolling at `speed` m/s forward. Like wheels_cpp,
the right-side drive motors (22, 24) turn the other way for forward motion.

usage: fake_motors.py [steer_amp_rad=0.4] [speed_mps=0.3]
"""
import math
import sys
import time

import rclpy
from std_msgs.msg import Float64MultiArray

R = 0.125  # wheel radius, wheels_cpp


def main():
    amp = float(sys.argv[1]) if len(sys.argv) > 1 else 0.4
    speed = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    rclpy.init()
    node = rclpy.create_node('fake_motors')
    pub = node.create_publisher(Float64MultiArray, '/Motor_pos', 50)
    t0 = time.time()
    while rclpy.ok():
        t = time.time() - t0
        s = amp * math.sin(2 * math.pi * t / 6)
        w = speed / R * t
        pub.publish(Float64MultiArray(data=[s, s, -s, -s, w, -w, w, -w]))
        time.sleep(0.05)


if __name__ == '__main__':
    main()
