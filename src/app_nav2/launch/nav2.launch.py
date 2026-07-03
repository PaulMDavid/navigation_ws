from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os

params_file = os.path.join('/workspace', 'src', 'app_nav2', 'config', 'params.yaml')


def generate_launch_description():
    nav2_bringup_dir = get_package_share_directory('nav2_bringup')

    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_dir, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'false',
            'params_file': params_file,
        }.items(),
    )

    return LaunchDescription([
        nav2_launch,
    ])
