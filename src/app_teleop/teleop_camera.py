#!/usr/bin/env python3
"""Relay a compressed camera stream to the phone app, sized for Wi-Fi.

Reads `input_topic` (sensor_msgs/CompressedImage; the ZED 2i's colour image by default)
in the robot's DDS domain and republishes it as /teleop/camera/compressed in the phone
domain (TELEOP_PHONE_DOMAIN), where foxglove_bridge runs; see teleop_mux.py for why the
phone has its own domain. On the way it drops frames above `max_rate` and, if the image
is wider than `max_width` or not JPEG, decodes, downscales and re-encodes it at
`jpeg_quality`.

Lazy: the input is only subscribed while something in the phone domain subscribes to
the output, i.e. while the app's camera page is open. Otherwise this costs nothing.
Kept out of teleop_mux's process so JPEG work can never delay a /cmd_vel tick.
"""
import os
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class TeleopCamera(Node):
    def __init__(self, phone_node):
        super().__init__('teleop_camera')
        self.declare_parameter('input_topic', '/zed2i/zed_node/rgb/color/rect/image/compressed')
        self.declare_parameter('max_rate', 10.0)
        self.declare_parameter('max_width', 960)
        self.declare_parameter('jpeg_quality', 60)
        self.pub = phone_node.create_publisher(CompressedImage, '/teleop/camera/compressed',
                                               qos_profile_sensor_data)
        self.sub = None
        self.next = 0.0
        self.sent = 0
        self.create_timer(0.5, self.follow_demand)
        self.create_timer(10.0, self.report)
        self.get_logger().info(f'relaying {self.get_parameter("input_topic").value} -> '
                               f'/teleop/camera/compressed (domain {phone_node.context.get_domain_id()}), '
                               f'<= {self.get_parameter("max_rate").value} Hz, '
                               f'<= {self.get_parameter("max_width").value} px wide')

    def follow_demand(self):
        watched = self.pub.get_subscription_count() > 0
        if watched and self.sub is None:
            self.sub = self.create_subscription(CompressedImage, self.get_parameter('input_topic').value,
                                                self.on_image, qos_profile_sensor_data)
            self.get_logger().info('phone watching: subscribed')
        elif not watched and self.sub is not None:
            self.destroy_subscription(self.sub)
            self.sub = None
            self.get_logger().info('nobody watching: unsubscribed')

    def on_image(self, msg):
        # frame slots every 1/max_rate; a frame up to a quarter period early still takes
        # its slot, so 30 Hz in gives 10 Hz out rather than every 4th frame
        now = time.monotonic()
        period = 1.0 / self.get_parameter('max_rate').value
        if now < self.next - period / 4:
            return
        self.next = max(self.next + period, now)
        max_width = self.get_parameter('max_width').value
        is_jpeg = 'jpeg' in msg.format.lower() or 'jpg' in msg.format.lower()
        if not is_jpeg or self.width(msg) > max_width:
            img = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None:
                return
            if img.shape[1] > max_width:
                h = round(img.shape[0] * max_width / img.shape[1])
                img = cv2.resize(img, (max_width, h), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY,
                                                 self.get_parameter('jpeg_quality').value])
            if not ok:
                return
            msg = CompressedImage(header=msg.header, format='jpeg', data=buf.tobytes())
        self.pub.publish(msg)
        self.sent += 1

    def width(self, msg):
        """Image width from the JPEG's SOF marker, without decoding; 0 if not found."""
        data = bytes(msg.data[:65536])
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return 0
            marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], 'big')
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[i + 7:i + 9], 'big')
            i += 2 + length
        return 0

    def report(self):
        if self.sent:
            self.get_logger().info(f'{self.sent / 10.0:.1f} frames/s to the phone')
        self.sent = 0


def main():
    rclpy.init()
    ctx = rclpy.Context()
    rclpy.init(context=ctx, domain_id=int(os.environ.get('TELEOP_PHONE_DOMAIN', '51')))
    phone_node = Node('teleop_camera_phone', context=ctx)
    executor = SingleThreadedExecutor(context=ctx)
    executor.add_node(phone_node)
    threading.Thread(target=executor.spin, daemon=True).start()
    rclpy.spin(TeleopCamera(phone_node))


if __name__ == '__main__':
    main()
