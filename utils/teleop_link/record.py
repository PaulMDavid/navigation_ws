#!/usr/bin/env python3
"""Record a hands-on phone session, then summarise it.

  record.py record   log /cmd_vel + /teleop/state (robot domain) and what the phone
                     sends (/teleop/phone/cmd_vel, phone domain) to results/session.jsonl
  record.py report   mode changes, peak output, and every stop: how long after the
                     phone's last non-zero command /cmd_vel went to zero, and why
"""
import json
import signal
import sys
import threading
import time

ROBOT_DOMAIN, PHONE_DOMAIN = 77, 79
PATH = '/probe/results/session.jsonl'


def record():
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String

    out = open(PATH, 'a', buffering=1)
    lock = threading.Lock()

    def log(kind, **data):
        with lock:
            out.write(json.dumps({'t': time.time(), 'k': kind, **data}) + '\n')

    def node_in(domain, name):
        ctx = rclpy.Context()
        rclpy.init(context=ctx, domain_id=domain)
        node = Node(name, context=ctx)
        ex = SingleThreadedExecutor(context=ctx)
        ex.add_node(node)
        threading.Thread(target=ex.spin, daemon=True).start()
        return node

    robot = node_in(ROBOT_DOMAIN, 'teleop_session_robot')
    robot.create_subscription(Twist, '/cmd_vel', lambda m: log(
        'out', vx=m.linear.x, wz=m.angular.z), 10)
    robot.create_subscription(String, '/teleop/state', lambda m: log(
        'state', **json.loads(m.data)), 10)
    phone = node_in(PHONE_DOMAIN, 'teleop_session_phone')
    phone.create_subscription(Twist, '/teleop/phone/cmd_vel', lambda m: log(
        'phone', vx=m.linear.x, wz=m.angular.z), qos_profile_sensor_data)
    phone.create_subscription(String, '/teleop/phone/set_mode', lambda m: log(
        'phone_mode', data=m.data), 10)

    print(f'recording to {PATH}; Ctrl-C to stop', flush=True)
    signal.sigwait({signal.SIGINT, signal.SIGTERM})


def report():
    rows = [json.loads(line) for line in open(PATH)]
    if not rows:
        print('empty session')
        return
    t0 = rows[0]['t']
    print(f'session: {rows[-1]["t"] - t0:.0f} s, {len(rows)} records')

    mode = None
    for r in rows:
        if r['k'] == 'state' and r['mode'] != mode:
            mode = r['mode']
            print(f'  {r["t"] - t0:7.2f} s  mode -> {mode:10s} (by {r["mode_by"]}, source {r["source"]})')

    phone = [r for r in rows if r['k'] == 'phone']
    if len(phone) > 1:
        gaps = [b['t'] - a['t'] for a, b in zip(phone, phone[1:])]
        print(f'phone commands: {len(phone)}, rate {len(phone) / (phone[-1]["t"] - phone[0]["t"]):.1f} Hz, '
              f'largest gap {max(gaps):.2f} s')
    outs = [r for r in rows if r['k'] == 'out']
    print(f'peak output: vx {max(abs(r["vx"]) for r in outs):.2f} m/s, '
          f'wz {max(abs(r["wz"]) for r in outs):.2f} rad/s')

    # every non-zero -> zero transition of /cmd_vel
    print('stops (output non-zero -> zero):')
    prev_moving = False
    for r in outs:
        moving = r['vx'] != 0.0 or r['wz'] != 0.0
        if prev_moving and not moving:
            before = [p for p in phone if p['t'] <= r['t']]
            last = before[-1] if before else None
            last_nonzero = next((p for p in reversed(before) if p['vx'] or p['wz']), None)
            state = next((s for s in reversed(rows) if s['k'] == 'state' and s['t'] <= r['t']), {})
            if state.get('mode') != 'manual':
                why, dt = f'mode {state.get("mode")}', None
            elif last and not (last['vx'] or last['wz']):
                why, dt = 'joystick released', r['t'] - last_nonzero['t'] if last_nonzero else None
            else:
                why, dt = 'deadman (phone stopped sending)', r['t'] - last['t'] if last else None
            lat = '' if dt is None else f', {dt:.3f} s after the last phone command'
            print(f'  {r["t"] - t0:7.2f} s  {why}{lat}')
        prev_moving = moving


if __name__ == '__main__':
    {'record': record, 'report': report}[sys.argv[1]]()
