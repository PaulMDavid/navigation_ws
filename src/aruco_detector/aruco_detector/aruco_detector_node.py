#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import cv2
import numpy as np

class ArucoDetectorNode(Node):
    def __init__(self):
        super().__init__('aruco_detector_node')
        self.get_logger().info('ArUco Detector node started.')
        
        # Declare parameters
        self.declare_parameter('aruco_dict', 'DICT_6X6_250')
        self.declare_parameter('camera_id', 0)
        self.declare_parameter('use_webcam', True)
        
        aruco_dict_name = self.get_parameter('aruco_dict').get_parameter_value().string_value
        camera_id = self.get_parameter('camera_id').get_parameter_value().integer_value
        use_webcam = self.get_parameter('use_webcam').get_parameter_value().bool_value
        
        self.get_logger().info(f'Using ArUco dictionary: {aruco_dict_name}')
        
        # Get the ArUco dictionary - use old API
        try:
            # Try new API first
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(
                getattr(cv2.aruco, aruco_dict_name)
            )
        except:
            # Fall back to old API
            self.aruco_dict = getattr(cv2.aruco, aruco_dict_name)
        
        self.marker_publisher = self.create_publisher(
            String,
            'marker_detected',
            10
        )
        
        # Initialize webcam if enabled
        if use_webcam:
            self.get_logger().info(f'Opening webcam {camera_id}')
            self.cap = cv2.VideoCapture(camera_id)
            if not self.cap.isOpened():
                self.get_logger().error(f'Failed to open webcam {camera_id}')
                return
            
            # Create timer for processing frames
            self.timer = self.create_timer(0.03, self.process_frame)  # ~30 Hz
        else:
            self.get_logger().info('Webcam disabled')
    
    def process_frame(self):
        """Process frames from webcam"""
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().error('Failed to read frame from webcam')
            return
        
        try:
            # Detect markers using the old API
            corners, ids, rejected = cv2.aruco.detectMarkers(frame, self.aruco_dict)
            
            if ids is not None:
                # Marker detected
                marker_msg = String()
                marker_msg.data = f'Marker detected: {ids.flatten().tolist()}'
                self.marker_publisher.publish(marker_msg)
                self.get_logger().info(f'Marker detected: {ids.flatten().tolist()}')
            
        except Exception as e:
            self.get_logger().error(f'Error processing frame: {str(e)}')

def main(args=None):
    rclpy.init(args=args)
    node = ArucoDetectorNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()  