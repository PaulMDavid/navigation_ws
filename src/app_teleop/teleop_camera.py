#!/usr/bin/env python3
"""Relay a compressed camera stream to the phone app, sized for Wi-Fi.

Reads the first of `input_topics` that exists (sensor_msgs/CompressedImage; the ZED 2i
under either of its wrapper's namings) and republishes it as /teleop/camera/compressed
in the phone DDS domain (phone_domain.py). Frames above `max_rate` are dropped; frames
wider than `max_width`, or not JPEG, are downscaled and re-encoded at `jpeg_quality`.

The input is subscribed only while something subscribes to the output, i.e. while the
app's camera page is open. A separate process from teleop_mux, so JPEG work can never
delay a /cmd_vel tick.
"""
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage

from phone_domain import phone_node

COMPRESSED = 'sensor_msgs/msg/CompressedImage'


def jpeg_width(data):
    """Width from a JPEG's SOF marker, without decoding; 0 if not found."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return 0
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], 'big')
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], 'big')
        i += 2 + length
    return 0


class TeleopCamera(Node):
    def __init__(self, phone):
        super().__init__('teleop_camera')
        self.declare_parameter('input_topics', ['/zed2i/zed_node/rgb/color/rect/image/compressed',
                                                '/zed2i/zed_node/rgb/image_rect_color/compressed'])
        self.declare_parameter('max_rate', 10.0)
        self.declare_parameter('max_width', 960)
        self.declare_parameter('jpeg_quality', 60)
        self.pub = phone.create_publisher(CompressedImage, '/teleop/camera/compressed', qos_profile_sensor_data)
        self.sub = None
        self.next = 0.0
        self.sent = 0
        self.create_timer(0.5, self.follow_demand)
        self.create_timer(10.0, self.report)
        self.get_logger().info(f'inputs {self.get_parameter("input_topics").value} -> /teleop/camera/compressed '
                               f'(domain {phone.context.get_domain_id()}), '
                               f'<= {self.get_parameter("max_rate").value} Hz, '
                               f'<= {self.get_parameter("max_width").value} px wide')

    def input_topic(self):
        existing = {name for name, types in self.get_topic_names_and_types() if COMPRESSED in types}
        return next((t for t in self.get_parameter('input_topics').value if t in existing), None)

    def follow_demand(self):
        watched = self.pub.get_subscription_count() > 0
        if watched and self.sub is None:
            topic = self.input_topic()
            if topic is None:
                self.get_logger().warn('phone watching, but none of input_topics is published',
                                       throttle_duration_sec=10.0)
                return
            self.sub = self.create_subscription(CompressedImage, topic, self.on_image, qos_profile_sensor_data)
            self.get_logger().info(f'phone watching: subscribed to {topic}')
        elif not watched and self.sub is not None:
            self.destroy_subscription(self.sub)
            self.sub = None
            self.get_logger().info('nobody watching: unsubscribed')

    def on_image(self, msg):
        # one frame slot per 1/max_rate; up to a quarter period early still counts
        now = time.monotonic()
        period = 1.0 / self.get_parameter('max_rate').value
        if now < self.next - period / 4:
            return
        self.next = max(self.next + period, now)

        max_width = self.get_parameter('max_width').value
        fmt = msg.format.lower()
        if not ('jpeg' in fmt or 'jpg' in fmt) or jpeg_width(bytes(msg.data[:65536])) > max_width:
            img = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None:
                return
            if img.shape[1] > max_width:
                h = round(img.shape[0] * max_width / img.shape[1])
                img = cv2.resize(img, (max_width, h), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, self.get_parameter('jpeg_quality').value])
            if not ok:
                return
            msg = CompressedImage(header=msg.header, format='jpeg', data=buf.tobytes())
        self.pub.publish(msg)
        self.sent += 1

    def report(self):
        if self.sent:
            self.get_logger().info(f'{self.sent / 10.0:.1f} frames/s to the phone')
        self.sent = 0


def main():
    rclpy.init()
    rclpy.spin(TeleopCamera(phone_node('teleop_camera_phone')))


if __name__ == '__main__':
    main()
