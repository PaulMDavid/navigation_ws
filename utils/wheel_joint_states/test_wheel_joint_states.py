#!/usr/bin/env python3
"""End-to-end check of app_wheel_joint_states with robot_state_publisher.

Needs running (same ROS_DOMAIN_ID): robot_state_publisher with the xacro model and
wheel_joint_states_node. Publishes /Motor_pos the way wheels_cpp does (8 MD80 positions,
rad: steer FL FR RL RR, drive FL FR RL RR), then checks
- nothing on /joint_states before /Motor_pos, and none for a /Motor_pos with a NaN or
  the wrong number of values;
- /joint_states: shafts 0, steering = motor value, drive = motor value with the right
  side (FR, RR) negated;
- TF: each steering/wheel link is turned about its joint axis by exactly that angle
  (compared with the pose at all-zero motor positions).

usage: test_wheel_joint_states.py
"""
import math
import sys
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray
from tf2_ros import Buffer, TransformListener

JOINTS = [  # (joint, parent link, child link, sign), /Motor_pos order
    ('steering_fl_joint', 'strut_fl_link', 'steering_fl_link', 1),
    ('steering_fr_joint', 'strut_fr_link', 'steering_fr_link', 1),
    ('steering_rl_joint', 'strut_rl_link', 'steering_rl_link', 1),
    ('steering_rr_joint', 'strut_rr_link', 'steering_rr_link', 1),
    ('wheel_fl_joint', 'steering_fl_link', 'wheel_fl_link', 1),
    ('wheel_fr_joint', 'steering_fr_link', 'wheel_fr_link', -1),
    ('wheel_rl_joint', 'steering_rl_link', 'wheel_rl_link', 1),
    ('wheel_rr_joint', 'steering_rr_link', 'wheel_rr_link', -1),
]
MOTORS = [0.30, -0.20, 0.10, -0.40, 1.00, 2.00, -0.50, 0.70]


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2)


class Harness(Node):
    def __init__(self):
        super().__init__('wheel_js_test')
        self.pub = self.create_publisher(Float64MultiArray, '/Motor_pos', 50)
        self.js = None
        self.n_js = 0
        self.create_subscription(JointState, '/joint_states', self.on_js, 50)
        self.buf = Buffer()
        self.tfl = TransformListener(self.buf, self)

    def on_js(self, m):
        self.js = dict(zip(m.name, m.position))
        self.n_js += 1

    def play(self, data, secs):
        end = time.time() + secs
        while time.time() < end:
            if data is not None:
                self.pub.publish(Float64MultiArray(data=data))
            rclpy.spin_once(self, timeout_sec=0.02)

    def rot(self, parent, child):
        r = self.buf.lookup_transform(parent, child, rclpy.time.Time()).transform.rotation
        return (r.w, r.x, r.y, r.z)


def main():
    rclpy.init()
    h = Harness()
    bad = 0
    for label, data in (('no /Motor_pos', None), ('NaN in /Motor_pos', [0.0] * 7 + [math.nan]),
                        ('7 values', [0.0] * 7)):
        h.play(data, 1.5)
        ok = h.n_js == 0
        bad += not ok
        print(f'{label:18} -> {h.n_js} /joint_states  {"OK" if ok else "FAIL"}')
    h.play([0.0] * 8, 2.0)
    zero = {j: h.rot(p, c) for j, p, c, _ in JOINTS}
    h.play(MOTORS, 2.0)
    for name in ('shaft_left_joint', 'shaft_right_joint'):
        ok = h.js is not None and abs(h.js.get(name, 1.0)) < 1e-12
        bad += not ok
        print(f'{name:18} js {h.js.get(name) if h.js else None}  {"OK" if ok else "FAIL"}')
    for (j, p, c, sign), m in zip(JOINTS, MOTORS):
        want = sign * m
        got_js = h.js.get(j) if h.js else None
        q0, q1 = zero[j], h.rot(p, c)
        d = qmul((q0[0], -q0[1], -q0[2], -q0[3]), q1)   # child turn in its own zero frame
        ang = 2 * math.atan2(d[3], d[0])                 # about the joint's z axis
        off_axis = math.hypot(d[1], d[2])
        ok = got_js is not None and abs(got_js - want) < 1e-9 and \
            abs(math.remainder(ang - want, 2 * math.pi)) < 1e-4 and off_axis < 1e-6
        bad += not ok
        print(f'{j:18} motor {m:+.2f} -> js {got_js:+.3f}, TF {ang:+.4f} rad about z  '
              f'{"OK" if ok else "FAIL"}')
    print('OK' if not bad else f'FAIL ({bad})')
    rclpy.shutdown()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
