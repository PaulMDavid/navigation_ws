from launch import LaunchDescription
from launch_ros.actions import Node
import os

workspace_dir = '/workspace' 
config_file = os.path.join(workspace_dir, 'src', 'app_template', 'config', 'params.yaml')

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='app_template',
            executable='template_node',
            name='template',
            output='screen',
            parameters=[config_file]  
        )
    ])