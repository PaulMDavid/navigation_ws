#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage, CameraInfo
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
        self.declare_parameter('image_topic', '/zed/zed_node/rgb/color/rect/image/compressed')
        self.declare_parameter('camera_info_topic', '/zed/zed_node/rgb/color/rect/camera_info')
        self.declare_parameter('marker_size', rclpy.Parameter.Type.DOUBLE)

        self.marker_size = self.get_parameter('marker_size').value

        # Intrinsics will be populated from camera_info
        self.fx = None
        self.fy = None
        self.cx = None
        self.cy = None
        self.camera_info_received = False

        aruco_dict_name = self.get_parameter('aruco_dict').get_parameter_value().string_value
        camera_id = self.get_parameter('camera_id').get_parameter_value().integer_value
        use_webcam = self.get_parameter('use_webcam').get_parameter_value().bool_value

        self.get_logger().info(f'Using ArUco dictionary: {aruco_dict_name}')

        # Get the ArUco dictionary
        try:
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(
                getattr(cv2.aruco, aruco_dict_name)
            )
        except:
            self.aruco_dict = getattr(cv2.aruco, aruco_dict_name)

        self.marker_publisher = self.create_publisher(String, 'marker_detected', 10)
        self.bridge = CvBridge()
        self.camera_id = camera_id

        # Subscribe to camera_info to get intrinsics automatically
        camera_info_topic = self.get_parameter('camera_info_topic').get_parameter_value().string_value
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            camera_info_topic,
            self.camera_info_callback,
            10
        )
        self.get_logger().info(f'Subscribing to camera_info: {camera_info_topic}')

        image_topic = self.get_parameter('image_topic').get_parameter_value().string_value
        self.get_logger().info(f'Subscribing to image topic: {image_topic}')
        self.image_sub = self.create_subscription(
            CompressedImage,
            image_topic,
            self.image_callback,
            10
        )

    def camera_info_callback(self, msg):
        """Get camera intrinsics from camera_info topic"""
        if not self.camera_info_received:
            self.fx = msg.k[0]
            self.fy = msg.k[4]
            self.cx = msg.k[2]
            self.cy = msg.k[5]
            self.camera_info_received = True
            self.get_logger().info(
                f'Camera intrinsics received: fx={self.fx:.2f}, fy={self.fy:.2f}, '
                f'cx={self.cx:.2f}, cy={self.cy:.2f}'
            )

    def image_callback(self, msg):
        """Process frames from ROS compressed image topic"""
        if not self.camera_info_received:
            self.get_logger().warn('Waiting for camera_info...', throttle_duration_sec=5.0)
            return
        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                self.get_logger().error('Failed to decode compressed image')
                return
        except Exception as e:
            self.get_logger().error(f'Image decode error: {str(e)}')
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
