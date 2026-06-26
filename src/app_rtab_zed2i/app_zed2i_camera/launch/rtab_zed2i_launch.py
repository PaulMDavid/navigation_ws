from launch import LaunchDescription
from launch_ros.actions import Node, ComposableNodeContainer
from launch_ros.descriptions import ComposableNode
import os

workspace_dir = '/workspace'
zed_config_file   = os.path.join(workspace_dir, 'src', 'zed2i_camera', 'config', 'params.yaml')
rtab_config_file  = os.path.join(workspace_dir, 'config', 'params.yaml')

# Try composable container for both nodes.   

def generate_launch_description():
    
    container = ComposableNodeContainer(
        name='rtab_zed2i_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        output='screen',
        composable_node_descriptions=[

            ComposableNode(
                package='zed_components',
                plugin='stereolabs::ZedCamera',
                name='zed_node',
                parameters=[
                    zed_config_file,
                    {   #
                        'camera_model': 'zed2i',
                        'camera_name': 'zed2i',
                        'publish_urdf': False,
                        'publish_tf': False,
                        'publish_map_tf': False,
                        'base_frame': 'chassis_link',
                    }
                ],
                extra_arguments=[{'use_intra_process_comms': True}],
            ),

            ComposableNode(
                package='rtabmap_slam',
                plugin='rtabmap_slam::CoreWrapper',
                name='rtabmap',
                parameters=[rtab_config_file],
                remappings=[
                    ('scan_cloud', '/ouster/points'),
                    ('imu',        '/ouster/imu'),
                ],
                extra_arguments=[{'use_intra_process_comms': True}],
            ),

        ],
        
    )

    return LaunchDescription([container])