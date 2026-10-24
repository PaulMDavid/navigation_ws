"""Count messages per topic without deserializing them:  python3 rate.py 15 /a /b ..."""
import sys
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message

seconds, topics = float(sys.argv[1]), sys.argv[2:]
rclpy.init()
node = rclpy.create_node('rate_probe')
counts = dict.fromkeys(topics, 0)
deadline = time.monotonic() + 5
while time.monotonic() < deadline and not all(
        t in dict(node.get_topic_names_and_types()) for t in topics):
    rclpy.spin_once(node, timeout_sec=0.2)
types = dict(node.get_topic_names_and_types())
for t in topics:
    if t in types:
        node.create_subscription(get_message(types[t][0]), t,
                                 lambda _m, t=t: counts.__setitem__(t, counts[t] + 1),
                                 qos_profile_sensor_data, raw=True)
end = time.monotonic() + seconds
while time.monotonic() < end:
    rclpy.spin_once(node, timeout_sec=0.1)
for t in topics:
    print(f'{t}: {counts[t] / seconds:.1f} Hz' if t in types else f'{t}: not advertised')
