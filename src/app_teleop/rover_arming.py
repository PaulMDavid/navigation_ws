#!/usr/bin/env python3
"""Arm and switch the rover's robot_control from the phone or the ground PC.

robot_control on the rover takes its mode switches as /joy button presses. This node
publishes those presses on /joy (sensor_msgs/Joy, 8 axes, 17 buttons) and tracks, i.e.
guesses, robot_control's state from what it sent (rover_tracker.py). It never reads
the rover.

  /teleop/phone/rover_cmd   std_msgs/String, phone domain (phone_domain.py)
  /teleop/ground/rover_cmd  std_msgs/String, main domain
     input_auto | steer_ackermann | steer_crab | resume | arm | reset
     Accepted only from teleop_mux's active source (read from /teleop/state), the same
     rule as set_mode.
  /teleop/rover_state       std_msgs/String, JSON, both domains, at `state_rate`

When the tracked steering is set, teleop_mux's max_angular is set to
`ackermann_max_angular` or `crab_max_angular` through its set_parameters service.
"""
import json
import threading

import rclpy
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import String

from phone_domain import phone_node
from rover_tracker import N_AXES, RoverTracker

SOURCES = ('ground', 'phone')


class RoverArming(Node):
    def __init__(self, phone):
        super().__init__('rover_arming')
        self.declare_parameter('press_gap', 0.2)              # s between Joy messages
        self.declare_parameter('state_rate', 4.0)             # Hz, /teleop/rover_state
        self.declare_parameter('mux_state_timeout', 2.0)      # s; older /teleop/state = source unknown
        self.declare_parameter('mux_node', '/teleop_mux')
        self.declare_parameter('ackermann_max_angular', 1.0)  # rad/s
        self.declare_parameter('crab_max_angular', 0.1)       # rad/s
        self.declare_parameter('joy_topic', '/joy')

        self.lock = threading.Lock()   # the phone node's callbacks run in another thread
        self.tracker = RoverTracker(gap=self.get_parameter('press_gap').value)
        self.active_source = None
        self.mux_state_t = None
        self.want_max_angular = None   # value teleop_mux should get; None once it has it
        self.param_call = None

        self.joy_pub = self.create_publisher(Joy, self.get_parameter('joy_topic').value, 10)
        self.state_pubs = [n.create_publisher(String, '/teleop/rover_state', 10) for n in (self, phone)]
        self.create_subscription(String, '/teleop/state', self.on_mux_state, 10)
        node_for = {'ground': self, 'phone': phone}
        for s in SOURCES:
            node_for[s].create_subscription(String, f'/teleop/{s}/rover_cmd',
                                            lambda m, s=s: self.on_cmd(s, m.data.strip().lower()), 10)
        mux = self.get_parameter('mux_node').value.rstrip('/')
        self.param_client = self.create_client(SetParameters, f'{mux}/set_parameters')

        self.create_timer(0.02, self.tick)
        self.create_timer(1.0 / self.get_parameter('state_rate').value, self.publish_state)
        self.create_timer(1.0, self.push_max_angular)
        self.get_logger().info(f'/teleop/{{ground,phone}}/rover_cmd -> {self.get_parameter("joy_topic").value}, '
                               f'phone_domain={phone.context.get_domain_id()}, '
                               f'tracked state starts at boot defaults (manual / crab / stopped)')

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def on_mux_state(self, msg):
        try:
            source = json.loads(msg.data).get('source')
        except (ValueError, AttributeError):
            return
        with self.lock:
            self.active_source, self.mux_state_t = source, self.now()

    def current_source(self):
        if self.mux_state_t is None or self.now() - self.mux_state_t > self.get_parameter('mux_state_timeout').value:
            return None
        return self.active_source

    def on_cmd(self, source, cmd):
        with self.lock:
            reason = self.tracker.submit(cmd, source, self.current_source())
        if reason:
            self.get_logger().warn(reason)
        else:
            self.get_logger().info(f'{cmd} from {source} queued')
        self.publish_state()

    def tick(self):
        with self.lock:
            events = self.tracker.step(self.now())
        for kind, value in events:
            if kind == 'joy':
                msg = Joy(axes=[0.0] * N_AXES, buttons=value)
                msg.header.stamp = self.get_clock().now().to_msg()
                self.joy_pub.publish(msg)
                pressed = [i for i, b in enumerate(value) if b]
                if pressed:
                    self.get_logger().info(f'/joy press button {pressed[0]}')
            elif kind == 'steering':
                self.want_max_angular = self.get_parameter(f'{value}_max_angular').value
                self.get_logger().info(f'steering {value}: teleop_mux max_angular -> {self.want_max_angular}')
                self.push_max_angular()
        if events:
            self.publish_state()

    def push_max_angular(self):
        """Send want_max_angular to teleop_mux; retried every second until it succeeds."""
        if self.want_max_angular is None or self.param_call is not None:
            return
        if not self.param_client.service_is_ready():
            self.get_logger().warn('teleop_mux set_parameters not available, retrying',
                                   throttle_duration_sec=10.0)
            return
        value = float(self.want_max_angular)
        req = SetParameters.Request(parameters=[Parameter(
            name='max_angular',
            value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=value))])
        self.param_call = self.param_client.call_async(req)
        self.param_call.add_done_callback(lambda f, v=value: self.on_param_done(f, v))

    def on_param_done(self, future, value):
        self.param_call = None
        try:
            ok = future.result().results[0].successful
        except Exception as e:  # noqa: BLE001 - any failure means retry
            self.get_logger().warn(f'setting teleop_mux max_angular failed: {e}')
            return
        if ok and self.want_max_angular == value:
            self.want_max_angular = None
            self.get_logger().info(f'teleop_mux max_angular = {value}')
        elif not ok:
            self.get_logger().warn('teleop_mux refused max_angular, retrying')

    def publish_state(self):
        with self.lock:
            msg = String(data=json.dumps(self.tracker.report(self.now())))
        for pub in self.state_pubs:
            pub.publish(msg)


def main():
    rclpy.init()
    rclpy.spin(RoverArming(phone_node('rover_arming_phone')))


if __name__ == '__main__':
    main()
