# =============================================================================
# Ouster ROS2 Docker Build
# =============================================================================

# Build arguments
ARG ROS_DISTRO=humble
ARG RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# =============================================================================
# Build Environment Stage
# =============================================================================
FROM ros:${ROS_DISTRO}-ros-core AS build-env

# Re-declare ARGs after FROM (required by Docker)
ARG ROS_DISTRO
ARG RMW_IMPLEMENTATION

# Environment configuration
ENV DEBIAN_FRONTEND=noninteractive \
    RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION} \
    BUILD_HOME=/var/lib/build \
    OUSTER_ROS_PATH=/opt/src/ouster-ros \
    ROS_SETUP=/opt/ros/${ROS_DISTRO}/setup.bash

 SHELL ["/bin/bash", "-c"]

# Install build dependencies (single apt-get update for efficiency)
RUN set -xue && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        fakeroot \
        dpkg-dev \
        python3-rosdep \
        python3-rospkg \
        python3-bloom \
        python3-colcon-common-extensions \
        # Ouster SDK dependencies (libcurl4-openssl-dev renamed in Ubuntu 24.04)
        ros-$ROS_DISTRO-pcl-ros     \
        ros-$ROS_DISTRO-tf2-eigen   \
        ros-$ROS_DISTRO-rviz2       \
        build-essential         \
        libeigen3-dev           \
        libjsoncpp-dev          \
        libspdlog-dev           \
        libcurl4-openssl-dev    \
        cmake                   \
        python3-colcon-common-extensions    \
        ros-humble-foxglove-bridge          && \
    # Install optional RMW implementation
    if [ "$RMW_IMPLEMENTATION" = "rmw_cyclonedds_cpp" ]; then \
        apt-get install -y --no-install-recommends ros-${ROS_DISTRO}-rmw-cyclonedds-cpp; \
    elif [ "$RMW_IMPLEMENTATION" = "rmw_zenoh_cpp" ]; then \
        apt-get install -y --no-install-recommends ros-${ROS_DISTRO}-rmw-zenoh-cpp; \
    fi && \
    rm -rf /var/lib/apt/lists/*

# Create non-root build user
ARG BUILD_UID=1000
ARG BUILD_GID=${BUILD_UID}

RUN groupadd -o -g ${BUILD_GID} build && \
    useradd -o -u ${BUILD_UID} -d ${BUILD_HOME} -rm -s /bin/bash -g build build

# Copy source and install ROS dependencies
COPY --chown=build:build . ${OUSTER_ROS_PATH}

RUN apt-get update && \
    rosdep init && \
    rosdep update --rosdistro=${ROS_DISTRO} && \
    rosdep install --from-paths ${OUSTER_ROS_PATH} -y --ignore-src || true && \
    rm -rf /var/lib/apt/lists/*

# Switch to build user
USER build:build
WORKDIR ${BUILD_HOME}

 RUN mkdir src && cp -R ${OUSTER_ROS_PATH} ./src/

# =============================================================================
# Final Build Stage
# =============================================================================
FROM build-env

# Build and test the workspace
RUN source ${ROS_SETUP} && \
    colcon build \
        --symlink-install \
        --cmake-args \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_CXX_FLAGS="-Wno-deprecated-declarations"

# RUN source ${ROS_SETUP} && \
#     colcon test \
#         --ctest-args tests ouster_ros \
#         --rerun-failed \
#         --output-on-failure

# =============================================================================
# Runtime Configuration
# =============================================================================
# Usage: docker run --rm -it ouster-ros [sensor.launch parameters ..]
ENTRYPOINT ["bash", "-c", "set -e \
    && source ./install/setup.bash \
    && source /opt/ros/humble/setup.bash \
    && ros2 launch ouster_ros sensor.launch.xml \"$@\"", \
    "ros-entrypoint"]
