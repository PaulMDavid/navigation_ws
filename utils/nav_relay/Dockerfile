FROM ros:humble-ros-base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pytest python3-opencv ros-humble-rmw-cyclonedds-cpp ros-humble-nav2-msgs \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /test
