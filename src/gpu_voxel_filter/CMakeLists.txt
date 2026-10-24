cmake_minimum_required(VERSION 3.18)
project(gpu_voxel_filter LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CUDA_STANDARD 17)
# Jetson AGX Orin (sm_87); override with -DCMAKE_CUDA_ARCHITECTURES=... elsewhere
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 87)
endif()

find_package(ament_cmake REQUIRED)
find_package(CUDAToolkit REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(sensor_msgs REQUIRED)

# GPU core, no ROS dependency; also used by utils/gpu_voxel_filter_bench
add_library(gpu_voxel_grid SHARED src/gpu_voxel_grid.cu)
target_include_directories(gpu_voxel_grid PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_link_libraries(gpu_voxel_grid PUBLIC CUDA::cudart)

add_library(voxel_filter_component SHARED src/voxel_filter.cpp)
target_link_libraries(voxel_filter_component gpu_voxel_grid)
ament_target_dependencies(voxel_filter_component rclcpp rclcpp_components sensor_msgs)
rclcpp_components_register_node(voxel_filter_component
  PLUGIN "gpu_voxel_filter::VoxelFilter"
  EXECUTABLE voxel_filter_node)

install(TARGETS gpu_voxel_grid EXPORT export_gpu_voxel_filter
  LIBRARY DESTINATION lib ARCHIVE DESTINATION lib RUNTIME DESTINATION bin)
install(TARGETS voxel_filter_component
  LIBRARY DESTINATION lib ARCHIVE DESTINATION lib RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY config DESTINATION share/${PROJECT_NAME})

ament_export_targets(export_gpu_voxel_filter HAS_LIBRARY_TARGET)
ament_export_dependencies(CUDAToolkit)
ament_package()
