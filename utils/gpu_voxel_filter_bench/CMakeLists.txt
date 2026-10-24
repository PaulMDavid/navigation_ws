cmake_minimum_required(VERSION 3.18)
project(gpu_voxel_filter_bench LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

find_package(ament_cmake REQUIRED)
find_package(gpu_voxel_filter REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rosbag2_cpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(PCL REQUIRED COMPONENTS common filters)

add_executable(bench src/bench.cpp)
target_include_directories(bench PRIVATE ${PCL_INCLUDE_DIRS})
target_link_libraries(bench gpu_voxel_filter::gpu_voxel_grid ${PCL_LIBRARIES})
ament_target_dependencies(bench rclcpp rosbag2_cpp sensor_msgs pcl_conversions)

install(TARGETS bench DESTINATION lib/${PROJECT_NAME})
ament_package()
