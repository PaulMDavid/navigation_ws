"""Topic rates and latency for perf_compare, without deserializing anything.

    python3 record.py SECONDS TOPIC...   -> JSON on stdout

Latency is receive time minus header.stamp, read straight from the serialized
message: every message that starts with a std_msgs/Header has stamp.sec/nanosec
right after the 4-byte CDR encapsulation header. Topics without a header just get
a rate.
"""
import json
import struct
import sys
import time

import rclpy
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message

seconds, topics = float(sys.argv[1]), sys.argv[2:]
rclpy.init()
node = rclpy.create_node('perf_probe')
deadline = time.monotonic() + 10
while time.monotonic() < deadline and not all(
        t in dict(node.get_topic_names_and_types()) for t in topics):
    rclpy.spin_once(node, timeout_sec=0.2)
types = dict(node.get_topic_names_and_types())
stats = {t: {'n': 0, 'lat': []} for t in topics}


def on_msg(raw, topic, has_header):
    s = stats[topic]
    s['n'] += 1
    if has_header:
        sec, nsec = struct.unpack_from('<iI', raw, 4)
        s['lat'].append(time.time() - (sec + nsec * 1e-9))


for t in topics:
    if t not in types:
        continue
    cls = get_message(types[t][0])
    has_header = 'header' in cls.get_fields_and_field_types()
    # latched topics (map) need transient local to be seen at all; everything else
    # best effort so the probe never slows a reliable publisher down
    pubs = node.get_publishers_info_by_topic(t)
    latched = any(p.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL for p in pubs)
    qos = (QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                      reliability=ReliabilityPolicy.RELIABLE) if latched else qos_profile_sensor_data)
    # a latched topic replays its last message on subscribe, so its stamp says nothing
    node.create_subscription(cls, t, lambda m, t=t, h=has_header and not latched: on_msg(m, t, h),
                             qos, raw=True)

end = time.monotonic() + seconds
while time.monotonic() < end:
    rclpy.spin_once(node, timeout_sec=0.1)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] * 1000 if xs else None


print(json.dumps({t: {'advertised': t in types, 'hz': s['n'] / seconds,
                      'lat_p50_ms': pct(s['lat'], 50), 'lat_p95_ms': pct(s['lat'], 95)}
                  for t, s in stats.items()}))
