from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os

workspace_dir = '/workspace' 
config_file = os.path.join(workspace_dir, 'src', 'app_robot_localization', 'config', 'params.yaml')

def generate_launch_description():
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(
                    get_package_share_directory('app_robot_localization'),
                    'robot_localization_erc26',
                    'launch',
                    'ekf.launch.py'
                )
            )
        )
    ])
