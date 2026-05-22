from launch import LaunchDescription
from launch_ros.actions import Node
import os

def generate_launch_description():
    config = '/workspace/config/cv7_ahrs.yml'

    return LaunchDescription([
        Node(
            package='microstrain_inertial_driver',
            executable='microstrain_inertial_driver_node',
            name='microstrain_inertial_driver',
            output='screen',
            parameters=[config],
        ),
    ])
