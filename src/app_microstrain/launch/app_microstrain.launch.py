"""
app_microstrain: MicroStrain driver, and for the GQ7 an NTRIP client for SAPOS RTK.

The driver is started the way its upstream microstrain_launch.py does it: its own
params.yml first (the node's built-in defaults differ), then our device file on top.

SAPOS credentials are not in the repo. Compose loads them from /etc/navws/sapos.env on
each robot (one account per robot: an account allows one connection at a time).
Without SAPOS_USER the driver still runs, just without corrections.
"""

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

DRIVER_DEFAULTS = os.path.join(
    get_package_share_directory('microstrain_inertial_driver'),
    'microstrain_inertial_driver_common', 'config', 'params.yml')


def launch_nodes(context):
    config = LaunchConfiguration('config').perform(context)
    nodes = [
        Node(
            package='microstrain_inertial_driver',
            executable='microstrain_inertial_driver_node',
            name='microstrain_inertial_driver',
            output='screen',
            parameters=[yaml.safe_load(open(DRIVER_DEFAULTS)), config],
        ),
    ]

    if LaunchConfiguration('ntrip').perform(context).lower() != 'true':
        return nodes
    user = os.environ.get('SAPOS_USER', '')
    if not user:
        nodes.append(LogInfo(msg='SAPOS_USER not set (/etc/navws/sapos.env): '
                                 'running without RTK corrections'))
        return nodes

    nodes.append(Node(
        package='ntrip_client',
        executable='ntrip_ros.py',
        name='ntrip_client',
        output='screen',
        parameters=[{
            'host': os.environ.get('SAPOS_HOST', 'www.sapos-be-ntrip.de'),
            'port': int(os.environ.get('SAPOS_PORT', '2101')),
            # VRS_3_4G_BE: GPS+GLO+GAL+BDS, RTCM 3.2 MSM4. VRS_3_2G_BE (GPS+GLO,
            # RTCM 3.1) is the fallback if the GQ7 won't fix on MSM.
            'mountpoint': os.environ.get('SAPOS_MOUNTPOINT', 'VRS_3_4G_BE'),
            'ntrip_version': 'None',
            'authenticate': True,
            'username': user,
            'password': os.environ.get('SAPOS_PASSWORD', ''),
            'ssl': False,
            'cert': 'None',
            'key': 'None',
            'ca_cert': 'None',
            'rtcm_frame_id': 'odom',
            'rtcm_message_package': 'rtcm_msgs',
            'nmea_max_length': 128,
            'nmea_min_length': 3,
            'reconnect_attempt_max': 10,
            'reconnect_attempt_wait_seconds': 5,
            'rtcm_timeout_seconds': 4,
        }],
    ))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('config', default_value='/workspace/config/gq7.yml',
                              description='device file; cv7_ahrs.yml for the CV7'),
        DeclareLaunchArgument('ntrip', default_value='true',
                              description='start the SAPOS NTRIP client (GQ7 only)'),
        OpaqueFunction(function=launch_nodes),
    ])
