cmake_minimum_required(VERSION 3.8)
project(app_wheel_joint_states LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

add_library(wheel_joint_states_component SHARED src/wheel_joint_states.cpp)
ament_target_dependencies(wheel_joint_states_component
  rclcpp rclcpp_components sensor_msgs std_msgs)
rclcpp_components_register_node(wheel_joint_states_component
  PLUGIN "app_wheel_joint_states::WheelJointStates"
  EXECUTABLE wheel_joint_states_node)

install(TARGETS wheel_joint_states_component
  LIBRARY DESTINATION lib ARCHIVE DESTINATION lib RUNTIME DESTINATION bin)

ament_package()
