from launch import LaunchDescription
from launch_ros.actions import Node
import os

workspace_dir = '/workspace' 
config_file = os.path.join(workspace_dir, 'src', 'zed2i_camera', 'config', 'params.yaml')

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='zed2i_camera',
            executable='zed2i_camera_node',
            name='zed2i_camera',
            output='screen',
            parameters=[config_file]  
        )
    ])