# Official multi-arch image (amd64 + arm64). The ground station runs the same tag:
# both ends of a Zenoh link should be the same version.
FROM eclipse/zenoh-bridge-ros2dds:1.8.0

# Humble uses 24-byte GIDs on ros_discovery_info; without this the bridge assumes iron
ENV ROS_DISTRO=humble

COPY config/zenoh_bridge_robot.json5 /etc/zenoh/config.json5

CMD ["-c", "/etc/zenoh/config.json5"]
