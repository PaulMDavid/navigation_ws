#!/usr/bin/env python3
"""The phone app's Autonav page: Nav2 goals, the map and Nav2's state, relayed between
the main DDS domain and the phone domain (phone_domain.py).

  /teleop/phone/nav_cmd   std_msgs/String JSON, phone domain, phone -> orintwo
      {"cmd": "goal", "x": .., "y": .., "yaw": ..}   NavigateToPose action (map frame)
      {"cmd": "cancel"}                              cancel the relay's active goal
      {"cmd": "bringup_go"} / {"cmd": "bringup_stop"} /bringup/go, /bringup/stop
      Accepted only while teleop_mux's active source is `phone` (from /teleop/state).
  /teleop/nav/map         sensor_msgs/CompressedImage PNG, latched, both domains
  /teleop/nav/map_meta    std_msgs/String JSON, latched, both domains
  /teleop/nav/state       std_msgs/String JSON, `state_rate` Hz, both domains

Formats: README.md, "Autonav relay". The pure parts are in nav_relay_core.py.
"""
import collections
import json
import math
import threading
import time

import rclpy
import tf2_ros
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Path
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from std_srvs.srv import Trigger

import nav_relay_core as core
from phone_domain import phone_node

LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
RESULT_STATUS = {GoalStatus.STATUS_SUCCEEDED: 'succeeded', GoalStatus.STATUS_CANCELED: 'canceled',
                 GoalStatus.STATUS_ABORTED: 'aborted'}


def r3(v):
    return None if v is None else round(float(v), 3)


class NavRelay(Node):
    def __init__(self, phone):
        super().__init__('nav_relay')
        p = self.declare_parameter
        p('map_topic', '/rtabmap/map')        # what Nav2's global costmap static layer reads
        p('map_transient_local', True)        # subscribe latched (rtabmap and map_server publish so)
        p('map_frame', 'map')
        p('base_frame', 'chassis_link')
        p('map_max_size', 1000)               # cells per side after downsampling
        p('map_max_rate', 0.5)                # Hz, map re-sends at most this often
        p('occupied_thresh', 65)              # OccupancyGrid value >= this = occupied
        p('free_thresh', 25)                  # 0..this = free; between = unknown
        p('state_rate', 5.0)                  # Hz, /teleop/nav/state
        p('plan_topic', '/plan')              # planner_server's global plan
        p('plan_max_points', 200)
        p('plan_max_age', 3.0)                # s; older plans are not shown
        p('action_name', '/navigate_to_pose')
        p('bringup_go_service', '/bringup/go')
        p('bringup_stop_service', '/bringup/stop')
        p('bringup_status_topic', '/bringup/status')
        p('mux_state_timeout', 2.0)           # s; older /teleop/state = source unknown
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        self.g = g
        self.map_frame, self.base_frame = g('map_frame'), g('base_frame')

        self.lock = threading.Lock()          # nav_cmd arrives on the phone node's thread
        self.cmds = collections.deque(maxlen=16)
        self.active_source, self.mux_state_t = None, None
        self.last_cmd, self.last_cmd_t, self.rejected = None, None, None
        self.bringup, self.bringup_t, self.bringup_reply = None, None, None
        self.plan, self.plan_frame, self.plan_t = [], None, None
        self.map_msg, self.map_new, self.map_sent_t, self.map_key = None, False, None, None
        self.map_seq = 0
        # navigation of the goal this relay sent last
        self.gen = 0                          # bumps per goal; stale callbacks are ignored
        self.goal_handle, self.cancel_pending = None, False
        self.status, self.reason, self.goal, self.goal_t = 'idle', None, None, None
        self.feedback = None

        self.tf = tf2_ros.Buffer(cache_time=Duration(seconds=10))
        self.tf_listener = tf2_ros.TransformListener(self.tf, self)
        self.nav = ActionClient(self, NavigateToPose, g('action_name'))
        self.bringup_cli = {'bringup_go': self.create_client(Trigger, g('bringup_go_service')),
                            'bringup_stop': self.create_client(Trigger, g('bringup_stop_service'))}

        nodes = (self, phone)
        self.state_pubs = [n.create_publisher(String, '/teleop/nav/state', 10) for n in nodes]
        self.map_pubs = [n.create_publisher(CompressedImage, '/teleop/nav/map', LATCHED) for n in nodes]
        self.meta_pubs = [n.create_publisher(String, '/teleop/nav/map_meta', LATCHED) for n in nodes]
        map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL if g('map_transient_local')
                             else DurabilityPolicy.VOLATILE)
        self.create_subscription(OccupancyGrid, g('map_topic'), self.on_map, map_qos)
        self.create_subscription(Path, g('plan_topic'), self.on_plan, 10)
        self.create_subscription(String, g('bringup_status_topic'), self.on_bringup, LATCHED)
        self.create_subscription(String, '/teleop/state', self.on_mux_state, 10)
        phone.create_subscription(String, '/teleop/phone/nav_cmd', self.on_cmd, 10)

        self.create_timer(0.02, self.run_cmds)
        self.create_timer(0.1, self.maybe_send_map)
        self.create_timer(1.0 / g('state_rate'), self.publish_state)
        self.get_logger().info(
            f'map {g("map_topic")} -> /teleop/nav/map (<= {g("map_max_size")} px, <= {g("map_max_rate")} Hz), '
            f'pose TF {self.map_frame} -> {self.base_frame}, goals -> {g("action_name")}, '
            f'phone_domain={phone.context.get_domain_id()}')

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    # ---- inputs ------------------------------------------------------------

    def on_mux_state(self, msg):
        try:
            source = json.loads(msg.data).get('source')
        except (ValueError, AttributeError):
            return
        with self.lock:
            self.active_source, self.mux_state_t = source, self.now()

    def on_cmd(self, msg):
        with self.lock:              # handled on the main thread (run_cmds)
            self.cmds.append(msg.data)

    def on_map(self, msg):
        self.map_msg, self.map_new = msg, True

    def on_plan(self, msg):
        self.plan = [(ps.pose.position.x, ps.pose.position.y) for ps in msg.poses]
        self.plan_frame, self.plan_t = msg.header.frame_id or self.map_frame, self.now()

    def on_bringup(self, msg):
        try:
            self.bringup = core.compact_bringup(json.loads(msg.data))
        except (ValueError, AttributeError, TypeError) as e:
            self.get_logger().warn(f'bad /bringup/status: {e}', throttle_duration_sec=10.0)
            return
        self.bringup_t = self.now()

    # ---- commands ----------------------------------------------------------

    def current_source(self):
        with self.lock:
            if self.mux_state_t is None or self.now() - self.mux_state_t > self.g('mux_state_timeout'):
                return None
            return self.active_source

    def run_cmds(self):
        while True:
            with self.lock:
                if not self.cmds:
                    return
                text = self.cmds.popleft()
            reason = self.handle_cmd(text)
            self.rejected = reason
            if reason:
                self.get_logger().warn(reason)
            self.publish_state()

    def handle_cmd(self, text):
        """Run one nav_cmd. Returns None if accepted, else the reason."""
        try:
            cmd = core.parse_cmd(text)
        except ValueError as e:
            return f'nav_cmd refused: {e}'
        name = cmd['cmd']
        self.last_cmd, self.last_cmd_t = name, self.now()
        source = self.current_source()
        if source is None:
            return f'{name} refused: teleop_mux source unknown (no /teleop/state)'
        if source != 'phone':
            return f'{name} refused: active source is {source}'
        if name == 'goal':
            return self.send_goal(cmd['x'], cmd['y'], cmd['yaw'])
        if name == 'cancel':
            return self.cancel()
        return self.call_bringup(name)

    def send_goal(self, x, y, yaw):
        if not self.nav.server_is_ready():
            return f'goal refused: Nav2 action server {self.g("action_name")} not available'
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.map_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        q = goal.pose.pose.orientation
        q.x, q.y, q.z, q.w = core.yaw_to_quat(yaw)
        self.gen += 1
        gen = self.gen
        # a goal sent while another runs preempts it in Nav2; the old one's callbacks are ignored
        self.goal_handle, self.cancel_pending, self.feedback = None, False, None
        self.status, self.reason = 'navigating', 'waiting for Nav2 to accept'
        self.goal, self.goal_t = {'x': x, 'y': y, 'yaw': math.atan2(math.sin(yaw), math.cos(yaw))}, self.now()
        fut = self.nav.send_goal_async(goal, feedback_callback=lambda f, gen=gen: self.on_feedback(gen, f))
        fut.add_done_callback(lambda f, gen=gen: self.on_goal_response(gen, f))
        self.get_logger().info(f'goal x={x:.2f} y={y:.2f} yaw={yaw:.2f} sent')
        return None

    def on_goal_response(self, gen, fut):
        if gen != self.gen:
            return
        try:
            handle = fut.result()
        except Exception as e:  # noqa: BLE001
            self.status, self.reason = 'aborted', f'sending the goal failed: {e}'
            return
        if not handle.accepted:
            self.status, self.reason = 'aborted', 'Nav2 rejected the goal'
            return
        self.goal_handle, self.reason = handle, None
        handle.get_result_async().add_done_callback(lambda f, gen=gen: self.on_result(gen, f))
        if self.cancel_pending:
            self.cancel()

    def on_feedback(self, gen, msg):
        if gen != self.gen:
            return
        fb = msg.feedback
        self.feedback = {
            'distance_remaining': r3(fb.distance_remaining),
            'eta': r3(Duration.from_msg(fb.estimated_time_remaining).nanoseconds * 1e-9),
            'navigation_time': r3(Duration.from_msg(fb.navigation_time).nanoseconds * 1e-9),
            'recoveries': int(fb.number_of_recoveries),
        }

    def on_result(self, gen, fut):
        if gen != self.gen:
            return
        try:
            status = fut.result().status
        except Exception as e:  # noqa: BLE001
            self.status, self.reason = 'aborted', f'no result from Nav2: {e}'
        else:
            self.status = RESULT_STATUS.get(status, 'aborted')
            self.reason = {'aborted': 'Nav2 aborted the goal', 'canceled': None,
                           'succeeded': None}[self.status]
            if status not in RESULT_STATUS:
                self.reason = f'Nav2 ended the goal with status {status}'
        self.goal_handle, self.cancel_pending, self.feedback = None, False, None
        self.get_logger().info(f'goal {self.status}' + (f': {self.reason}' if self.reason else ''))
        self.publish_state()

    def cancel(self):
        if self.status != 'navigating':
            return 'cancel refused: no active goal'
        if self.goal_handle is None:                  # not accepted yet: cancel once it is
            self.cancel_pending, self.reason = True, 'cancel requested'
            return None
        self.reason = 'cancel requested'
        self.goal_handle.cancel_goal_async()
        self.get_logger().info('cancel sent')
        return None

    def call_bringup(self, name):
        cli = self.bringup_cli[name]
        if not cli.service_is_ready():
            return f'{name} refused: {cli.srv_name} not available (app_bringup_manager running?)'
        t = self.now()

        def done(fut):
            try:
                res = fut.result()
                self.bringup_reply = {'cmd': name, 'success': bool(res.success), 'message': res.message, 't': t}
            except Exception as e:  # noqa: BLE001
                self.bringup_reply = {'cmd': name, 'success': False, 'message': f'call failed: {e}', 't': t}
            self.publish_state()
        cli.call_async(Trigger.Request()).add_done_callback(done)
        self.get_logger().info(f'{cli.srv_name} called')
        return None

    # ---- outputs -----------------------------------------------------------

    def maybe_send_map(self):
        if not self.map_new:
            return
        now = self.now()
        if self.map_sent_t is not None and now - self.map_sent_t < 1.0 / self.g('map_max_rate'):
            return
        msg, self.map_new = self.map_msg, False
        info = msg.info
        if info.width == 0 or info.height == 0 or len(msg.data) != info.width * info.height:
            self.get_logger().warn('empty or malformed map, not sent', throttle_duration_sec=10.0)
            return
        t0 = time.monotonic()
        img, factor = core.downsample_grid(msg.data, info.width, info.height, self.g('map_max_size'),
                                           self.g('occupied_thresh'), self.g('free_thresh'))
        png = core.encode_png(img)
        work_ms = (time.monotonic() - t0) * 1e3
        o = info.origin
        origin = {'x': o.position.x, 'y': o.position.y,
                  'yaw': core.quat_to_yaw(o.orientation.x, o.orientation.y, o.orientation.z, o.orientation.w)}
        key = (png, factor, info.resolution, tuple(origin.values()), msg.header.frame_id)
        if key == self.map_key:                  # unchanged: nothing re-sent
            return
        self.map_key, self.map_sent_t = key, now
        self.map_seq += 1
        stamp = self.get_clock().now().to_msg()
        image = CompressedImage(format='png', data=png)
        image.header.stamp, image.header.frame_id = stamp, msg.header.frame_id or self.map_frame
        meta = {
            'seq': self.map_seq,
            'stamp': stamp.sec + stamp.nanosec * 1e-9,
            'map_stamp': msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9,
            'frame_id': image.header.frame_id,
            'resolution': info.resolution * factor,
            'width': int(img.shape[1]), 'height': int(img.shape[0]),
            'origin': origin,
            'downsample': factor,
            'source_resolution': info.resolution,
            'source_width': info.width, 'source_height': info.height,
            'encoding': 'png',
            'values': {'free': core.FREE, 'occupied': core.OCCUPIED, 'unknown': core.UNKNOWN},
            'bytes': len(png),
        }
        meta_msg = String(data=json.dumps(meta))
        for pub in self.meta_pubs:               # meta first: an app that waits for both pairs them by seq/stamp
            pub.publish(meta_msg)
        for pub in self.map_pubs:
            pub.publish(image)
        self.get_logger().info(f'map #{self.map_seq} sent: {info.width}x{info.height} -> '
                               f'{meta["width"]}x{meta["height"]} (x{factor}), {len(png)} B PNG, {work_ms:.0f} ms')

    def lookup_2d(self, target, source):
        """Planar transform target <- source at the latest time: (tx, ty, yaw, age)."""
        t = self.tf.lookup_transform(target, source, Time())
        tr, q = t.transform.translation, t.transform.rotation
        age = self.now() - Time.from_msg(t.header.stamp).nanoseconds * 1e-9
        return tr.x, tr.y, core.quat_to_yaw(q.x, q.y, q.z, q.w), age

    def publish_state(self):
        now = self.now()
        pose, pose_error = None, None
        try:
            x, y, yaw, age = self.lookup_2d(self.map_frame, self.base_frame)
            # a static transform has stamp 0: report age 0, not decades
            pose = {'x': r3(x), 'y': r3(y), 'yaw': r3(yaw), 'age': r3(max(0.0, age) if age < 1e6 else 0.0)}
        except tf2_ros.TransformException as e:
            pose_error = str(e).splitlines()[0][:200]
        plan, plan_age = [], None
        if self.plan_t is not None and now - self.plan_t <= self.g('plan_max_age'):
            plan_age = r3(now - self.plan_t)
            pts = core.downsample_path(self.plan, self.g('plan_max_points'))
            if self.plan_frame != self.map_frame:
                try:
                    tx, ty, tyaw, _ = self.lookup_2d(self.map_frame, self.plan_frame)
                    pts = core.transform_2d(pts, tx, ty, tyaw)
                except tf2_ros.TransformException:
                    pts, plan_age = [], None
            plan = [[round(px, 2), round(py, 2)] for px, py in pts]
            if not plan:
                plan_age = None
        fb = self.feedback if self.status == 'navigating' and self.feedback else {}
        bringup = None
        if self.bringup is not None:
            bringup = dict(self.bringup, age=r3(now - self.bringup_t))
        reply = None
        if self.bringup_reply is not None:
            reply = {k: v for k, v in self.bringup_reply.items() if k != 't'}
            reply['age'] = r3(now - self.bringup_reply['t'])
        state = {
            'stamp': r3(now),
            'frame_id': self.map_frame,
            'pose': pose,
            'pose_error': pose_error,
            'nav2_ready': self.nav.server_is_ready(),
            'status': self.status,
            'reason': self.reason,
            'goal': None if self.goal is None else {k: r3(v) for k, v in self.goal.items()} | {'age': r3(now - self.goal_t)},
            'distance_remaining': fb.get('distance_remaining'),
            'eta': fb.get('eta'),
            'navigation_time': fb.get('navigation_time'),
            'recoveries': fb.get('recoveries'),
            'plan': plan,
            'plan_age': plan_age,
            'bringup': bringup,
            'bringup_reply': reply,
            'last_cmd': self.last_cmd,
            'last_cmd_age': None if self.last_cmd_t is None else r3(now - self.last_cmd_t),
            'rejected': self.rejected,
        }
        msg = String(data=json.dumps(state))
        for pub in self.state_pubs:
            pub.publish(msg)


def main():
    rclpy.init()
    rclpy.spin(NavRelay(phone_node('nav_relay_phone')))


if __name__ == '__main__':
    main()
