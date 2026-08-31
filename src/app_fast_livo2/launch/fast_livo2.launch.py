"""
ZED2i + Ouster + FAST-LIVO2, sharing one process where that's actually possible.

Composed into one ComposableNodeContainer (true zero-copy, intra-process — no
serialize/deserialize hop):
  - the Ouster driver (ouster_ros::OusterDriver, the same all-in-one component the
    upstream sensor.composite.launch.py uses)
  - the ZED2i driver (joined via zed_wrapper's own launch file, same pattern already
    used by app_rtab_zed2i/launch/rtab_zed2i.launch.py in this repo)

NOT composed (regular OS process, still same Docker container / same host, but a normal
DDS hop rather than intra-process zero-copy):
  - FAST-LIVO2's `fastlivo_mapping` executable. Its ROS2 port (see ../README.md for which
    fork and why) runs its own `while (rclcpp::ok()) { rclcpp::spin_some(...) }` loop
    inside LIVMapper::run() instead of handing control to an external executor, which is
    incompatible with being loaded as an rclcpp_components plugin into a shared container.
    Making it truly composable means patching that loop into a timer/executor-driven
    callback upstream — worth doing once there's real hardware to validate the change
    against, not attempted blind here.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode

CONTAINER_NAME = "fast_livo2_container"
ZED_NAMESPACE = "zed2i"  # must match zed_camera.launch.py's camera_name default


def generate_launch_description():
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
    )

    livo_params_file = LaunchConfiguration("livo_params_file")
    livo_params_arg = DeclareLaunchArgument(
        "livo_params_file",
        default_value=os.path.join(config_dir, "zed2i_ouster.yaml"),
        description="FAST-LIVO2 mapping params (topics, extrinsics, lidar_type).",
    )

    camera_params_file = LaunchConfiguration("camera_params_file")
    camera_params_arg = DeclareLaunchArgument(
        "camera_params_file",
        default_value=os.path.join(config_dir, "camera_zed2i.yaml"),
        description="ZED2i pinhole intrinsics, published via parameter_blackboard for vikit_ros.",
    )

    ouster_params_file = LaunchConfiguration("ouster_params_file")
    ouster_params_arg = DeclareLaunchArgument(
        "ouster_params_file",
        default_value=os.path.join(config_dir, "os_driver_params.yaml"),
        description="ouster_ros driver params (sensor_hostname, lidar_mode, ...).",
    )

    # --- The shared composable container ---------------------------------------------
    os_driver = ComposableNode(
        package="ouster_ros",
        plugin="ouster_ros::OusterDriver",
        name="os_driver",
        namespace="ouster",
        parameters=[ouster_params_file],
        extra_arguments=[{"use_intra_process_comms": True}],
    )

    container = ComposableNodeContainer(
        name=CONTAINER_NAME,
        namespace=ZED_NAMESPACE,
        package="rclcpp_components",
        executable="component_container_mt",
        composable_node_descriptions=[os_driver],
        output="screen",
    )

    # Join the ZED driver into the same container by name (same trick as
    # app_rtab_zed2i/launch/rtab_zed2i.launch.py).
    zed_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("zed_wrapper"),
                "launch",
                "zed_camera.launch.py",
            )
        ),
        launch_arguments={
            "camera_model": "zed2i",
            "camera_name": ZED_NAMESPACE,
            "container_name": CONTAINER_NAME,
            "publish_urdf": "false",
            "publish_tf": "false",
            "publish_map_tf": "false",
            "base_frame": "chassis_link",
            "enable_ipc": "true",
        }.items(),
    )

    # --- Everything else: regular nodes, same container image, separate processes -----
    camera_param_blackboard = Node(
        package="demo_nodes_cpp",
        executable="parameter_blackboard",
        name="parameter_blackboard",
        parameters=[camera_params_file],
        output="screen",
    )

    fast_livo_node = Node(
        package="fast_livo",
        executable="fastlivo_mapping",
        name="laserMapping",
        parameters=[livo_params_file],
        output="screen",
    )

    return LaunchDescription(
        [
            livo_params_arg,
            camera_params_arg,
            ouster_params_arg,
            container,
            zed_launch,
            camera_param_blackboard,
            fast_livo_node,
        ]
    )
