# =====================================================================
# BASE IMAGE — choose desired ROS 2 distribution (humble, iron, jazzy…)
# =====================================================================
ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}-desktop

ARG ROS_DISTRO

# =====================================================================
# SYSTEM DEPENDENCIES
# =====================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    libeigen3-dev \
    libjsoncpp-dev \
    libspdlog-dev \
    libcurl4-openssl-dev \
    libpcap-dev \
    python3-colcon-common-extensions \
    ros-${ROS_DISTRO}-pcl-ros \
    ros-${ROS_DISTRO}-tf2-eigen \
    ros-${ROS_DISTRO}-rviz2 \
    && rm -rf /var/lib/apt/lists/*

# =====================================================================
# CREATE WORKSPACE AND CLONE OUSTER DRIVER
# =====================================================================
RUN mkdir -p /ros2_ws/src
WORKDIR /ros2_ws/src

RUN git clone -b ros2 --recurse-submodules https://github.com/ouster-lidar/ouster-ros.git

# =====================================================================
# BUILD DRIVER
# =====================================================================
WORKDIR /ros2_ws

# source ros and build
RUN /bin/bash -c "source /opt/ros/${ROS_DISTRO}/setup.bash && \
    colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release"

# =====================================================================
# ENVIRONMENT SETUP
# =====================================================================
# Source ROS + workspace every time container starts
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc \
 && echo "source /ros2_ws/install/setup.bash" >> /root/.bashrc

ENV ROS_DISTRO=${ROS_DISTRO}

# Useful default entry point
ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/${ROS_DISTRO}/setup.bash && source /ros2_ws/install/setup.bash && exec bash"]

