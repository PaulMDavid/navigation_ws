# Array of ArUco marker detections from a single image frame.
# header.stamp and header.frame_id match those of the individual detections.

std_msgs/Header header
ArucoDetection[] detections
