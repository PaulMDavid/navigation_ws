#!/usr/bin/env python3
"""One-shot ROS checks for scripts/phone_ctl.sh, run inside app_teleop_container:

  docker exec app_teleop_container /ros_entrypoint.sh \\
      python3 app_teleop/phone_probe.py <check> [args]

  mux_source [--timeout S]             teleop_mux's active source, from /teleop/state
  subs TOPIC... [--timeout S]          every TOPIC has >= 1 subscriber in the main domain
  rate TOPIC [--phone] [--window S] [--timeout S]
                                       sensor_msgs/CompressedImage rate (phone domain with --phone)
  rover_cmd CMD [--timeout S]          send CMD to rover_arming as the active source and wait
                                       until /teleop/rover_state shows it ran

Prints one line, `ok <detail>` or `fail <reason>`, and exits 0 / 1. phone_ctl.sh reads
that line; no JSON parsing needed on the host.
"""
import argparse
import json
import os
import sys
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

PHONE_DOMAIN = int(os.environ.get('TELEOP_PHONE_DOMAIN', '51'))


class Probe:
    def __init__(self, domain=None):
        self.ctx = rclpy.Context()
        kw = {} if domain is None else {'domain_id': domain}
        rclpy.init(context=self.ctx, **kw)
        self.node = Node(f'phone_probe_{os.getpid()}', context=self.ctx)
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(self.node)

    def spin_until(self, cond, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            self.ex.spin_once(timeout_sec=0.05)
        return cond()

    def close(self):
        self.node.destroy_node()
        rclpy.shutdown(context=self.ctx)


def json_sub(probe, topic):
    box = {}

    def cb(msg):
        try:
            box['v'], box['t'] = json.loads(msg.data), time.monotonic()
        except ValueError:
            pass
    probe.node.create_subscription(String, topic, cb, 10)
    return box


def mux_source(main, timeout):
    state = json_sub(main, '/teleop/state')
    if not main.spin_until(lambda: 'v' in state, timeout):
        return None
    return state['v'].get('source')


def check_mux_source(a):
    main = Probe()
    try:
        source = mux_source(main, a.timeout)
    finally:
        main.close()
    if source is None:
        return False, f'no /teleop/state within {a.timeout:g} s (teleop_mux not running?)'
    return True, source


def check_subs(a):
    main = Probe()
    try:
        counts = lambda: {t: main.node.count_subscribers(t) for t in a.topics}
        main.spin_until(lambda: all(n > 0 for n in counts().values()), a.timeout)
        c = counts()
    finally:
        main.close()
    missing = [t for t, n in c.items() if n == 0]
    if missing:
        return False, f'no subscriber on {" ".join(missing)}'
    return True, ' '.join(f'{t}:{n}' for t, n in c.items())


def check_rate(a):
    p = Probe(PHONE_DOMAIN if a.phone else None)
    stamps = []
    try:
        p.node.create_subscription(CompressedImage, a.topic, lambda _m: stamps.append(time.monotonic()),
                                  qos_profile_sensor_data)  # relay publishes best-effort
        # wait for the first frame (teleop_camera is lazy: our subscription switches it on)
        if not p.spin_until(lambda: stamps, a.timeout):
            return False, f'no message on {a.topic} within {a.timeout:g} s'
        del stamps[:]
        p.spin_until(lambda: False, a.window)
    finally:
        p.close()
    hz = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) >= 2 else 0.0
    return True, f'{hz:.1f}'


def check_rover_cmd(a):
    main = Probe()
    phone = Probe(PHONE_DOMAIN)
    try:
        source = mux_source(main, a.timeout)
        if source not in ('ground', 'phone'):
            return False, f'active source unknown ({source!r}); rover_arming refuses commands'
        rover_state = json_sub(main, '/teleop/rover_state')
        node = phone if source == 'phone' else main
        pub = node.node.create_publisher(String, f'/teleop/{source}/rover_cmd', 10)
        if not node.spin_until(lambda: pub.get_subscription_count() > 0, a.timeout):
            return False, f'nobody listens on /teleop/{source}/rover_cmd (app_rover_arming not running?)'
        sent = time.monotonic()
        pub.publish(String(data=a.cmd))

        def ran():
            node.ex.spin_once(timeout_sec=0)
            v = rover_state.get('v')
            if not v or rover_state['t'] < sent:
                return False
            if v.get('rejected') and v.get('last_cmd') != a.cmd:
                return True
            return v.get('last_cmd') == a.cmd and v.get('last_cmd_age', 1e9) <= time.monotonic() - sent + 0.5
        if not main.spin_until(ran, a.timeout):
            return False, f'rover_arming did not report {a.cmd} within {a.timeout:g} s'
        v = rover_state['v']
        if v.get('last_cmd') != a.cmd:
            return False, f'rover_arming refused {a.cmd}: {v.get("rejected")}'
        # a command with presses changes the state while it runs: wait until it settles
        key = lambda: tuple(rover_state['v'].get(k) for k in ('input', 'steering', 'motion', 'presses'))
        last, since = key(), time.monotonic()

        def settled():
            nonlocal last, since
            node.ex.spin_once(timeout_sec=0)
            if key() != last:
                last, since = key(), time.monotonic()
            return time.monotonic() - since >= 0.6
        main.spin_until(settled, a.timeout)
        v = rover_state['v']
        return True, f'{a.cmd} by {source}: {v.get("input")}/{v.get("steering")}/{v.get("motion")}'
    finally:
        phone.close()
        main.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='check', required=True)
    s = sub.add_parser('mux_source')
    s.add_argument('--timeout', type=float, default=5.0)
    s.set_defaults(fn=check_mux_source)
    s = sub.add_parser('subs')
    s.add_argument('topics', nargs='+')
    s.add_argument('--timeout', type=float, default=5.0)
    s.set_defaults(fn=check_subs)
    s = sub.add_parser('rate')
    s.add_argument('topic')
    s.add_argument('--phone', action='store_true')
    s.add_argument('--window', type=float, default=3.0)
    s.add_argument('--timeout', type=float, default=10.0)
    s.set_defaults(fn=check_rate)
    s = sub.add_parser('rover_cmd')
    s.add_argument('cmd')
    s.add_argument('--timeout', type=float, default=5.0)
    s.set_defaults(fn=check_rover_cmd)
    a = ap.parse_args(argv)
    try:
        ok, detail = a.fn(a)
    except Exception as e:  # noqa: BLE001 - any failure is a red check, with its reason
        ok, detail = False, f'{type(e).__name__}: {e}'
    print(f'{"ok" if ok else "fail"} {detail}', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
