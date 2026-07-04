ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}-ros-base
#NOTE use the following line for arm64 architecture, and the line above for amd64 architecture, when building on jetson
#FROM --platform=linux/arm64 ros:${ROS_DISTRO}-ros-base
ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}
RUN apt-get update && apt-get install -y \
    git wget curl vim nano \
    python3-pip python3-colcon-common-extensions python3-rosdep \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-robot-localization \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
RUN mkdir -p /workspace/src
RUN rosdep update
COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh
# Set as entrypoint
ENTRYPOINT ["/postcreatecommand.sh"]
