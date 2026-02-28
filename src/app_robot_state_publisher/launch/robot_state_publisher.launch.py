from launch import LaunchDescription
from launch_ros.actions import Node
import os

workspace_dir = '/workspace' 
config_file = os.path.join(workspace_dir, 'src', 'app_robot_state_publisher', 'config', 'params.yaml')

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='app_robot_state_publisher',
            executable='robot_state_publisher_node',
            name='robot_state_publisher',
            output='screen',
            parameters=[config_file]  
        )
    ])