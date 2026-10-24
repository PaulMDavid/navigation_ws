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

Phone domain: with TELEOP_PHONE_DOMAIN set, the phone's topics (and a copy of
/teleop/state) live in that DDS domain instead, where foxglove_bridge runs. This node
is the only thing in both domains, so a WebSocket client can reach nothing else:
foxglove_bridge 3.6.0 ignores its client_topic_whitelist and would otherwise let any
client publish any topic, /cmd_vel included (utils/teleop_link/README.md).
"""
import json
import math
import os
import threading

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import SetParametersResult
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from std_msgs.msg import String

MODES = ('autonomous', 'manual', 'stop')
SOURCES = ('ground', 'phone')


def clamp(v, limit):
    return max(-limit, min(limit, v)) if math.isfinite(v) else 0.0


class TeleopMux(Node):
    def __init__(self, phone_node=None):
        super().__init__('teleop_mux')
        self.declare_parameter('source', os.environ.get('TELEOP_SOURCE', 'ground'))
        self.declare_parameter('initial_mode', 'autonomous')
        self.declare_parameter('rate', 20.0)
        self.declare_parameter('teleop_timeout', 0.5)
        self.declare_parameter('nav_timeout', 0.5)
        self.declare_parameter('max_linear', 0.5)
        self.declare_parameter('max_angular', 1.0)
        self.declare_parameter('nav_topic', '/cmd_vel_auto')
        self.declare_parameter('out_topic', '/cmd_vel')

        self.source = self.get_parameter('source').value
        if self.source not in SOURCES:
            raise SystemExit(f'source must be one of {SOURCES}, got {self.source!r}')
        self.mode = self.get_parameter('initial_mode').value
        self.mode_by = 'startup'
        self.teleop = {s: (None, Twist()) for s in SOURCES}  # source -> (receive time, msg)
        self.nav = (None, Twist())
        self.out = Twist()

        self.pub = self.create_publisher(Twist, self.get_parameter('out_topic').value,
                                         QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        node_for = {'ground': self, 'phone': phone_node or self}
        self.state_pubs = [n.create_publisher(String, '/teleop/state', 10)
                           for n in {self, node_for['phone']}]
        # best effort matches both reliable and best-effort publishers (bridges differ)
        self.create_subscription(Twist, self.get_parameter('nav_topic').value,
                                 self.on_nav, qos_profile_sensor_data)
        for s in SOURCES:
            node_for[s].create_subscription(Twist, f'/teleop/{s}/cmd_vel',
                                            lambda m, s=s: self.on_teleop(s, m), qos_profile_sensor_data)
            node_for[s].create_subscription(String, f'/teleop/{s}/set_mode',
                                            lambda m, s=s: self.on_set_mode(s, m.data.strip().lower()), 10)
        self.add_on_set_parameters_callback(self.on_params)

        self.create_timer(1.0 / self.get_parameter('rate').value, self.tick)
        self.create_timer(0.2, self.publish_state)
        phone_domain = phone_node.context.get_domain_id() if phone_node else 'same'
        self.get_logger().info(f'source={self.source} mode={self.mode} phone_domain={phone_domain} '
                               f'limits={self.limits()} timeout={self.timeout("teleop")}s')

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

    def on_set_mode(self, source, mode):
        if mode not in MODES:
            self.get_logger().warn(f'{source}: unknown mode {mode!r}')
            return
        if mode != 'stop' and source != self.source:
            self.get_logger().warn(f'{source}: {mode} ignored, active source is {self.source}')
            return
        if mode != self.mode:
            self.get_logger().info(f'mode {self.mode} -> {mode} (by {source})')
        self.mode, self.mode_by = mode, source

    def on_params(self, params):
        for p in params:
            if p.name == 'source':
                if p.value not in SOURCES:
                    return SetParametersResult(successful=False, reason=f'source must be one of {SOURCES}')
                if p.value != self.source:
                    self.get_logger().info(f'source {self.source} -> {p.value}, mode -> stop')
                    self.source, self.mode, self.mode_by = p.value, 'stop', 'source change'
        return SetParametersResult(successful=True)

    def tick(self):
        out = Twist()
        if self.mode == 'manual':
            stamp, cmd = self.teleop[self.source]
            age = self.age(stamp)
            if age is not None and age < self.timeout('teleop'):
                max_lin, max_ang = self.limits()
                out.linear.x = clamp(cmd.linear.x, max_lin)
                out.linear.y = clamp(cmd.linear.y, max_lin)
                out.angular.z = clamp(cmd.angular.z, max_ang)
        elif self.mode == 'autonomous':
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
        }))
        for pub in self.state_pubs:
            pub.publish(msg)


def main():
    rclpy.init()
    phone_node = None
    phone_domain = os.environ.get('TELEOP_PHONE_DOMAIN')
    if phone_domain:
        ctx = rclpy.Context()
        rclpy.init(context=ctx, domain_id=int(phone_domain))
        phone_node = Node('teleop_mux_phone', context=ctx)
        executor = SingleThreadedExecutor(context=ctx)
        executor.add_node(phone_node)
        threading.Thread(target=executor.spin, daemon=True).start()
    rclpy.spin(TeleopMux(phone_node))


if __name__ == '__main__':
    main()
