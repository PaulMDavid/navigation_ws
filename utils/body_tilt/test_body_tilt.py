#!/usr/bin/env python3
"""End-to-end check of app_body_tilt with robot_state_publisher.

Needs (already running, same ROS_DOMAIN_ID): robot_state_publisher with the xacro model
and app_body_tilt's body_tilt_node (orientation_frame auto). This script plays a fake
GQ7 on /imu/data (frame imu_link, mounted like imu_link in the URDF, i.e. no rotation):
first 2 s still and level so the node can decide ENU/NED, then a list of body pitches,
each held for 1.5 s with a random yaw. For each it reads TF chassis_link ->
drivetrain_link and checks the drivetrain is turned back by exactly the body pitch.

usage: test_body_tilt.py enu|ned
"""
import math
import random
import sys
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu
from tf2_ros import Buffer, TransformListener

G = 9.81
PITCHES_DEG = [0.0, -12.0, -5.0, 3.0, 15.0, -25.0]


def quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2)


def rot_y(a):
    return (math.cos(a / 2), 0.0, math.sin(a / 2), 0.0)


def rot_z(a):
    return (math.cos(a / 2), 0.0, 0.0, math.sin(a / 2))


def rotate_inv(q, v):
    """R(q)^T v."""
    w, x, y, z = q
    qc = (w, -x, -y, -z)
    r = quat_mul(quat_mul(qc, (0.0, *v)), q)
    return r[1:]


# ENU -> NED: x_n = y_e, y_n = x_e, z_n = -z_e (a 180 deg turn about (1,1,0)/sqrt2)
Q_NED_ENU = (0.0, math.sqrt(0.5), math.sqrt(0.5), 0.0)


class Harness(Node):
    def __init__(self, frame):
        super().__init__('body_tilt_test')
        self.frame = frame
        self.pub = self.create_publisher(Imu, '/imu/data', 50)
        self.buf = Buffer()
        self.tfl = TransformListener(self.buf, self)

    def send(self, pitch, yaw):
        q_enu = quat_mul(rot_z(yaw), rot_y(pitch))           # sensor -> ENU world
        acc = rotate_inv(q_enu, (0.0, 0.0, G))               # still: +g along up
        q = q_enu if self.frame == 'enu' else quat_mul(Q_NED_ENU, q_enu)
        m = Imu()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = 'imu_link'
        m.orientation.w, m.orientation.x, m.orientation.y, m.orientation.z = q
        m.linear_acceleration.x, m.linear_acceleration.y, m.linear_acceleration.z = acc
        self.pub.publish(m)

    def play(self, pitch, yaw, secs):
        end = time.time() + secs
        while time.time() < end:
            self.send(pitch, yaw)
            rclpy.spin_once(self, timeout_sec=0.005)

    def drivetrain_pitch(self):
        t = self.buf.lookup_transform('chassis_link', 'drivetrain_link', rclpy.time.Time())
        r = t.transform.rotation
        sinp = 2 * (r.w * r.y - r.z * r.x)
        return math.asin(max(-1.0, min(1.0, sinp))), (r.x, r.z)


def main():
    frame = sys.argv[1]
    rclpy.init()
    h = Harness(frame)
    h.play(0.0, 0.3, 2.0)
    bad = 0
    for deg in PITCHES_DEG:
        yaw = random.uniform(-math.pi, math.pi)
        h.play(math.radians(deg), yaw, 1.5)
        got, (rx, rz) = h.drivetrain_pitch()
        got_deg = math.degrees(got)
        ok = abs(got_deg + deg) < 0.1 and abs(rx) < 1e-6 and abs(rz) < 1e-6
        bad += not ok
        print(f'{frame}: body pitch {deg:+6.1f} deg, yaw {math.degrees(yaw):+5.0f} -> '
              f'drivetrain {got_deg:+7.2f} deg {"OK" if ok else "FAIL"}')
    print('OK' if not bad else f'FAIL ({bad})')
    rclpy.shutdown()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
