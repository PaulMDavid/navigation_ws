# app_nav_master: the whole nav stack as composable nodes in one process, so the heavy
# topics (Ouster clouds, ZED images) move intra-process instead of over DDS.
# Same base as app_zed2i_camera: L4T R36.4 + CUDA 12.6 + ZED SDK 5.1.
# Build context is src/ (see docker-compose.yaml) so rosdep can read the driver sources.
FROM stereolabs/zed:5.1-devel-l4t-r36.4

ENV ROS_DISTRO=humble
ENV ZED_SDK_ROOT=/usr/local/zed
ENV ZED_DIR=/usr/local/zed
ENV CMAKE_PREFIX_PATH=/usr/local/zed:/opt/ros/humble:$CMAKE_PREFIX_PATH
ENV LD_LIBRARY_PATH=/usr/local/zed/lib:/usr/local/zed/lib64:$LD_LIBRARY_PATH
ENV PATH=/usr/local/zed/bin:/usr/local/cuda/bin:$PATH
ENV PYTHONPATH=/usr/local/zed/lib/python3.10/site-packages:$PYTHONPATH
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gnupg lsb-release software-properties-common \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | apt-key add - \
    && echo "deb http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && add-apt-repository -y ppa:borglab/gtsam-release-4.1 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential cmake git iputils-ping \
        python3-colcon-common-extensions python3-rosdep \
        ros-humble-ros-base \
        ros-humble-rmw-cyclonedds-cpp \
        ros-humble-rclcpp-components \
        ros-humble-robot-state-publisher \
        ros-humble-tf2-ros ros-humble-tf2-eigen ros-humble-tf2-sensor-msgs ros-humble-tf2-geometry-msgs \
        ros-humble-pcl-ros ros-humble-pcl-conversions ros-humble-pcl-msgs \
        ros-humble-cv-bridge ros-humble-image-transport \
        ros-humble-zed-msgs ros-humble-nmea-msgs ros-humble-geographic-msgs \
        ros-humble-robot-localization ros-humble-backward-ros ros-humble-xacro \
        ros-humble-rtabmap-ros \
        ros-humble-navigation2 ros-humble-nav2-bringup \
        ros-humble-microstrain-inertial-driver ros-humble-microstrain-inertial-msgs \
        ros-humble-ublox-dgnss libusb-1.0-0 udev \
        libeigen3-dev libpcl-dev libopencv-dev libomp-dev libboost-all-dev \
        libgtsam-dev libgtsam-unstable-dev \
    && rosdep init && rosdep update \
    && rm -rf /var/lib/apt/lists/*

# g2o for li_slam's graph_based_slam (not packaged for 22.04). Pinned: newer releases
# dropped g2o::make_unique, which li_slam_ros2 still calls.
RUN git clone --depth 1 -b 20201223_git https://github.com/RainerKuemmerle/g2o.git /tmp/g2o \
    && cmake -S /tmp/g2o -B /tmp/g2o/build -DCMAKE_BUILD_TYPE=Release \
        -DG2O_BUILD_APPS=OFF -DG2O_BUILD_EXAMPLES=OFF \
    && cmake --build /tmp/g2o/build -j4 && cmake --install /tmp/g2o/build \
    && ldconfig && rm -rf /tmp/g2o

# Remaining system deps of the sources built at container start, resolved from their
# package.xml files. Only the manifests matter; the sources are mounted at runtime.
COPY app_lidar_ouster_ros/ouster-ros /tmp/deps/ouster-ros
COPY app_lidar_ouster_ros/ouster-sensor-msgs /tmp/deps/ouster-sensor-msgs
COPY app_zed2i_camera/zed-ros2-wrapper /tmp/deps/zed-ros2-wrapper
COPY app_LIO_SAM/li_slam_ros2 /tmp/deps/li_slam_ros2
RUN apt-get update \
    && rosdep install --from-paths /tmp/deps --ignore-src -y -r \
        --skip-keys "libg2o ament_python zed_msgs" \
    && rm -rf /var/lib/apt/lists/* /tmp/deps

COPY app_nav_master/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
# the real command, with Nav2's params files, is in docker-compose.yaml
CMD ["ros2", "run", "rclcpp_components", "component_container_isolated", \
     "--ros-args", "-r", "ComponentManager:__node:=nav_master_container"]
