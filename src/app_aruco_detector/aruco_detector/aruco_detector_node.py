#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, CameraInfo
from geometry_msgs.msg import Pose, Point, Quaternion, Point32
from aruco_detector_msgs.msg import ArucoDetection, ArucoDetectionArray
import cv2
import numpy as np


def rvec_to_quaternion(rvec: np.ndarray) -> Quaternion:
    """Convert an OpenCV rotation vector to a ROS Quaternion via Rodrigues."""
    rot_matrix, _ = cv2.Rodrigues(rvec)
    # Extract quaternion (w, x, y, z) from rotation matrix
    trace = rot_matrix[0, 0] + rot_matrix[1, 1] + rot_matrix[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (rot_matrix[2, 1] - rot_matrix[1, 2]) * s
        y = (rot_matrix[0, 2] - rot_matrix[2, 0]) * s
        z = (rot_matrix[1, 0] - rot_matrix[0, 1]) * s
    elif rot_matrix[0, 0] > rot_matrix[1, 1] and rot_matrix[0, 0] > rot_matrix[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rot_matrix[0, 0] - rot_matrix[1, 1] - rot_matrix[2, 2])
        w = (rot_matrix[2, 1] - rot_matrix[1, 2]) / s
        x = 0.25 * s
        y = (rot_matrix[0, 1] + rot_matrix[1, 0]) / s
        z = (rot_matrix[0, 2] + rot_matrix[2, 0]) / s
    elif rot_matrix[1, 1] > rot_matrix[2, 2]:
        s = 2.0 * np.sqrt(1.0 + rot_matrix[1, 1] - rot_matrix[0, 0] - rot_matrix[2, 2])
        w = (rot_matrix[0, 2] - rot_matrix[2, 0]) / s
        x = (rot_matrix[0, 1] + rot_matrix[1, 0]) / s
        y = 0.25 * s
        z = (rot_matrix[1, 2] + rot_matrix[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + rot_matrix[2, 2] - rot_matrix[0, 0] - rot_matrix[1, 1])
        w = (rot_matrix[1, 0] - rot_matrix[0, 1]) / s
        x = (rot_matrix[0, 2] + rot_matrix[2, 0]) / s
        y = (rot_matrix[1, 2] + rot_matrix[2, 1]) / s
        z = 0.25 * s
    q = Quaternion()
    q.x, q.y, q.z, q.w = float(x), float(y), float(z), float(w)
    return q


class ArucoDetectorNode(Node):
    def __init__(self):
        super().__init__('aruco_detector_node')
        self.get_logger().info('ArUco Detector node started.')

        # Declare parameters
        self.declare_parameter('aruco_dict', 'DICT_6X6_250')
        self.declare_parameter('image_topic', '/zed2i/zed_node/rgb/color/rect/image/compressed')
        self.declare_parameter('camera_info_topic', '/zed2i/zed_node/rgb/color/rect/camera_info')
        self.declare_parameter('camera_frame', 'zed2i_left_camera_optical_frame')
        self.declare_parameter('marker_size', 0.05)  # metres; override via params file

        self.camera_frame = self.get_parameter('camera_frame').get_parameter_value().string_value

        # Camera intrinsics — populated on first camera_info message
        self.camera_matrix: np.ndarray | None = None
        self.dist_coeffs: np.ndarray | None = None

        aruco_dict_name = self.get_parameter('aruco_dict').get_parameter_value().string_value
        self.get_logger().info(f'ArUco dictionary: {aruco_dict_name}')

        aruco_dict_id = getattr(cv2.aruco, aruco_dict_name, None)
        if aruco_dict_id is None:
            raise ValueError(f'Unknown ArUco dictionary: {aruco_dict_name}')
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(aruco_dict_id)
        self.aruco_params = cv2.aruco.DetectorParameters_create()

        # Publisher
        self.detections_pub = self.create_publisher(
            ArucoDetectionArray, 'aruco_detections', 10)

        # Subscribers
        camera_info_topic = self.get_parameter('camera_info_topic').get_parameter_value().string_value
        self.camera_info_sub = self.create_subscription(
            CameraInfo, camera_info_topic, self._camera_info_callback, 10)
        self.get_logger().info(f'Subscribing to camera_info: {camera_info_topic}')

        image_topic = self.get_parameter('image_topic').get_parameter_value().string_value
        self.image_sub = self.create_subscription(
            CompressedImage, image_topic, self._image_callback, 10)
        self.get_logger().info(f'Subscribing to image: {image_topic}')

    # ------------------------------------------------------------------ #

    def _camera_info_callback(self, msg: CameraInfo) -> None:
        if self.camera_matrix is not None:
            return  # already received
        self.camera_matrix = np.array(msg.k, dtype=np.float64).reshape(3, 3)
        self.dist_coeffs = np.array(msg.d, dtype=np.float64)
        self.get_logger().info(
            f'Camera intrinsics received — fx={self.camera_matrix[0,0]:.2f}, '
            f'fy={self.camera_matrix[1,1]:.2f}, '
            f'cx={self.camera_matrix[0,2]:.2f}, cy={self.camera_matrix[1,2]:.2f}'
        )

    def _image_callback(self, msg: CompressedImage) -> None:
        if self.camera_matrix is None:
            self.get_logger().warning(
                'Waiting for camera_info…', throttle_duration_sec=5.0)
            return
        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except Exception as exc:
            self.get_logger().error(f'Image decode error: {exc}')
            return
        if frame is None:
            self.get_logger().error('cv2.imdecode returned None')
            return
        self._detect_and_publish(frame, msg.header)

    def _detect_and_publish(self, frame: np.ndarray, image_header) -> None:
        corners, ids, _ = cv2.aruco.detectMarkers(frame, self.aruco_dict, parameters=self.aruco_params)

        array_msg = ArucoDetectionArray()
        array_msg.header.stamp = image_header.stamp
        array_msg.header.frame_id = self.camera_frame

        if ids is None:
            self.detections_pub.publish(array_msg)
            return

        # Recompute every frame so runtime parameter changes take effect
        half = self.get_parameter('marker_size').get_parameter_value().double_value / 2.0
        obj_points = np.array([
            [-half,  half, 0.0],
            [ half,  half, 0.0],
            [ half, -half, 0.0],
            [-half, -half, 0.0],
        ], dtype=np.float32)

        for i, marker_id in enumerate(ids.flatten()):
            corner_pts = corners[i][0]  # shape (4, 2)

            ok, rvec, tvec = cv2.solvePnP(
                obj_points, corner_pts,
                self.camera_matrix, self.dist_coeffs,
                flags=cv2.SOLVEPNP_IPPE_SQUARE,
            )
            if not ok:
                self.get_logger().warning(f'solvePnP failed for marker id={marker_id}')
                continue

            tvec = tvec.flatten()
            detection = ArucoDetection()
            detection.header.stamp = image_header.stamp
            detection.header.frame_id = self.camera_frame
            detection.id = int(marker_id)

            detection.pose = Pose(
                position=Point(x=float(tvec[0]), y=float(tvec[1]), z=float(tvec[2])),
                orientation=rvec_to_quaternion(rvec),
            )
            detection.distance = float(np.linalg.norm(tvec))

            # Pixel corners: top-left, top-right, bottom-right, bottom-left
            # Fixed-size array field — must assign all 4 at once, not append
            detection.corners_px = [
                Point32(x=float(pt[0]), y=float(pt[1]), z=0.0)
                for pt in corner_pts
            ]

            array_msg.detections.append(detection)

        self.detections_pub.publish(array_msg)
        if array_msg.detections:
            ids_seen = [d.id for d in array_msg.detections]
            self.get_logger().info(f'Detected markers: {ids_seen}')


def main(args=None):
    rclpy.init(args=args)
    node = ArucoDetectorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()

