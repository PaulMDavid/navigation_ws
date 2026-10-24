"""Test harness: stand in for the Ouster by replaying a bag with fresh timestamps.

ros2 bag play remaps the bag's topics to /replay/*; this republishes them on the
real names with header.stamp = now, so TF ages and Nav2 tolerances look live.
"""
import struct

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import Imu, PointCloud2
from tf2_msgs.msg import TFMessage


class Restamp(Node):
    def __init__(self):
        super().__init__('replay_restamp')
        for src, dst, kind in (('/replay/points', '/ouster/points', PointCloud2),
                               ('/replay/imu', '/ouster/imu', Imu)):
            pub = self.create_publisher(kind, dst, qos_profile_sensor_data)
            self.create_subscription(kind, src, lambda m, p=pub: self.fwd(m, p),
                                     qos_profile_sensor_data, raw=True)
        latched = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.static_pub = self.create_publisher(TFMessage, '/tf_static', latched)
        self.create_subscription(TFMessage, '/replay/tf_static', self.static, 10)

    def fwd(self, raw, pub):
        # CDR: 4-byte encapsulation header, then header.stamp.sec, header.stamp.nanosec
        # as little-endian 32-bit ints. Patching bytes avoids deserializing 2.6 MB clouds.
        sec, nsec = divmod(self.get_clock().now().nanoseconds, 10**9)
        buf = bytearray(raw)
        struct.pack_into('<iI', buf, 4, sec, nsec)
        pub.publish(bytes(buf))

    def static(self, msg):
        # only the lidar's own frames; the URDF frames come from robot_state_publisher
        msg.transforms = [t for t in msg.transforms if t.header.frame_id == 'os_sensor']
        if msg.transforms:
            self.static_pub.publish(msg)


rclpy.init()
rclpy.spin(Restamp())
