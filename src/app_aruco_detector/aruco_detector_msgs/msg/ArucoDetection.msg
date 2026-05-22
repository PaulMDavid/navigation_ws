# Single ArUco marker detection in the sensor (camera optical) frame.
# Consumers should use TF2 to transform to their desired target frame.

std_msgs/Header header        # stamp from image message; frame_id = camera optical frame

int32 id                      # ArUco marker ID

geometry_msgs/Pose pose       # 6-DOF pose of the marker centre in header.frame_id
                              # position: metres; orientation: quaternion (solvePnP -> Rodrigues)

float64 distance              # Euclidean distance from camera origin to marker centre [m]

# 2-D pixel corners of the marker in image coordinates (clockwise from top-left).
# Useful for debug overlays and reprojection validation.
# Order: top-left, top-right, bottom-right, bottom-left
geometry_msgs/Point32[4] corners_px
