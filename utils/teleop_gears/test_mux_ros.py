"""ROS-level check of teleop_mux with stick + gear input (#37) and angular_sign.

Runs against a live teleop_mux (see run_mux_test.sh): publishes /teleop/phone/* in the
phone domain like the app does, reads /cmd_vel and /teleop/state in the main domain.
Exit code 0 = all checks passed.
"""
import json
import os
import sys
import time

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String

PHONE = int(os.environ.get('TELEOP_PHONE_DOMAIN', '51'))
fails = []


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}  {detail}', flush=True)
    if not ok:
        fails.append(name)


ctx_main, ctx_phone = rclpy.Context(), rclpy.Context()
rclpy.init(context=ctx_main)
rclpy.init(context=ctx_phone, domain_id=PHONE)
main = Node('gears_test_main', context=ctx_main)
phone = Node('gears_test_phone', context=ctx_phone)

last = {'cmd': Twist(), 'state': {}}
main.create_subscription(Twist, '/cmd_vel', lambda m: last.__setitem__('cmd', m), 10)
main.create_subscription(String, '/teleop/state',
                         lambda m: last.__setitem__('state', json.loads(m.data)), 10)
stick_pub = phone.create_publisher(Twist, '/teleop/phone/stick', qos_profile_sensor_data)
gear_pub = phone.create_publisher(String, '/teleop/phone/gear', 10)
mode_pub = phone.create_publisher(String, '/teleop/phone/set_mode', 10)
params = main.create_client(SetParameters, '/teleop_mux/set_parameters')
ex_main = SingleThreadedExecutor(context=ctx_main); ex_main.add_node(main)
ex_phone = SingleThreadedExecutor(context=ctx_phone); ex_phone.add_node(phone)


def spin(secs, throttle=None, steer=0.0):
    """Spin both nodes for secs; publish the stick at 20 Hz if throttle is given."""
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if throttle is not None:
            t = Twist()
            t.linear.x, t.angular.z = float(throttle), float(steer)
            stick_pub.publish(t)
        stop = time.monotonic() + 0.05
        while time.monotonic() < stop:
            ex_main.spin_once(timeout_sec=0.005)
            ex_phone.spin_once(timeout_sec=0.005)


def send(pub, text, n=3):
    for _ in range(n):            # volatile QoS, first message may race discovery
        pub.publish(String(data=text))
        spin(0.1)


def set_param(name, v):
    req = SetParameters.Request(parameters=[Parameter(
        name=name, value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=v))])
    fut = params.call_async(req)
    ex_main.spin_until_future_complete(fut, timeout_sec=5.0)
    return fut.done() and all(r.successful for r in fut.result().results)


check('mux service up', params.wait_for_service(timeout_sec=15.0))
spin(2.0)
check('state has gear key', 'gear' in last['state'], str(last['state'].get('gear')))

send(mode_pub, 'manual')
spin(2.0, throttle=1.0)            # gear 1: 0.15 m/s, ramp 0.3 m/s^2 -> 0.5 s
check('gear 1 full throttle -> 0.15 m/s', abs(last['cmd'].linear.x - 0.15) < 0.01,
      f'vx={last["cmd"].linear.x:.3f} mode={last["state"].get("mode")}')

send(gear_pub, 'up', n=1); send(gear_pub, 'up', n=1); send(gear_pub, 'up', n=1)
spin(4.0, throttle=1.0)            # 0.15 -> 0.8 at 0.3 m/s^2 ~ 2.2 s
check('gear 4 -> 0.8 m/s', abs(last['cmd'].linear.x - 0.8) < 0.01 and last['state'].get('gear') == 4,
      f'vx={last["cmd"].linear.x:.3f} gear={last["state"].get("gear")}')

check('max_angular 1.0 (as rover_arming sets in Ackermann)', set_param('max_angular', 1.0))
check('set angular_sign +1', set_param('angular_sign', 1.0))
spin(1.5, throttle=1.0, steer=1.0)   # omega = a_lat/v = 0.5/0.8 = 0.625
w = last['cmd'].angular.z
check('steer left at 0.8 m/s, a_lat bound -> +0.625', abs(w - 0.625) < 0.02, f'wz={w:.3f}')

check('set angular_sign -1', set_param('angular_sign', -1.0))
spin(0.5, throttle=1.0, steer=1.0)
w = last['cmd'].angular.z
check('angular_sign -1 flips steering', abs(w + 0.625) < 0.02, f'wz={w:.3f}')

spin(1.0)                           # no stick -> deadman after teleop_timeout
check('deadman: stick stops -> zero', last['cmd'].linear.x == 0.0 and last['cmd'].angular.z == 0.0,
      f'vx={last["cmd"].linear.x:.3f} wz={last["cmd"].angular.z:.3f}')

send(mode_pub, 'stop')
spin(0.5)
check('stop resets gear to 1', last['state'].get('gear') == 1, str(last['state'].get('gear')))

print('ALL PASS' if not fails else f'FAILED: {fails}')
sys.exit(1 if fails else 0)
