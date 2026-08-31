# Base image: ZED SDK 5.1 for Jetson L4T R36.4 (JetPack 6.1) — same base as
# app_zed2i_camera/app_rtab_zed2i, since it's the most particular image in this repo
# (CUDA/TensorRT/ZED SDK baked in for the Jetson) and everything else here can be layered
# on top of it via plain apt/source builds.
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
ENV DEBIAN_FRONTEND=noninteractive

# Install ROS 2 Humble + deps for: zed_wrapper, ouster_ros, and FAST-LIVO2
# (rclcpp/pcl/cv_bridge/vikit/Sophus/etc — see package.xml of the FAST-LIVO2 fork).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        lsb-release \
        cmake \
        build-essential \
        git \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        | apt-key add - \
    && echo "deb http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-humble-ros-base \
        ros-humble-rmw-cyclonedds-cpp \
        ros-humble-zed-msgs \
        ros-humble-nmea-msgs \
        ros-humble-geographic-msgs \
        ros-humble-image-transport \
        ros-humble-ament-cmake-auto \
        ros-humble-tf2 \
        ros-humble-tf2-ros \
        ros-humble-tf2-geometry-msgs \
        ros-humble-geometry-msgs \
        ros-humble-nav-msgs \
        ros-humble-stereo-msgs \
        ros-humble-sensor-msgs \
        ros-humble-std-srvs \
        ros-humble-diagnostic-msgs \
        ros-humble-visualization-msgs \
        ros-humble-shape-msgs \
        ros-humble-robot-localization \
        ros-humble-backward-ros \
        ros-humble-xacro \
        ros-humble-rclcpp-components \
        ros-humble-pcl-ros \
        ros-humble-pcl-conversions \
        ros-humble-cv-bridge \
        ros-humble-demo-nodes-cpp \
        ros-humble-rviz2 \
        libeigen3-dev \
        libopencv-dev \
        libpcl-dev \
        libboost-filesystem-dev \
        libboost-system-dev \
        libboost-thread-dev \
        libfmt-dev \
        python3-colcon-common-extensions \
        python3-rosdep \
    && rosdep init \
    && rosdep update \
    && rm -rf /var/lib/apt/lists/*

# Sophus, pinned to the version FAST-LIVO2 (hku-mars family) builds against.
# Not packaged for Jetson/L4T, so it's built from source and installed system-wide.
RUN git clone https://github.com/strasdat/Sophus.git -b 1.22.10 /opt/Sophus \
    && cd /opt/Sophus && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF \
    && make -j"$(nproc)" && make install

# Livox-SDK2: C library required by livox_ros_driver2. Installed system-wide, not part
# of the ROS workspace.
COPY Livox-SDK2 /opt/Livox-SDK2
RUN cd /opt/Livox-SDK2 && mkdir -p build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j"$(nproc)" && make install

# livox_ros_driver2: FAST-LIVO2's CMakeLists hard-requires this package to exist at build
# time (find_package(livox_ros_driver2 REQUIRED)), even when running lidar_type=3 (Ouster)
# and never touching Livox hardware or the CustomMsg code path — see app_fast_livo2/README.md.
# Its own build.sh nukes build/install/devel in its *parent* workspace, so it's built here in
# an isolated throwaway workspace and baked into the image; the real /workspace (FAST-LIVO2,
# vikit, ouster_ros, zed_wrapper) is mounted and built fresh by postcreatecommand.sh instead.
COPY livox_ros_driver2 /opt/ws_livox/src/livox_ros_driver2
RUN /bin/bash -lc " \
    source /opt/ros/humble/setup.bash && \
    cd /opt/ws_livox/src/livox_ros_driver2 && \
    ./build.sh humble \
    "

COPY postcreatecommand.sh /postcreatecommand.sh
RUN chmod +x /postcreatecommand.sh

WORKDIR /workspace

ENTRYPOINT ["/postcreatecommand.sh"]
