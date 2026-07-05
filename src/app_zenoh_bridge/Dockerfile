ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

# Eclipse Zenoh apt repo — provides zenoh-bridge-ros2dds binary (multi-arch: amd64 + arm64)
RUN echo "deb [trusted=yes] https://download.eclipse.org/zenoh/debian-repo/ /" \
    | tee /etc/apt/sources.list.d/zenoh.list \
    && apt-get update \
    && apt-get install -y zenoh-bridge-ros2dds \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/zenoh
COPY config/zenoh_bridge_robot.json5 /etc/zenoh/config.json5

ENTRYPOINT ["zenoh-bridge-ros2dds"]
CMD ["-c", "/etc/zenoh/config.json5"]
