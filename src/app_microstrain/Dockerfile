ARG ROS_DISTRO=humble
ARG RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
FROM ros:${ROS_DISTRO}-ros-core AS build-env
ARG RMW_IMPLEMENTATION
ARG ROS_DISTRO
ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=${ROS_DISTRO} \
    RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION}
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git \
    python3-rosdep python3-colcon-common-extensions \
    ros-${ROS_DISTRO}-microstrain-inertial-driver \
    ros-${ROS_DISTRO}-microstrain-inertial-msgs \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
RUN mkdir -p /workspace/src
RUN rosdep init && rosdep update
COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh
ENTRYPOINT ["/postcreatecommand.sh"]
