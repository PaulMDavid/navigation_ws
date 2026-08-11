FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y \
    ros-humble-rtabmap-ros \
    ros-humble-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
