"""ROS-level test of nav_relay.py with the real teleop_mux and fake SLAM / Nav2 / bringup
manager, on loopback DDS. Domains: 81 = robot (main), 83 = phone (not 0/51, which a
stand-in stack on the laptop may be using). Runs inside the container from run.sh.

Fakes (main domain, own thread): a latched /rtabmap/map (2500x1800 cells at 0.05 m),
TF map -> chassis_link, /plan with 1000 poses, a NavigateToPose action server on
/navigate_to_pose (succeeds after ~2 s; aborts goals with x < 0; honours cancel), and
/bringup/go, /bringup/stop, latched /bringup/status."""
import array
import json
import math
import os
import subprocess
import sys
import threading
import time

import cv2
import numpy as np
import pytest
import rclpy
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Path
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster

APP = os.environ.get('APP_DIR', '/workspace/app_teleop')
sys.path.insert(0, APP)
import nav_relay_core as core  # noqa: E402

MAIN, PHONE = int(os.environ.get('ROS_DOMAIN_ID', '81')), int(os.environ.get('TELEOP_PHONE_DOMAIN', '83'))
LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
POSE = (1.5, -2.0, 0.7)
MAP_W, MAP_H, MAP_RES, MAP_ORIGIN = 2500, 1800, 0.05, (-60.0, -40.0)


def make_grid(variant=0):
    g = np.full((MAP_H, MAP_W), -1, np.int8)
    g[200:1600, 300:2200] = 0
    g[800:803, 300:2200] = 100                     # a wall
    g[1000 + variant * 30:1010 + variant * 30, 1000:1100] = 100   # moves per variant
    return g


class Fakes(Node):
    def __init__(self, ctx):
        super().__init__('fakes', context=ctx)
        grp = ReentrantCallbackGroup()
        self.goals, self.bringup_calls = [], []
        self.map_pub = self.create_publisher(OccupancyGrid, '/rtabmap/map', LATCHED)
        self.plan_pub = self.create_publisher(Path, '/plan', 1)
        self.status_pub = self.create_publisher(String, '/bringup/status', LATCHED)
        self.tfb = TransformBroadcaster(self)
        self.create_timer(0.05, self.pub_tf)
        self.create_timer(0.5, self.pub_plan)
        for name in ('go', 'stop'):
            self.create_service(Trigger, f'/bringup/{name}', lambda q, r, n=name: self.on_trigger(n, r),
                                callback_group=grp)
        ActionServer(self, NavigateToPose, '/navigate_to_pose', self.execute,
                     goal_callback=lambda g: GoalResponse.ACCEPT,
                     cancel_callback=lambda h: CancelResponse.ACCEPT, callback_group=grp)
        self.publish_map(0)
        self.status_pub.publish(String(data=json.dumps({
            'stamp': time.time(), 'overall': 'failed', 'project': 'navbringup',
            'events': [{'t': 1, 'level': 'info', 'text': 'x'}],
            'stages': [{'name': 'slam', 'title': 'SLAM (rtabmap)', 'state': 'failed', 'required': True,
                        'message': 'TF map → chassis_link: missing', 'services': ['app_rtab_map'],
                        'timeout': 90, 'started_at': 1.0, 'ready_at': None,
                        'checks': [{'label': 'TF map → chassis_link', 'ok': False, 'value': 'missing',
                                    'hint': 'odometry lost?'}],
                        'containers': [{'name': 'app_rtab_map_container', 'status': 'running'}],
                        'logs': {'app_rtab_map_container': ['log line'] * 200}}]})))

    def publish_map(self, variant):
        m = OccupancyGrid()
        m.header.frame_id = 'map'
        m.header.stamp = self.get_clock().now().to_msg()
        m.info.resolution, m.info.width, m.info.height = MAP_RES, MAP_W, MAP_H
        m.info.origin.position.x, m.info.origin.position.y = MAP_ORIGIN
        m.info.origin.orientation.w = 1.0
        m.data = array.array('b', make_grid(variant).tobytes())
        self.map_pub.publish(m)

    def pub_tf(self):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = 'map', 'chassis_link'
        t.transform.translation.x, t.transform.translation.y = POSE[:2]
        _, _, t.transform.rotation.z, t.transform.rotation.w = core.yaw_to_quat(POSE[2])
        self.tfb.sendTransform(t)

    def pub_plan(self):
        p = Path()
        p.header.frame_id = 'map'
        for i in range(1000):
            ps = PoseStamped()
            ps.pose.position.x, ps.pose.position.y = POSE[0] + i * 0.01, POSE[1] + i * 0.005
            p.poses.append(ps)
        self.plan_pub.publish(p)

    def on_trigger(self, name, res):
        self.bringup_calls.append(name)
        res.success, res.message = True, f'{name} queued'
        return res

    def execute(self, handle):
        pose = handle.request.pose
        self.goals.append(pose)
        fb = NavigateToPose.Feedback()
        for i in range(20):
            if handle.is_cancel_requested:
                handle.canceled()
                return NavigateToPose.Result()
            if pose.pose.position.x < 0 and i == 5:
                handle.abort()
                return NavigateToPose.Result()
            fb.distance_remaining = 10.0 - i * 0.5
            fb.estimated_time_remaining.sec = 20 - i
            fb.navigation_time.sec = i // 10
            fb.number_of_recoveries = 1
            handle.publish_feedback(fb)
            time.sleep(0.1)
        handle.succeed()
        return NavigateToPose.Result()


class Probe:
    def __init__(self, domain, name):
        self.ctx = rclpy.Context()
        rclpy.init(context=self.ctx, domain_id=domain)
        self.node = Node(name, context=self.ctx)
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(self.node)
        self.state, self.states, self.mux_state = None, [], None
        self.maps, self.metas = [], []
        self.node.create_subscription(String, '/teleop/nav/state', self.on_state, 10)
        self.node.create_subscription(String, '/teleop/state',
                                      lambda m: setattr(self, 'mux_state', json.loads(m.data)), 10)
        self.node.create_subscription(CompressedImage, '/teleop/nav/map', self.maps.append, LATCHED)
        self.node.create_subscription(String, '/teleop/nav/map_meta',
                                      lambda m: self.metas.append(json.loads(m.data)), LATCHED)
        self.cmd = self.node.create_publisher(String, '/teleop/phone/nav_cmd', 10)

    def on_state(self, m):
        self.state = json.loads(m.data)
        self.states.append((time.monotonic(), self.state))

    def spin(self, secs):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            self.ex.spin_once(timeout_sec=0.02)


@pytest.fixture(scope='module')
def stack():
    env = dict(os.environ, TELEOP_SOURCE='phone')
    params = ['--ros-args', '--params-file', f'{APP}/config/teleop.yaml']
    procs = [subprocess.Popen(['python3', f'{APP}/{n}.py', *params], env=env)
             for n in ('teleop_mux', 'nav_relay')]
    fctx = rclpy.Context()
    rclpy.init(context=fctx, domain_id=MAIN)
    fakes = Fakes(fctx)
    fex = MultiThreadedExecutor(num_threads=4, context=fctx)
    fex.add_node(fakes)
    threading.Thread(target=fex.spin, daemon=True).start()
    main, phone = Probe(MAIN, 'probe_main'), Probe(PHONE, 'probe_phone')
    end = time.monotonic() + 30
    while time.monotonic() < end and not (main.state and phone.state and phone.metas and phone.maps
                                          and phone.state['nav2_ready'] and phone.state['pose']):
        both(main, phone, 0.1)
    assert main.state and phone.state and phone.metas and phone.maps, 'stack did not come up'
    yield main, phone, fakes
    for p in procs:
        p.terminate()
        p.wait(5)
    fex.shutdown(timeout_sec=2)
    for ctx in (fctx, main.ctx, phone.ctx):
        ctx.try_shutdown()


def both(main, phone, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        main.spin(0.02)
        phone.spin(0.02)


def send(main, phone, cmd, secs=1.0):
    for _ in range(20):
        if phone.cmd.get_subscription_count():
            break
        both(main, phone, 0.1)
    phone.cmd.publish(String(data=cmd if isinstance(cmd, str) else json.dumps(cmd)))
    both(main, phone, secs)


def wait_for(main, phone, pred, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        both(main, phone, 0.05)
        if phone.state and pred(phone.state):
            return True
    return False


def test_state_both_domains_and_rate(stack):
    main, phone, _ = stack
    for p in (main, phone):
        p.states.clear()
    both(main, phone, 3.0)
    for p in (main, phone):
        assert 4.0 <= len(p.states) / 3.0 <= 6.5
    s = phone.state
    assert set(s) == {'stamp', 'frame_id', 'pose', 'pose_error', 'nav2_ready', 'status', 'reason', 'goal',
                      'distance_remaining', 'eta', 'navigation_time', 'recoveries', 'plan', 'plan_age',
                      'bringup', 'bringup_reply', 'last_cmd', 'last_cmd_age', 'rejected'}
    assert s['frame_id'] == 'map' and s['status'] == 'idle' and s['goal'] is None and s['nav2_ready']


def test_pose_from_tf(stack):
    s = stack[1].state
    assert s['pose_error'] is None
    assert (s['pose']['x'], s['pose']['y'], s['pose']['yaw']) == pytest.approx(POSE, abs=1e-3)
    assert 0 <= s['pose']['age'] < 0.5


def test_plan_downsampled(stack):
    s = stack[1].state
    assert len(s['plan']) == 200 and s['plan_age'] < 1.5
    assert s['plan'][0] == pytest.approx([POSE[0], POSE[1]], abs=0.01)
    assert s['plan'][-1] == pytest.approx([POSE[0] + 9.99, POSE[1] + 4.995], abs=0.01)


def test_bringup_relayed_compact(stack):
    b = stack[1].state['bringup']
    assert b['overall'] == 'failed' and b['age'] >= 0
    st = b['stages'][0]
    assert set(st) == {'name', 'title', 'state', 'required', 'message', 'checks'}
    assert st['checks'][0]['ok'] is False and st['message'].startswith('TF map')


def test_map_meta_and_png(stack):
    main, phone, _ = stack
    meta, img = phone.metas[-1], phone.maps[-1]
    assert img.format == 'png' and img.header.frame_id == 'map'
    assert meta['stamp'] == pytest.approx(img.header.stamp.sec + img.header.stamp.nanosec * 1e-9)
    assert (meta['width'], meta['height'], meta['downsample']) == (834, 600, 3)
    assert meta['resolution'] == pytest.approx(0.15)
    assert (meta['origin']['x'], meta['origin']['y'], meta['origin']['yaw']) == pytest.approx((*MAP_ORIGIN, 0))
    assert (meta['source_width'], meta['source_height'], meta['source_resolution']) == (MAP_W, MAP_H, pytest.approx(MAP_RES))
    assert meta['values'] == {'free': 254, 'occupied': 0, 'unknown': 205} and meta['frame_id'] == 'map'
    assert meta['bytes'] == len(img.data) < 1_000_000
    back = cv2.imdecode(np.frombuffer(bytes(img.data), np.uint8), cv2.IMREAD_UNCHANGED)
    want, _ = core.downsample_grid(make_grid(0).ravel(), MAP_W, MAP_H, 1000)
    assert back.shape == (600, 834) and (back == want).all()
    # the wall at grid rows 800..802 (y = -40 + 800*0.05 = 0 m) is at image row 600-1-266
    assert (back[600 - 1 - 800 // 3, 100:700] == 0).all()
    assert main.metas and main.metas[-1]['seq'] == meta['seq']


def test_map_latched_for_late_joiner(stack):
    main, phone, _ = stack
    late = Probe(PHONE, 'probe_late')
    end = time.monotonic() + 10
    while time.monotonic() < end and not (late.maps and late.metas):
        late.spin(0.1)
        both(main, phone, 0.02)
    assert late.maps and late.metas and late.metas[-1]['seq'] == phone.metas[-1]['seq']
    assert len(late.maps) == 1


def test_unchanged_map_not_resent(stack):
    main, phone, fakes = stack
    n = len(phone.metas)
    for _ in range(10):                     # same map, 5 Hz, for 2 s
        fakes.publish_map(0)
        both(main, phone, 0.2)
    both(main, phone, 2.5)
    assert len(phone.metas) == n


def test_changed_map_rate_limited(stack):
    main, phone, fakes = stack
    phone.metas.clear()
    phone.maps.clear()
    t0 = time.monotonic()
    for v in range(1, 26):                  # a different map every 0.2 s for 5 s
        fakes.publish_map(v)
        both(main, phone, 0.2)
    both(main, phone, 2.5)                  # the last one goes out once the interval allows
    assert 2 <= len(phone.metas) <= 4       # <= 0.5 Hz over ~5 s
    assert len(phone.maps) == len(phone.metas)
    back = cv2.imdecode(np.frombuffer(bytes(phone.maps[-1].data), np.uint8), cv2.IMREAD_UNCHANGED)
    want, _ = core.downsample_grid(make_grid(25).ravel(), MAP_W, MAP_H, 1000)
    assert (back == want).all(), 'last map version must be the one left latched'
    seqs = [m['seq'] for m in phone.metas]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert time.monotonic() - t0 < 10


def test_goal_succeeds(stack):
    main, phone, fakes = stack
    n = len(fakes.goals)
    send(main, phone, {'cmd': 'goal', 'x': 3.0, 'y': 4.0, 'yaw': 1.0}, secs=0.6)
    assert len(fakes.goals) == n + 1
    g = fakes.goals[-1]
    assert g.header.frame_id == 'map'
    assert (g.pose.position.x, g.pose.position.y) == (3.0, 4.0)
    q = g.pose.orientation
    assert core.quat_to_yaw(q.x, q.y, q.z, q.w) == pytest.approx(1.0)
    s = phone.state
    assert s['status'] == 'navigating' and s['rejected'] is None and s['last_cmd'] == 'goal'
    assert (s['goal']['x'], s['goal']['y'], s['goal']['yaw']) == (3.0, 4.0, 1.0)
    assert 0 < s['distance_remaining'] <= 10 and s['eta'] > 0 and s['recoveries'] == 1
    assert wait_for(main, phone, lambda s: s['status'] == 'succeeded', 5)
    s = phone.state
    assert s['reason'] is None and s['distance_remaining'] is None and s['eta'] is None
    assert s['goal']['x'] == 3.0


def test_goal_cancel(stack):
    main, phone, _ = stack
    send(main, phone, {'cmd': 'goal', 'x': 2.0, 'y': 0.0, 'yaw': 0.0}, secs=0.5)
    assert phone.state['status'] == 'navigating'
    send(main, phone, {'cmd': 'cancel'}, secs=0.1)
    assert wait_for(main, phone, lambda s: s['status'] == 'canceled', 3)
    assert phone.state['rejected'] is None


def test_goal_aborted(stack):
    main, phone, _ = stack
    send(main, phone, {'cmd': 'goal', 'x': -1.0, 'y': 0.0, 'yaw': 0.0}, secs=0.1)
    assert wait_for(main, phone, lambda s: s['status'] == 'aborted', 3)
    assert phone.state['reason'] == 'Nav2 aborted the goal'


def test_cancel_without_goal_and_bad_json(stack):
    main, phone, _ = stack
    send(main, phone, {'cmd': 'cancel'}, secs=0.5)
    assert phone.state['rejected'] == 'cancel refused: no active goal'
    send(main, phone, 'not json', secs=0.5)
    assert phone.state['rejected'].startswith('nav_cmd refused: not JSON')
    send(main, phone, {'cmd': 'goal', 'x': 1}, secs=0.5)
    assert 'finite numbers' in phone.state['rejected']


def test_bringup_go_stop(stack):
    main, phone, fakes = stack
    fakes.bringup_calls.clear()
    send(main, phone, {'cmd': 'bringup_go'}, secs=0.8)
    assert fakes.bringup_calls == ['go']
    r = phone.state['bringup_reply']
    assert (r['cmd'], r['success'], r['message']) == ('bringup_go', True, 'go queued') and r['age'] < 1
    send(main, phone, {'cmd': 'bringup_stop'}, secs=0.8)
    assert fakes.bringup_calls == ['go', 'stop']
    assert phone.state['bringup_reply']['cmd'] == 'bringup_stop' and phone.state['rejected'] is None


def test_refused_unless_phone_is_source(stack):
    """Last: switches teleop_mux's source to ground."""
    main, phone, fakes = stack
    cli = main.node.create_client(SetParameters, '/teleop_mux/set_parameters')
    assert cli.wait_for_service(timeout_sec=5)
    fut = cli.call_async(SetParameters.Request(parameters=[Parameter(
        name='source', value=ParameterValue(type=ParameterType.PARAMETER_STRING, string_value='ground'))]))
    while not fut.done():
        main.spin(0.05)
    both(main, phone, 1.0)
    assert main.mux_state['source'] == 'ground'
    n, calls = len(fakes.goals), len(fakes.bringup_calls)
    for cmd in ({'cmd': 'goal', 'x': 1.0, 'y': 1.0, 'yaw': 0.0}, {'cmd': 'bringup_go'}, {'cmd': 'cancel'}):
        send(main, phone, cmd, secs=0.5)
        assert phone.state['rejected'] == f'{cmd["cmd"]} refused: active source is ground'
    assert len(fakes.goals) == n and len(fakes.bringup_calls) == calls
    assert math.isfinite(phone.state['stamp'])
