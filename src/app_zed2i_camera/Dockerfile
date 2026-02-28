# ------------------------------------------------------------
# Base image: ZED SDK 5.1 for Jetson L4T R36.4 (JetPack 6.1)
# ------------------------------------------------------------
FROM stereolabs/zed:5.1-devel-l4t-r36.4

# ------------------------------------------------------------
# Environment variables for ROS2 and ZED
# ------------------------------------------------------------
ENV ROS_DISTRO=humble
ENV ZED_SDK_ROOT=/usr/local/zed
# ------------------------------------------------------------
# Environment variables for ROS2 and ZED
# ------------------------------------------------------------
ENV ROS_DISTRO=humble
ENV ZED_SDK_ROOT=/usr/local/zed
ENV CMAKE_PREFIX_PATH=/usr/local/zed:/opt/ros/humble:$CMAKE_PREFIX_PATH
ENV ZED_DIR=/usr/local/zed
ENV LD_LIBRARY_PATH=/usr/local/zed/lib:/usr/local/zed/lib64:$LD_LIBRARY_PATH
ENV PATH=/usr/local/zed/bin:$PATH
ENV PYTHONPATH=/usr/local/zed/lib/python3.10/site-packages:$PYTHONPATH

# ... rest of your Dockerfile stays the same
# ------------------------------------------------------------
# Install ROS2 Humble desktop essentials
# ------------------------------------------------------------

# Setup sources for ROS Humble
RUN apt-get update && apt-get install -y curl gnupg lsb-release && \
    curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | apt-key add - && \
    sh -c 'echo "deb http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" > /etc/apt/sources.list.d/ros2.list'


RUN apt-get update && apt-get install -y \
    ros-humble-ros-base \
    python3-colcon-common-extensions \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Create workspace and copy your source code
# ------------------------------------------------------------
WORKDIR /ros2_ws
COPY ./zed-ros2-wrapper /ros2_ws/src/zed_ros2_wrapper


# Install dependencies via rosdep
RUN apt-get update && apt-get install -y python3-rosdep
RUN rosdep init || true
RUN rosdep update
RUN /bin/bash -c "cd /ros2_ws && rosdep install --from-paths src --ignore-src -r -y"

# Fix ZED library path for Jetson
#RUN mkdir -p /usr/local/zed/lib/cmake/ZED/lib && \
#    ln -s /usr/local/zed/lib/libsl_zed.so /usr/local/zed/lib/cmake/ZED/lib/libsl_zed.so

# ------------------------------------------------------------
# Build workspace
# ------------------------------------------------------------
RUN /bin/bash -c "source /opt/ros/humble/setup.bash && \
                  colcon build --symlink-install --cmake-args -DZED_DIR=/usr/local/zed"

# ------------------------------------------------------------
# Set entrypoint
# ------------------------------------------------------------
WORKDIR /ros2_ws
#ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/humble/setup.bash && source install/setup.bash && exec bash"]
