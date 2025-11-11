#!/bin/bash
set -e

echo "Running postCreateCommand.sh ..."

# Go to workspace
cd /workspace

# Ensure src folder exists
mkdir -p src

# Initialize rosdep
sudo rosdep init 2>/dev/null || true
rosdep update

# Install missing dependencies
rosdep install --from-paths src --ignore-src -r -y

# Build the workspace
colcon build --symlink-install

# Source environment setup for all shells
echo "source /workspace/install/setup.bash" >> ~/.bashrc

# Set CycloneDDS as default RMW (since you installed it)
echo "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" >> ~/.bashrc

echo "✅ Post-create setup complete."
