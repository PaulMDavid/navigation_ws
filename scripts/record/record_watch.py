#!/usr/bin/env python3
"""Runs next to `ros2 bag record` in the recorder container (record_drive.sh starts both),
so it has every message type the bag has (microstrain overlay, zed_msgs). Subscribes raw
(nothing deserialized, best-effort QoS) to each selected topic once it shows up in the
graph and writes, every second, atomically:

  {"t": <wall s>, "start": <wall s>, "mbps": <MB/s (1e6 B) of messages over the last
   --window s>, "watched": [...], "unloadable": [topics whose type this image can't load],
   "topics": {"/imu/data": {"last": <wall s of the last message>, "count": N}}}

`record status` (record_helper.py silent) turns it into the "no messages in the last 8 s"
list. If this process dies, the recording goes on; status then says the watch file is old.
"""
import argparse
import collections
import json
import os
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rosidl_runtime_py.utilities import get_message


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--topics-file', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--window', type=float, default=8.0)
    a = ap.parse_args()
    with open(a.topics_file) as f:
        topics = [t.strip() for t in f if t.strip()]

    rclpy.init()
    node = Node(f'record_watch_{os.getpid()}')
    ex = SingleThreadedExecutor()
    ex.add_node(node)
    start = time.time()
    stats = {}
    recent = collections.deque()        # (wall s, bytes)
    subs = {}
    unloadable = set()

    def cb_for(name):
        def cb(msg):
            now = time.time()
            s = stats.setdefault(name, {'last': 0.0, 'count': 0})
            s['last'], s['count'] = now, s['count'] + 1
            recent.append((now, len(msg)))
        return cb

    def subscribe_new():
        graph = dict(node.get_topic_names_and_types())
        for t in topics:
            if t in subs or not graph.get(t):
                continue
            try:
                cls = get_message(graph[t][0])
            except Exception:  # noqa: BLE001 - type not loadable: leave it unwatched
                unloadable.add(t)
                continue
            subs[t] = node.create_subscription(cls, t, cb_for(t), qos_profile_sensor_data, raw=True)

    next_graph = next_write = 0.0
    try:
        while rclpy.ok():
            ex.spin_once(timeout_sec=0.05)
            now = time.time()
            if now >= next_graph:
                subscribe_new()
                next_graph = now + 2.0
            if now >= next_write:
                while recent and recent[0][0] < now - a.window:
                    recent.popleft()
                span = min(a.window, max(now - start, 1e-3))
                doc = {'t': now, 'start': start, 'mbps': round(sum(b for _, b in recent) / span / 1e6, 3),
                       'watched': sorted(subs),
                       'unloadable': sorted(unloadable), 'topics': stats}
                tmp = a.out + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(doc, f)
                os.replace(tmp, a.out)
                next_write = now + 1.0
    except KeyboardInterrupt:
        pass
    finally:
        try:
            rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    main()
