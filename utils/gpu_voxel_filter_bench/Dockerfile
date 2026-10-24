# Build/run environment for the benchmark: the ZED image (ROS 2 Humble + CUDA 12.6
# on L4T r36.4, built from src/app_zed2i_camera) plus PCL for the CPU comparison.
ARG BASE=src-app_zed2i_camera:latest
FROM ${BASE}
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-pcl-conversions libpcl-dev python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*
