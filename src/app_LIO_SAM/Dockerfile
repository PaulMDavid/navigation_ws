ARG ROS_DISTRO=humble
FROM ros:${ROS_DISTRO}-ros-base
# NOTE: for arm64/Jetson, use:
# FROM --platform=linux/arm64 ros:${ROS_DISTRO}-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DISTRO=${ROS_DISTRO}

# g2o — build from source (not in Ubuntu 22.04 repos)
# -j2: each g2o compile job needs ~3 GB; -j$(nproc) OOM-killed a 16 GB laptop, and
# laptop builds are capped at 8 GB (utils/build_memory_cap)
RUN git clone https://github.com/RainerKuemmerle/g2o.git /tmp/g2o \
    && cd /tmp/g2o \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release \
    && make -j2 \
    && make install \
    && rm -rf /tmp/g2o

RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository ppa:borglab/gtsam-release-4.1 \
    && apt-get update && apt-get install -y \
    # Build tools
    git wget curl vim nano \
    cmake build-essential \
    python3-pip python3-colcon-common-extensions python3-rosdep \
    # PCL
    libpcl-dev \
    ros-${ROS_DISTRO}-pcl-ros \
    ros-${ROS_DISTRO}-pcl-conversions \
    # OpenMP
    libomp-dev \
    # Eigen
    libeigen3-dev \
    # GTSAM
    libgtsam-dev libgtsam-unstable-dev \
    # Boost
    libboost-all-dev \
    # ROS middleware + common interfaces
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-rviz2 \
    ros-${ROS_DISTRO}-sensor-msgs \
    ros-${ROS_DISTRO}-geometry-msgs \
    ros-${ROS_DISTRO}-nav-msgs \
    ros-${ROS_DISTRO}-tf2 \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-tf2-eigen \
    ros-${ROS_DISTRO}-tf2-geometry-msgs \
    # Visualization / diagnostics
    ros-${ROS_DISTRO}-rqt \
    ros-${ROS_DISTRO}-rqt-common-plugins \
    && rm -rf /var/lib/apt/lists/*

# Auto-source ROS in every terminal
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc \
    && echo "source /workspace/install/setup.bash 2>/dev/null || true" >> /root/.bashrc

WORKDIR /workspace
RUN mkdir -p /workspace/src

RUN rosdep update

COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh

ENTRYPOINT ["/postcreatecommand.sh"]