#!/usr/bin/env python3
"""Decide what reaches /cmd_vel: Nav2, an operator, or nothing.

Sits between Nav2 and the rover. Nav2's velocity smoother publishes /cmd_vel_auto;
operators publish /teleop/<source>/cmd_vel, where <source> is `ground` (ground-station
PC over Zenoh) or `phone` (the phone app over foxglove_bridge). Only the active source,
set by the `source` parameter (TELEOP_SOURCE at boot), is listened to.

Modes:
  autonomous  Nav2's commands pass through; teleop is ignored.
  manual      the active source drives; Nav2 is ignored.
  stop        zero velocity, held until someone leaves this mode.

/teleop/<source>/set_mode takes "autonomous" | "manual" | "stop". "stop" is accepted
from every source; the other modes only from the active one. Changing the source
puts the robot in stop.

Deadman: an input older than its timeout counts as zero, so a dead link stops the
rover within `teleop_timeout`. /cmd_vel is published at `rate` in every mode, and the
robot-side speed limits clamp everything an operator sends.
/teleop/state reports the mode the robot is actually in, as JSON.

Stick input (#37): /teleop/<source>/stick is a normalized Twist (linear.x = throttle,
angular.z = steer, both in [-1, 1], steer + = left) and /teleop/<source>/gear picks the
gear ("up", "down", "1".."4"). The gears, speed ramp and speed-dependent curvature
limit are in teleop_drive.py. For each source the newest of stick and cmd_vel wins.
/odom_wheels (nav_msgs/Odometry) gives the measured speed for /teleop/state.

The phone's topics, and a copy of /teleop/state, live in the phone DDS domain
(phone_domain.py).
"""
import json
import math
import os
import threading

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from std_msgs.msg import String

from phone_domain import phone_node
from teleop_drive import DriveCore, DriveParams

MODES = ('autonomous', 'manual', 'stop')
SOURCES = ('ground', 'phone')


DRIVE_PARAMS = ('gear_speeds', 'accel', 'decel', 'a_lat_max', 'min_turn_radius', 'steer_rate')


def clamp(v, limit):
    return max(-limit, min(limit, v)) if math.isfinite(v) else 0.0


class TeleopMux(Node):
    def __init__(self, phone):
        super().__init__('teleop_mux')
        self.declare_parameter('source', os.environ.get('TELEOP_SOURCE', 'ground'))
        self.declare_parameter('initial_mode', 'autonomous')
        self.declare_parameter('rate', 20.0)
        self.declare_parameter('teleop_timeout', 0.5)
        self.declare_parameter('nav_timeout', 0.5)
        self.declare_parameter('max_linear', 0.8)
        self.declare_parameter('max_angular', 1.0)
        self.declare_parameter('nav_topic', '/cmd_vel_auto')
        self.declare_parameter('out_topic', '/cmd_vel')
        # stick input (#37), defaults as in teleop_drive.DriveParams
        d = DriveParams()
        self.declare_parameter('gear_speeds', d.gear_speeds)
        for name in DRIVE_PARAMS[1:]:
            self.declare_parameter(name, getattr(d, name))
        self.declare_parameter('odom_topic', '/odom_wheels')
        self.declare_parameter('odom_timeout', 0.5)

        self.source = self.get_parameter('source').value
        if self.source not in SOURCES:
            raise SystemExit(f'source must be one of {SOURCES}, got {self.source!r}')
        self.mode = self.get_parameter('initial_mode').value
        self.mode_by = 'startup'
        self.teleop = {s: (None, Twist()) for s in SOURCES}  # source -> (receive time, msg)
        self.stick = {s: (None, Twist()) for s in SOURCES}   # source -> (receive time, msg)
        self.nav = (None, Twist())
        self.odom = (None, 0.0)                               # (receive time, twist.linear.x)
        self.out = Twist()
        # phone callbacks run in phone_node's thread; gear and ramp state are shared
        self.lock = threading.Lock()
        params = DriveParams(**{n: self.get_parameter(n).value for n in DRIVE_PARAMS})
        if params.problems():
            raise SystemExit(f'bad drive parameters: {params.problems()}')
        self.drive = DriveCore(params)
        self.last_tick = None

        self.pub = self.create_publisher(Twist, self.get_parameter('out_topic').value,
                                         QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        node_for = {'ground': self, 'phone': phone}
        self.state_pubs = [n.create_publisher(String, '/teleop/state', 10) for n in (self, phone)]
        # best effort matches both reliable and best-effort publishers (bridges differ)
        self.create_subscription(Twist, self.get_parameter('nav_topic').value,
                                 self.on_nav, qos_profile_sensor_data)
        for s in SOURCES:
            node_for[s].create_subscription(Twist, f'/teleop/{s}/cmd_vel',
                                            lambda m, s=s: self.on_teleop(s, m), qos_profile_sensor_data)
            node_for[s].create_subscription(String, f'/teleop/{s}/set_mode',
                                            lambda m, s=s: self.on_set_mode(s, m.data.strip().lower()), 10)
            node_for[s].create_subscription(Twist, f'/teleop/{s}/stick',
                                            lambda m, s=s: self.on_stick(s, m), qos_profile_sensor_data)
            node_for[s].create_subscription(String, f'/teleop/{s}/gear',
                                            lambda m, s=s: self.on_gear(s, m.data), 10)
        self.create_subscription(Odometry, self.get_parameter('odom_topic').value,
                                 self.on_odom, qos_profile_sensor_data)
        self.add_on_set_parameters_callback(self.on_params)

        self.create_timer(1.0 / self.get_parameter('rate').value, self.tick)
        self.create_timer(0.2, self.publish_state)
        self.get_logger().info(f'source={self.source} mode={self.mode} '
                               f'phone_domain={phone.context.get_domain_id()} '
                               f'limits={self.limits()} timeout={self.timeout("teleop")}s '
                               f'gears={params.gear_speeds}')

    def limits(self):
        return (self.get_parameter('max_linear').value, self.get_parameter('max_angular').value)

    def timeout(self, which):
        return self.get_parameter(f'{which}_timeout').value

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def age(self, stamp):
        return None if stamp is None else self.now() - stamp

    def on_nav(self, msg):
        self.nav = (self.now(), msg)

    def on_teleop(self, source, msg):
        self.teleop[source] = (self.now(), msg)

    def on_stick(self, source, msg):
        self.stick[source] = (self.now(), msg)

    def on_odom(self, msg):
        self.odom = (self.now(), msg.twist.twist.linear.x)

    def on_gear(self, source, text):
        with self.lock:
            if source != self.source:
                self.get_logger().warn(f'{source}: gear {text!r} ignored, active source is {self.source}')
                return
            before = self.drive.gear
            if self.drive.shift(text) is None:
                self.get_logger().warn(f'{source}: unknown gear command {text!r}')
            elif self.drive.gear != before:
                self.get_logger().info(f'gear {before} -> {self.drive.gear} (by {source})')

    def on_set_mode(self, source, mode):
        if mode not in MODES:
            self.get_logger().warn(f'{source}: unknown mode {mode!r}')
            return
        if mode != 'stop' and source != self.source:
            self.get_logger().warn(f'{source}: {mode} ignored, active source is {self.source}')
            return
        with self.lock:
            if mode != self.mode:
                self.get_logger().info(f'mode {self.mode} -> {mode} (by {source})')
                self.drive.zero()
            if mode == 'stop':
                self.drive.reset_gear()
            self.mode, self.mode_by = mode, source

    def on_params(self, params):
        new = {p.name: p.value for p in params}
        if any(n in new for n in DRIVE_PARAMS):
            cur = self.drive.p
            drive = DriveParams(**{n: new.get(n, getattr(cur, n)) for n in DRIVE_PARAMS})
            if drive.problems():
                return SetParametersResult(successful=False, reason='; '.join(drive.problems()))
        else:
            drive = None
        if 'source' in new and new['source'] not in SOURCES:
            return SetParametersResult(successful=False, reason=f'source must be one of {SOURCES}')
        with self.lock:
            if drive is not None:
                self.drive.set_params(drive)
            if 'source' in new and new['source'] != self.source:
                self.get_logger().info(f'source {self.source} -> {new["source"]}, mode -> stop')
                self.source, self.mode, self.mode_by = new['source'], 'stop', 'source change'
                self.drive.zero()
                self.drive.reset_gear()
        return SetParametersResult(successful=True)

    def tick(self):
        now = self.now()
        dt = 0.0 if self.last_tick is None else min(now - self.last_tick, 0.1)
        self.last_tick = now
        out = Twist()
        with self.lock:
            if self.mode == 'manual':
                max_lin, max_ang = self.limits()
                t_cmd, cmd = self.teleop[self.source]
                t_stick, stick = self.stick[self.source]
                use_stick = t_stick is not None and (t_cmd is None or t_stick >= t_cmd)
                stamp = t_stick if use_stick else t_cmd
                age = self.age(stamp)
                if age is None or age >= self.timeout('teleop'):
                    self.drive.zero()                     # deadman: at once, no ramp
                elif use_stick:
                    out.linear.x, out.angular.z = self.drive.step(
                        stick.linear.x, stick.angular.z, dt, max_lin, max_ang)
                else:
                    out.linear.x = clamp(cmd.linear.x, max_lin)
                    out.linear.y = clamp(cmd.linear.y, max_lin)
                    out.angular.z = clamp(cmd.angular.z, max_ang)
                    self.drive.hold(out.linear.x)
            else:
                self.drive.zero()
                if self.mode == 'autonomous':
                    stamp, cmd = self.nav
                    age = self.age(stamp)
                    if age is not None and age < self.timeout('nav'):
                        out = cmd
        self.out = out
        self.pub.publish(out)

    def publish_state(self):
        def rounded(age):
            return None if age is None else round(age, 3)
        max_lin, max_ang = self.limits()
        odom_age = self.age(self.odom[0])
        fresh = (odom_age is not None and odom_age <= self.get_parameter('odom_timeout').value
                 and math.isfinite(self.odom[1]))
        t_cmd, t_stick = self.teleop[self.source][0], self.stick[self.source][0]
        if t_stick is None and t_cmd is None:
            inp = None
        else:
            inp = 'stick' if t_stick is not None and (t_cmd is None or t_stick >= t_cmd) else 'cmd_vel'
        with self.lock:
            d = self.drive
            drive = {
                'gear': d.gear,
                'gears': list(d.p.gear_speeds),
                'input': inp,
                'v_target': round(d.v_target, 3),
                'kappa_max': round(d.kappa_max, 4),
                'steer_limited': d.steer_limited(),
                'a_lat_max': d.p.a_lat_max,
            }
        msg = String(data=json.dumps({
            'mode': self.mode,
            'mode_by': self.mode_by,
            'source': self.source,
            'teleop_age': {s: rounded(self.age(self.teleop[s][0])) for s in SOURCES},
            'nav_age': rounded(self.age(self.nav[0])),
            'teleop_timeout': self.timeout('teleop'),
            'max_linear': max_lin,
            'max_angular': max_ang,
            'out': {'vx': round(self.out.linear.x, 3), 'vy': round(self.out.linear.y, 3),
                    'wz': round(self.out.angular.z, 3)},
            **drive,
            'speed_meas': round(self.odom[1], 3) if fresh else None,
            'speed_meas_age': rounded(odom_age),
        }))
        for pub in self.state_pubs:
            pub.publish(msg)


def main():
    rclpy.init()
    rclpy.spin(TeleopMux(phone_node('teleop_mux_phone')))


if __name__ == '__main__':
    main()
