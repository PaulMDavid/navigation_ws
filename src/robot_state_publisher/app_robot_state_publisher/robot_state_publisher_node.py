#!/usr/bin/env python3
import rclpy
from rclpy.node import Node

class RobotStatePublisherNode(Node):
    def __init__(self):
        super().__init__('robot_state_publisher_node')
        self.get_logger().info('Robot state publisher node started.')

def main(args=None):
    rclpy.init(args=args)
    node = RobotStatePublisherNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()  