"""
app_gnss: single ZED-F9P receiver, Phase 1.

NOTE ON STRUCTURE: ublox_dgnss ships its nodes as *composable components*
(libublox_dgnss_components.so, libublox_nav_sat_fix_hp_components.so), not as
standalone executables. They therefore have to be loaded into a component
container; using a plain Node action fails with
"executable not found on the libexec directory". This mirrors upstream's own
ublox_rover_hpposllh_navsatfix.launch.py.

Phase 2 adds the ntrip_client node here once SAPOS credentials arrive.
Phase 3 replaces this with the moving-base + rover pair for heading.

Topics out:
  /ublox_dgnss/ubx_nav_hp_pos_llh   high-precision position
  /ublox_dgnss/ubx_nav_status       fix status
  /ublox_dgnss/ubx_nav_cov          covariance, consumed by the EKF later
  /fix                              sensor_msgs/NavSatFix
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, TextSubstitution
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode


def generate_launch_description():

    # Receiver parameters. Kept inline rather than in a YAML file because the
    # driver only accepts configuration keys it has explicitly declared; an
    # unknown key stops the node from starting. Start from the set upstream is
    # known to accept, and add more only after confirming each one works.
    #
    # CFG_RATE_MEAS is the measurement interval in milliseconds and
    # CFG_RATE_NAV the number of measurements per navigation solution,
    # so 1000 / 1 gives a 1 Hz position. Start slow: a stable 1 Hz fix is far
    # easier to debug than a fast one that drops out.
    params = [
        {'DEVICE_FAMILY': LaunchConfiguration('device_family')},
        {'DEVICE_SERIAL_STRING': LaunchConfiguration('device_serial_string')},
        {'FRAME_ID': LaunchConfiguration('frame_id')},
        {'CFG_USBOUTPROT_NMEA': False},      # we read UBX binary, NMEA is noise here
        {'CFG_RATE_MEAS': 1000},
        {'CFG_RATE_NAV': 1},
        {'CFG_MSGOUT_UBX_NAV_HPPOSLLH_USB': 1},
        {'CFG_MSGOUT_UBX_NAV_STATUS_USB': 1},
        {'CFG_MSGOUT_UBX_NAV_COV_USB': 1},
        {'CFG_MSGOUT_UBX_RXM_RTCM_USB': 1},  # reports incoming corrections, Phase 2
    ]

    # Physical offset of the GNSS antenna from the rover's chassis origin.
    # Placeholders: measure on the real rover before any outdoor run. An
    # unmeasured lever arm becomes a constant position bias that is easy to
    # mistake for a GNSS problem.
    antenna_x = LaunchConfiguration('antenna_x')
    antenna_y = LaunchConfiguration('antenna_y')
    antenna_z = LaunchConfiguration('antenna_z')

    return LaunchDescription([
        DeclareLaunchArgument('log_level', default_value=TextSubstitution(text='INFO')),
        DeclareLaunchArgument('device_family', default_value=TextSubstitution(text='F9P')),
        DeclareLaunchArgument(
            'device_serial_string', default_value='',
            description='USB serial string; leave empty with one receiver, '
                        'set it once the second F9P is connected'),
        DeclareLaunchArgument('frame_id', default_value='gnss_link'),
        DeclareLaunchArgument('antenna_x', default_value='0.0',
                              description='GNSS antenna X offset from chassis_link, metres'),
        DeclareLaunchArgument('antenna_y', default_value='0.0',
                              description='GNSS antenna Y offset from chassis_link, metres'),
        DeclareLaunchArgument('antenna_z', default_value='0.5',
                              description='GNSS antenna Z offset from chassis_link, metres'),
        DeclareLaunchArgument('foxglove', default_value='true',
                              description='Run the Foxglove bridge for live visualisation'),

        # The driver: claims the F9P over USB and publishes UBX messages.
        ComposableNodeContainer(
            name='ublox_dgnss_container',
            namespace='',
            package='rclcpp_components',
            executable='component_container_mt',
            output='screen',
            arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
            composable_node_descriptions=[
                ComposableNode(
                    package='ublox_dgnss_node',
                    plugin='ublox_dgnss::UbloxDGNSSNode',
                    name='ublox_dgnss',
                    parameters=params,
                )
            ],
        ),

        # Converts the high-precision UBX position into a standard NavSatFix,
        # which is what robot_localization's navsat_transform_node expects.
        ComposableNodeContainer(
            name='ublox_nav_sat_fix_hp_container',
            namespace='',
            package='rclcpp_components',
            executable='component_container_mt',
            output='screen',
            arguments=['--ros-args', '--log-level', LaunchConfiguration('log_level')],
            composable_node_descriptions=[
                ComposableNode(
                    package='ublox_nav_sat_fix_hp_node',
                    plugin='ublox_nav_sat_fix_hp::UbloxNavSatHpFixNode',
                    name='ublox_nav_sat_fix_hp',
                )
            ],
        ),

        # Foxglove bridge, for live visualisation from the laptop.
        # Connect Foxglove Studio to ws://localhost:8765 and add a Map panel
        # bound to /fix; it plots NavSatFix on a real map directly.
        # On the rover this is usually started separately, so it can be turned
        # off here with foxglove:=false.
        Node(
            package='foxglove_bridge',
            executable='foxglove_bridge',
            name='foxglove_bridge',
            output='screen',
            parameters=[{'port': 8765}],
            condition=IfCondition(LaunchConfiguration('foxglove')),
        ),

        # Static transform chassis_link -> gnss_link.
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='gnss_static_tf',
            output='screen',
            arguments=[antenna_x, antenna_y, antenna_z,
                       '0', '0', '0',
                       'chassis_link', 'gnss_link'],
        ),
    ])
