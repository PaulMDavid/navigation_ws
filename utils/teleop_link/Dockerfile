FROM ros:humble-ros-base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip ros-humble-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir websockets==12.0
WORKDIR /probe
