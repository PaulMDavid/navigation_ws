FROM ros:noetic-ros-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl vim nano cmake build-essential \
    libpcl-dev libopencv-dev libeigen3-dev \
    python3-pip python3-catkin-tools \
    ros-noetic-cv-bridge \
    ros-noetic-pcl-ros \
    ros-noetic-pcl-conversions \
    ros-noetic-tf \
    ros-noetic-image-transport \
    ros-noetic-image-geometry \
    ros-noetic-rviz \
    ros-noetic-rosbag \
    && rm -rf /var/lib/apt/lists/*

# For scripts/distance_filter_tool.py (interactive point-picker used to find the
# calibration board in a raw scan before running calib.launch)
RUN pip3 install --no-cache-dir open3d

# Livox-SDK: required by livox_ros_driver, installed system-wide (not part of the catkin workspace)
RUN git clone https://github.com/Livox-SDK/Livox-SDK.git /opt/Livox-SDK \
    && cd /opt/Livox-SDK \
    && mkdir -p build && cd build \
    && cmake .. && make -j"$(nproc)" \
    && make install

# livox_ros_driver: message/driver package FAST-Calib depends on. Baked into the image since
# it's a fixed upstream dependency, not something we edit.
RUN mkdir -p /workspace/catkin_ws/src \
    && cd /workspace/catkin_ws/src \
    && git clone https://github.com/Livox-SDK/livox_ros_driver.git

WORKDIR /workspace/catkin_ws

COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh

ENTRYPOINT ["/postcreatecommand.sh"]
