import json, rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from std_msgs.msg import String
rclpy.init(); n = rclpy.create_node('peek'); got = []
n.create_subscription(String, '/bringup/status', lambda m: got.append(m.data),
    QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
while not got: rclpy.spin_once(n, timeout_sec=1)
d = json.loads(got[0]); print('overall:', d['overall'])
for s in d['stages']:
    print(f"- {s['title']:22} {s['state']:9} {s['message'][:120]}")
    for c in s['checks']: print(f"     {'ok ' if c['ok'] else 'BAD'} {c['label']}: {c['value']}")
    for c in s['containers']: print(f"     [{c['name']}] {c['status']} exit={c['exit_code']}")
    for k, v in s['logs'].items(): print(f"     logs {k}: {len(v)} lines, last: {v[-1][:100] if v else ''}")
print(); [print(' ', e['level'], e['text']) for e in d['events']]
