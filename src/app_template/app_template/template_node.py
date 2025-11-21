#!/usr/bin/env python3
import rclpy
from rclpy.node import Node

class TemplateNode(Node):
    def __init__(self):
        super().__init__('template_node')
        self.get_logger().info('Template node started.')
        self.declare_parameter('param_example', 1.0)
        param_value = self.get_parameter('param_example').get_parameter_value().double_value
        self.get_logger().info(f'Parameter param_example: {param_value}')

def main(args=None):
    rclpy.init(args=args)
    node = TemplateNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()  