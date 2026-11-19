cmake_minimum_required(VERSION 3.8)
project(app_body_tilt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)

add_library(body_tilt_component SHARED src/body_tilt.cpp)
ament_target_dependencies(body_tilt_component
  rclcpp rclcpp_components sensor_msgs tf2 tf2_ros tf2_geometry_msgs)
rclcpp_components_register_node(body_tilt_component
  PLUGIN "app_body_tilt::BodyTilt"
  EXECUTABLE body_tilt_node)

install(TARGETS body_tilt_component
  LIBRARY DESTINATION lib ARCHIVE DESTINATION lib RUNTIME DESTINATION bin)

ament_package()
