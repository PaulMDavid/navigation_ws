#!/usr/bin/env python3
"""Republish RTAB-Map's odometry with RELIABLE QoS for Nav2.

rtabmap runs with qos:=2 so icp_odometry can subscribe to the Ouster's
best-effort /ouster/points, but the same parameter makes it publish
/rtabmap/odom best-effort too, and Nav2's odometry subscriber is reliable.
The two can't connect, so this bridges /rtabmap/odom -> /rtabmap/odom_reliable.
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from nav_msgs.msg import Odometry


class OdomReliableRelay(Node):
    def __init__(self):
        super().__init__('odom_reliable_relay')
        self.pub = self.create_publisher(
            Odometry, '/rtabmap/odom_reliable',
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        self.create_subscription(
            Odometry, '/rtabmap/odom', self.pub.publish, qos_profile_sensor_data)


def main():
    rclpy.init()
    rclpy.spin(OdomReliableRelay())


if __name__ == '__main__':
    main()
