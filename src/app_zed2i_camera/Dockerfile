# Base image: ZED SDK 5.1 for Jetson L4T R36.4 (JetPack 6.1)
FROM stereolabs/zed:5.1-devel-l4t-r36.4

# Environment
ENV ROS_DISTRO=humble
ENV ZED_SDK_ROOT=/usr/local/zed
ENV ZED_DIR=/usr/local/zed
ENV CMAKE_PREFIX_PATH=/usr/local/zed:/opt/ros/humble:$CMAKE_PREFIX_PATH
ENV LD_LIBRARY_PATH=/usr/local/zed/lib:/usr/local/zed/lib64:$LD_LIBRARY_PATH
ENV PATH=/usr/local/zed/bin:$PATH
ENV PYTHONPATH=/usr/local/zed/lib/python3.10/site-packages:$PYTHONPATH
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# Install ROS 2 Humble + build tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        lsb-release \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        | apt-key add - \
    && echo "deb http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-humble-ros-base \
        ros-humble-rmw-cyclonedds-cpp \
        python3-colcon-common-extensions \
        python3-rosdep \
    && rosdep init \
    && rosdep update \
    && rm -rf /var/lib/apt/lists/*
    
COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh

WORKDIR /workspace

ENTRYPOINT ["/postcreatecommand.sh"]
