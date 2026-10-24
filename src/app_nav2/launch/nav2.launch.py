from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os

params_file = os.path.join('/workspace', 'src', 'app_nav2', 'config', 'params.yaml')


def generate_launch_description():
    # nav2_bringup's navigation_launch.py with the smoother and behaviors remapped to
    # app_teleop's mux input (see navigation.launch.py)
    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('app_nav2'), 'launch', 'navigation.launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'false',
            'params_file': params_file,
        }.items(),
    )

    return LaunchDescription([
        nav2_launch,
    ])
