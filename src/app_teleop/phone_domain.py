"""The phone's DDS domain, shared by teleop_mux, teleop_camera and rover_arming.

foxglove_bridge runs alone in TELEOP_PHONE_DOMAIN (default 51), because 3.6.0 ignores
its client_topic_whitelist and would publish any topic a WebSocket client asks for,
/cmd_vel included. teleop_mux, teleop_camera and rover_arming are the only nodes in both domains, so the phone
can reach /teleop/phone/*, /teleop/state, /teleop/rover_state and
/teleop/camera/compressed and nothing else.
"""
import os
import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node


def phone_node(name):
    """A node in the phone domain, spinning in its own thread."""
    ctx = rclpy.Context()
    rclpy.init(context=ctx, domain_id=int(os.environ.get('TELEOP_PHONE_DOMAIN', '51')))
    node = Node(name, context=ctx)
    executor = SingleThreadedExecutor(context=ctx)
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    return node
