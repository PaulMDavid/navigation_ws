ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}

# ublox_dgnss talks to the ZED-F9P over raw USB (libusb), not a serial port,
# so libusb-1.0 and udev are required at runtime, not just at build time.
RUN apt-get update && apt-get install -y \
    git wget curl vim nano \
    python3-pip python3-colcon-common-extensions python3-rosdep \
    libusb-1.0-0 udev usbutils \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-ublox-dgnss \
    ros-${ROS_DISTRO}-ntrip-client \
    ros-${ROS_DISTRO}-robot-localization \
    ros-${ROS_DISTRO}-foxglove-bridge \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
RUN mkdir -p /workspace/src
RUN rosdep update

COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh

ENTRYPOINT ["/postcreatecommand.sh"]
