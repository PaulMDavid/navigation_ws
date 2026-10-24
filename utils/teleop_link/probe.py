#!/usr/bin/env python3
"""Drive teleop_mux through both links and check what reaches /cmd_vel.

  probe.py phone   Foxglove WebSocket client, as the phone app speaks it
  probe.py ground  ROS node on domain 78, reaching the robot (77) only via Zenoh;
                   run.sh kills the ground Zenoh bridge mid-drive
  probe.py camera  the camera page: subscribe /teleop/camera/compressed over the bridge
                   (OV9281 standing in for the ZED), check rate, size, and that the
                   relay stops when the page unsubscribes

Prints one PASS/FAIL line per check and writes results/<phase>.json.
"""
import asyncio
import json
import os
import struct
import sys
import threading
import time

import rclpy
import websockets
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String

ROBOT_DOMAIN, GROUND_DOMAIN = 77, 78
RESULTS = '/probe/results'
results = {'checks': []}


def check(name, ok, detail=''):
    results['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail})
    print(f'{"PASS" if ok else "FAIL"}  {name}  {detail}', flush=True)


class Watch(Node):
    """Robot-side observer: /cmd_vel samples and the latest /teleop/state."""

    def __init__(self, context):
        super().__init__('teleop_probe_watch', context=context)
        self.cmd = []    # (receive time, vx, wz)
        self.state = None
        self.create_subscription(Twist, '/cmd_vel', lambda m: self.cmd.append(
            (time.time(), m.linear.x, m.angular.z)), 10)
        self.create_subscription(String, '/teleop/state',
                                 lambda m: setattr(self, 'state', json.loads(m.data)), 10)
        self.nav_pub = self.create_publisher(Twist, '/cmd_vel_auto', 10)
        self.ground_mode = self.create_publisher(String, '/teleop/ground/set_mode', 10)
        self.params = self.create_client(SetParameters, '/teleop_mux/set_parameters')

    def latest(self, since):
        return [c for c in self.cmd if c[0] >= since]

    def set_source(self, source):
        self.params.wait_for_service(timeout_sec=5)
        req = SetParameters.Request(parameters=[Parameter(name='source', value=ParameterValue(
            type=ParameterType.PARAMETER_STRING, string_value=source))])
        fut = self.params.call_async(req)
        while not fut.done():
            time.sleep(0.05)
        return fut.result().results[0].successful


def spin_in_thread(node, context):
    ex = SingleThreadedExecutor(context=context)
    ex.add_node(node)
    threading.Thread(target=ex.spin, daemon=True).start()


def wait_for(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def stop_latency(watch, cut_at):
    """Seconds from cut_at until /cmd_vel first reads zero, or None."""
    if not wait_for(lambda: any(c[1] == 0.0 and c[2] == 0.0 for c in watch.latest(cut_at)), 3):
        return None
    return next(c[0] for c in watch.latest(cut_at) if c[1] == 0.0 and c[2] == 0.0) - cut_at


def rate(watch, seconds=2.0):
    t0 = time.time()
    time.sleep(seconds)
    return len(watch.latest(t0)) / seconds


# ── phone path ──────────────────────────────────────────────────────────────
class FoxgloveClient:
    def __init__(self, ws):
        self.ws, self.channels, self.state = ws, {}, None

    @classmethod
    async def connect(cls, url='ws://127.0.0.1:8765'):
        self = cls(await websockets.connect(url, subprotocols=['foxglove.sdk.v1']))
        asyncio.get_event_loop().create_task(self.reader())
        await self.ws.send(json.dumps({'op': 'advertise', 'channels': [
            {'id': 1, 'topic': '/teleop/phone/cmd_vel', 'encoding': 'json',
             'schemaName': 'geometry_msgs/msg/Twist'},
            {'id': 2, 'topic': '/teleop/phone/set_mode', 'encoding': 'json',
             'schemaName': 'std_msgs/msg/String'},
            {'id': 3, 'topic': '/cmd_vel', 'encoding': 'json',
             'schemaName': 'geometry_msgs/msg/Twist'},
        ]}))
        return self

    async def reader(self):
        try:
            await self._read()
        except websockets.ConnectionClosed:
            pass

    async def _read(self):
        async for m in self.ws:
            if isinstance(m, str):
                msg = json.loads(m)
                if msg['op'] == 'advertise':
                    for c in msg['channels']:
                        self.channels[c['topic']] = c['id']
                    if '/teleop/state' in self.channels:
                        await self.ws.send(json.dumps({'op': 'subscribe', 'subscriptions': [
                            {'id': 7, 'channelId': self.channels['/teleop/state']}]}))
            elif m[0] == 1 and struct.unpack_from('<I', m, 1)[0] == 7:
                n = struct.unpack_from('<I', m, 17)[0]
                self.state = json.loads(m[21:21 + n - 1])

    async def publish(self, channel, obj):
        await self.ws.send(struct.pack('<BI', 1, channel) + json.dumps(obj).encode())

    async def twist(self, vx, wz, channel=1):
        await self.publish(channel, {'linear': {'x': vx, 'y': 0, 'z': 0},
                                     'angular': {'x': 0, 'y': 0, 'z': wz}})

    async def mode(self, mode):
        await self.publish(2, {'data': mode})


async def drive(fox, vx, wz, seconds):
    end = time.time() + seconds
    while time.time() < end:
        await fox.twist(vx, wz)
        await asyncio.sleep(0.1)


async def phone_phase(watch):
    check('mux set to phone source', watch.set_source('phone'))
    hz = rate(watch)
    check('/cmd_vel published at ~20 Hz with no input', 17 <= hz <= 23, f'{hz:.1f} Hz')

    fox = await FoxgloveClient.connect()
    ok = await asyncio.to_thread(wait_for, lambda: fox.state is not None, 5)
    check('phone receives /teleop/state over the bridge', ok,
          f'source={fox.state and fox.state["source"]}')

    await fox.mode('manual')
    ok = await asyncio.to_thread(wait_for, lambda: watch.state['mode'] == 'manual', 2)
    check('phone sets manual', ok)

    t0 = time.time()
    await drive(fox, 2.0, 0.3, 2.0)
    samples = watch.latest(t0 + 0.5)
    vx = max(c[1] for c in samples)
    wz = samples[-1][2]
    check('joystick reaches /cmd_vel, clamped to max_linear', abs(vx - 0.5) < 1e-6 and abs(wz - 0.3) < 1e-6,
          f'sent vx=2.0 wz=0.3, got vx={vx} wz={wz}')

    latency = []
    for _ in range(5):  # silent drop: the socket stays open, commands just stop
        await drive(fox, 0.4, 0.0, 1.0)
        cut = time.time()
        latency.append(await asyncio.to_thread(stop_latency, watch, cut))
    ok = all(l is not None and l <= 0.6 for l in latency)
    check('deadman: commands stop -> /cmd_vel zero within 0.6 s', ok,
          'latencies ' + ', '.join('none' if l is None else f'{l:.3f}' for l in latency))
    results['phone_stop_latency_s'] = latency

    # a client publishing /cmd_vel directly: foxglove_bridge 3.6.0 creates the publisher
    # (whitelist ignored), but in the phone domain, where nothing reads it
    t0 = time.time()
    for _ in range(10):
        await fox.twist(0.9, 0.0, channel=3)
        await asyncio.sleep(0.05)
    leaked = [c for c in watch.latest(t0) if c[1] == 0.9]
    check('a client publishing /cmd_vel does not reach the robot', not leaked, f'{len(leaked)} leaked')

    watch.nav_pub.publish(Twist())
    t0 = time.time()
    while time.time() - t0 < 1.0:
        watch.nav_pub.publish(Twist(linear=type(Twist().linear)(x=0.2)))
        await fox.twist(0.1, 0.0)
        await asyncio.sleep(0.05)
    check('manual ignores Nav2', all(c[1] != 0.2 for c in watch.latest(t0 + 0.2)))

    await fox.mode('autonomous')
    await asyncio.to_thread(wait_for, lambda: watch.state['mode'] == 'autonomous', 2)
    t0 = time.time()
    while time.time() - t0 < 1.0:
        watch.nav_pub.publish(Twist(linear=type(Twist().linear)(x=0.2)))
        await fox.twist(0.1, 0.0)
        await asyncio.sleep(0.05)
    tail = watch.latest(t0 + 0.3)
    check('autonomous passes Nav2, ignores the phone', tail and all(c[1] == 0.2 for c in tail))

    watch.ground_mode.publish(String(data='manual'))
    await asyncio.sleep(0.3)
    check('inactive source (ground) cannot take manual', watch.state['mode'] == 'autonomous')
    watch.ground_mode.publish(String(data='stop'))
    ok = await asyncio.to_thread(wait_for, lambda: watch.state['mode'] == 'stop', 1)
    check('inactive source (ground) can always stop', ok)
    t0 = time.time()
    while time.time() - t0 < 1.0:
        watch.nav_pub.publish(Twist(linear=type(Twist().linear)(x=0.2)))
        await asyncio.sleep(0.05)
    check('stop holds zero against Nav2', all(c[1] == 0.0 for c in watch.latest(t0 + 0.1)))
    await fox.ws.close()


# ── camera page ─────────────────────────────────────────────────────────────
def compressed_image(payload):
    """(format, jpeg bytes) from a CDR sensor_msgs/CompressedImage."""
    body = payload[4:]  # encapsulation header; alignment is relative to what follows
    off = 8  # header.stamp
    def string(off):
        n = struct.unpack_from('<I', body, off)[0]
        return body[off + 4:off + 4 + n - 1].decode(), off + 4 + n
    _, off = string(off)              # header.frame_id
    off = (off + 3) & ~3
    fmt, off = string(off)
    off = (off + 3) & ~3
    n = struct.unpack_from('<I', body, off)[0]
    return fmt, body[off + 4:off + 4 + n]


def jpeg_size(data):
    i = 2
    while i + 9 < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], 'big')
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], 'big'), int.from_bytes(data[i + 5:i + 7], 'big')
        i += 2 + length
    return None


async def camera_phase():
    ws = await websockets.connect('ws://127.0.0.1:8765', subprotocols=['foxglove.sdk.v1'],
                                  max_size=None)
    channels, frames = {}, []

    async def reader():
        async for m in ws:
            if isinstance(m, str):
                msg = json.loads(m)
                if msg['op'] == 'advertise':
                    channels.update({c['topic']: c['id'] for c in msg['channels']})
            elif m[0] == 1 and struct.unpack_from('<I', m, 1)[0] == 9:
                frames.append((time.time(), *compressed_image(m[13:])))
    task = asyncio.get_event_loop().create_task(reader())

    ok = await asyncio.to_thread(wait_for, lambda: '/teleop/camera/compressed' in channels, 5)
    check('camera topic advertised to the phone', ok)
    await asyncio.sleep(2)
    check('no frames before the page subscribes', not frames)

    await ws.send(json.dumps({'op': 'subscribe', 'subscriptions': [
        {'id': 9, 'channelId': channels['/teleop/camera/compressed']}]}))
    t0 = time.time()
    await asyncio.sleep(6)
    got = [f for f in frames if f[0] > t0 + 2]  # after the relay's 0.5 s demand check
    rate = len(got) / 4
    check('frames arrive at <= max_rate (10 Hz)', 7 <= rate <= 10.5, f'{rate:.1f} Hz')
    if got:
        fmt, data = got[-1][1], got[-1][2]
        size = jpeg_size(data)
        check('frames are JPEG <= 960 px wide', 'jpeg' in fmt and size and size[0] <= 960,
              f'format {fmt}, {size[0]}x{size[1]}, {len(data) / 1024:.0f} KiB' if size else fmt)
        results['camera'] = {'hz': rate, 'size': size, 'kib': len(data) / 1024}
        os.makedirs(RESULTS, exist_ok=True)
        open(f'{RESULTS}/camera_frame.jpg', 'wb').write(data)

    await ws.send(json.dumps({'op': 'unsubscribe', 'subscriptionIds': [9]}))
    await asyncio.sleep(2)
    n = len(frames)
    await asyncio.sleep(2)
    check('relay stops when the page unsubscribes', len(frames) == n, f'{len(frames) - n} after')
    task.cancel()
    await ws.close()


# ── ground path ─────────────────────────────────────────────────────────────
def ground_phase(watch, ground):
    check('mux set to ground source', watch.set_source('ground'))
    check('source change puts the robot in stop',
          wait_for(lambda: watch.state['mode'] == 'stop' and watch.state['source'] == 'ground', 2))

    check('/teleop/state crosses Zenoh to the ground domain', wait_for(lambda: ground.state, 15),
          f'mode={ground.state and ground.state["mode"]}')

    ground.mode.publish(String(data='manual'))
    check('ground sets manual over Zenoh', wait_for(lambda: watch.state['mode'] == 'manual', 3))

    ground.vx = 0.3
    t0 = time.time()
    time.sleep(2.0)
    vx = [c[1] for c in watch.latest(t0 + 0.5)]
    check('ground joystick reaches /cmd_vel over Zenoh', vx and min(vx) == 0.3,
          f'{len(vx)} samples, min {min(vx) if vx else None}')

    # run.sh kills the ground bridge container and writes the time
    open(f'{RESULTS}/ground_ready', 'w').close()
    marker = f'{RESULTS}/ground_killed'
    if not wait_for(lambda: os.path.exists(marker), 30):
        check('ground bridge killed by run.sh', False)
        return
    cut = float(open(marker).read())
    lat = stop_latency(watch, cut)
    check('Zenoh link killed mid-drive -> /cmd_vel zero within 0.6 s', lat is not None and lat <= 0.6,
          'none' if lat is None else f'{lat:.3f} s')
    results['ground_stop_latency_s'] = lat
    ground.vx = None


class Ground(Node):
    """The ground-station PC: publishes teleop at 10 Hz on its own domain."""

    def __init__(self, context):
        super().__init__('teleop_probe_ground', context=context)
        self.vx, self.state = None, None
        self.cmd = self.create_publisher(Twist, '/teleop/ground/cmd_vel', qos_profile_sensor_data)
        self.mode = self.create_publisher(String, '/teleop/ground/set_mode', 10)
        self.create_subscription(String, '/teleop/state',
                                 lambda m: setattr(self, 'state', json.loads(m.data)), 10)
        self.create_timer(0.1, lambda: self.vx is not None and self.cmd.publish(
            Twist(linear=type(Twist().linear)(x=self.vx))))


def main():
    phase = sys.argv[1]
    robot_ctx = rclpy.Context()
    rclpy.init(context=robot_ctx, domain_id=ROBOT_DOMAIN)
    watch = Watch(robot_ctx)
    spin_in_thread(watch, robot_ctx)
    check('teleop_mux is running', wait_for(lambda: watch.state, 10))
    if phase == 'phone':
        asyncio.run(phone_phase(watch))
    elif phase == 'camera':
        asyncio.run(camera_phase())
    else:
        ground_ctx = rclpy.Context()
        rclpy.init(context=ground_ctx, domain_id=GROUND_DOMAIN)
        ground = Ground(ground_ctx)
        spin_in_thread(ground, ground_ctx)
        ground_phase(watch, ground)
    os.makedirs(RESULTS, exist_ok=True)
    with open(f'{RESULTS}/{phase}.json', 'w') as f:
        json.dump(results, f, indent=1)
    sys.exit(0 if all(c['ok'] for c in results['checks']) else 1)


if __name__ == '__main__':
    main()
