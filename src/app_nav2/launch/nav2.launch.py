from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

params_file = os.path.join(
    '/workspace',
    'src',
    'app_nav2',
    'config',
    'params.yaml'
)

map_yaml_file = os.path.join(
    '/workspace',
    'install',
    'app_nav2',
    'share',
    'app_nav2',
    'resource',
    'marsyard_costmap.yaml'
)

rviz_config = os.path.join(
    get_package_share_directory('nav2_bringup'),
    'rviz',
    'nav2_default_view.rviz'
)

def generate_launch_description():
    nav2_bringup_dir = get_package_share_directory('nav2_bringup')

    map_server = Node(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'yaml_filename': map_yaml_file,
        }]
    )

    map_server_lifecycle = Node(
        package='nav2_lifecycle_manager',
        executable='lifecycle_manager',
        name='lifecycle_manager_map',
        output='screen',
        parameters=[{
            'use_sim_time': True,
            'autostart': True,
            'node_names': ['map_server'],
        }]
    )

    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_dir, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'false',
            'params_file': params_file,
        }.items(),
        remappings=[
            ('/map', '/rtabmap/map'),
            ('/odom', '/rtabmap/odom'),
        ]
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', rviz_config],
        parameters=[{'use_sim_time': True}],
    )

    return LaunchDescription([
        map_server,
        map_server_lifecycle,
        nav2_launch,
        rviz,
    ])
