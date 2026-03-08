#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
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
        self.declare_parameter('image_topic', '/zed/camera/image_rect')
        self.declare_parameter('marker_size', rclpy.Parameter.Type.DOUBLE)
        self.declare_parameter('fx', rclpy.Parameter.Type.DOUBLE)
        self.declare_parameter('fy', rclpy.Parameter.Type.DOUBLE)
        self.declare_parameter('cx', rclpy.Parameter.Type.DOUBLE)
        self.declare_parameter('cy', rclpy.Parameter.Type.DOUBLE)

        self.marker_size = self.get_parameter('marker_size').value
        self.fx = self.get_parameter('fx').value
        self.fy = self.get_parameter('fy').value
        self.cx = self.get_parameter('cx').value
        self.cy = self.get_parameter('cy').value
                
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
        
        self.bridge = CvBridge()
        self.camera_id = camera_id

        # Check if topic exists and has a publisher; else fall back to webcam
        image_topic = self.get_parameter('image_topic').get_parameter_value().string_value
        topic_available = False
        if not use_webcam and image_topic:
            topic_names = [name for name, _ in self.get_topic_names_and_types()]
            if image_topic in topic_names:
                pubs = self.count_publishers(image_topic)
                if pubs > 0:
                    topic_available = True

        if topic_available:
            self.get_logger().info(f'Topic {image_topic} found with publisher(s), subscribing')
            self.image_sub = self.create_subscription(
                Image,
                image_topic,
                self.image_callback,
                10
            )
        else:
            if not use_webcam and image_topic:
                self.get_logger().warn(
                    f'Topic {image_topic} not available or has no publishers, falling back to webcam')
            self.get_logger().info(f'Opening webcam {camera_id}')
            self.cap = cv2.VideoCapture(camera_id)
            if not self.cap.isOpened():
                self.get_logger().error(f'Failed to open webcam {camera_id}')
                return
            self.timer = self.create_timer(0.03, self.process_frame)  # ~30 Hz
    
    def image_callback(self, msg):
        """Process frames from ROS image topic"""
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'cv_bridge error: {str(e)}')
            return
        self.detect_markers(frame)

    def process_frame(self):
        """Process frames from webcam"""
        ret, frame = self.cap.read()
        if not ret:
            self.get_logger().error('Failed to read frame from webcam')
            return
        self.detect_markers(frame)

    def detect_markers(self, frame):
        try:
            corners, ids, rejected = cv2.aruco.detectMarkers(frame, self.aruco_dict)

            if ids is not None:
                marker_data = []
                half = self.marker_size / 2.0
                obj_points = np.array([[-half,  half, 0],
                                        [ half,  half, 0],
                                        [ half, -half, 0],
                                        [-half, -half, 0]], dtype=np.float32)
                camera_matrix = np.array([[self.fx,       0, self.cx],
                                        [      0, self.fy, self.cy],
                                        [      0,       0,       1]], dtype=np.float32)

                for i, marker_id in enumerate(ids.flatten()):
                    corner_points = corners[i][0]
                    center_u = float(np.mean(corner_points[:, 0]))
                    center_v = float(np.mean(corner_points[:, 1]))

                    ret, rvec, tvec = cv2.solvePnP(obj_points, corner_points,
                                                camera_matrix, None)
                    distance = float(np.linalg.norm(tvec))

                    marker_data.append({
                        'id': int(marker_id),
                        'center_u': center_u,
                        'center_v': center_v,
                        'distance': distance
                    })

                marker_msg = String()
                marker_msg.data = str(marker_data)
                self.marker_publisher.publish(marker_msg)
                self.get_logger().info(f'Markers detected: {marker_data}')

        except Exception as e:
            self.get_logger().error(f'Error processing frame: {str(e)}')

def main(args=None):
    rclpy.init(args=args)
    node = ArucoDetectorNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()  