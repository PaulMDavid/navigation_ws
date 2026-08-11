# ──────────────────────────────────────────────────────────────
# Groundstation image — RViz2 + Nav2 plugins, for visualizing /
# commanding the Jetson's nav stack from your PC over the network.
# ──────────────────────────────────────────────────────────────
FROM osrf/ros:humble-desktop

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-rviz2 \
    ros-humble-nav2-rviz-plugins \
    ros-humble-nav2-bringup \
    ros-humble-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc

WORKDIR /workspace

CMD ["bash"]
