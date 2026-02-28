from launch import LaunchDescription
from launch_ros.actions import Node
import os

workspace_dir = '/workspace' 
config_file = os.path.join(workspace_dir, 'src', 'aruco_detector', 'config', 'params.yaml')

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='aruco_detector',
            executable='aruco_detector_node',
            name='aruco_detector',
            output='screen',
            parameters=[config_file]  
        )
    ])