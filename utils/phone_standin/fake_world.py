#!/usr/bin/env python3
"""Fake SLAM + Nav2 + bringup manager, so the phone's Autonav page can be tried without
a robot (laptop stand-in for orintwo, see README.md).

Main domain only (nav_relay carries it to the phone):
  /rtabmap/map         latched OccupancyGrid: a 20 x 14 m room with walls and boxes, 5 cm
  TF map->chassis_link the fake robot; it drives straight to each goal at 0.5 m/s
  /plan                straight line robot -> goal while navigating
  /navigate_to_pose    NavigateToPose action: feedback, succeed on arrival, cancel works;
                       goals inside a wall or box are aborted
  /bringup/go|stop     Trigger; /bringup/status (latched) flips all stages ready / stopped
"""
import array
import json
import math
import threading
import time

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Path
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster

LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
RES, W, H = 0.05, 400, 280           # 20 m x 14 m
ORIGIN = (-2.0, -2.0)
SPEED = 0.5                          # m/s
STAGES = [('preflight', 'Preflight'), ('robot_model', 'Robot model'), ('lidar', 'Ouster lidar'),
          ('slam', 'SLAM'), ('nav2', 'Nav2'), ('rover', 'Rover link')]


def make_grid():
    g = np.zeros((H, W), np.int8)
    g[:4, :] = g[-4:, :] = g[:, :4] = g[:, -4:] = 100          # outer walls
    g[140:144, 4:250] = 100                                     # inner wall, gap on the right
    g[60:100, 280:330] = 100                                    # a box
    g[190:230, 80:120] = 100                                    # another box
    g[240:276, 300:396] = -1                                    # unexplored corner
    return g


class FakeWorld(Node):
    def __init__(self):
        super().__init__('fake_world')
        grp = ReentrantCallbackGroup()
        self.grid = make_grid()
        self.pose = [1.0, 1.0, 0.0]
        self.goal = None
        self.lock = threading.Lock()
        self.tfb = TransformBroadcaster(self)
        self.plan_pub = self.create_publisher(Path, '/plan', 1)
        self.status_pub = self.create_publisher(String, '/bringup/status', LATCHED)
        map_pub = self.create_publisher(OccupancyGrid, '/rtabmap/map', LATCHED)
        m = OccupancyGrid()
        m.header.frame_id = 'map'
        m.header.stamp = self.get_clock().now().to_msg()
        m.info.resolution, m.info.width, m.info.height = RES, W, H
        m.info.origin.position.x, m.info.origin.position.y = ORIGIN
        m.info.origin.orientation.w = 1.0
        m.data = array.array('b', self.grid.tobytes())
        map_pub.publish(m)
        self.create_timer(0.05, self.pub_tf)
        self.create_timer(1.0, self.pub_plan)
        for name in ('go', 'stop'):
            self.create_service(Trigger, f'/bringup/{name}', lambda q, r, n=name: self.on_trigger(n, r),
                                callback_group=grp)
        ActionServer(self, NavigateToPose, '/navigate_to_pose', self.execute,
                     goal_callback=lambda g: GoalResponse.ACCEPT,
                     cancel_callback=lambda h: CancelResponse.ACCEPT, callback_group=grp)
        self.publish_status('ready')
        self.get_logger().info('fake world up: room 20x14 m, robot at (1, 1)')

    def blocked(self, x, y):
        u, v = int((x - ORIGIN[0]) / RES), int((y - ORIGIN[1]) / RES)
        return not (0 <= u < W and 0 <= v < H) or self.grid[v, u] != 0

    def pub_tf(self):
        with self.lock:
            x, y, yaw = self.pose
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = 'map', 'chassis_link'
        t.transform.translation.x, t.transform.translation.y = x, y
        t.transform.rotation.z, t.transform.rotation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.tfb.sendTransform(t)

    def pub_plan(self):
        with self.lock:
            if self.goal is None:
                return
            (x0, y0, _), (x1, y1) = self.pose, self.goal[:2]
        p = Path()
        p.header.frame_id = 'map'
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 0.05))
        for i in range(n + 1):
            ps = PoseStamped()
            ps.pose.position.x, ps.pose.position.y = x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n
            p.poses.append(ps)
        self.plan_pub.publish(p)

    def publish_status(self, state):
        stages = [{'name': n, 'title': t, 'state': state, 'required': n != 'rover',
                   'message': 'fake' if state == 'ready' else 'stopped',
                   'checks': [{'label': f'{t} (fake)', 'ok': state == 'ready', 'value': state, 'hint': ''}]}
                  for n, t in STAGES]
        self.status_pub.publish(String(data=json.dumps(
            {'stamp': time.time(), 'overall': state, 'stages': stages})))

    def on_trigger(self, name, res):
        self.publish_status('ready' if name == 'go' else 'stopped')
        res.success, res.message = True, f'fake {name} done'
        return res

    def execute(self, handle):
        p = handle.request.pose.pose
        gx, gy = p.position.x, p.position.y
        gyaw = 2 * math.atan2(p.orientation.z, p.orientation.w)
        self.get_logger().info(f'goal ({gx:.2f}, {gy:.2f}, yaw {gyaw:.2f})')
        if self.blocked(gx, gy):
            self.get_logger().info('goal is in an obstacle -> abort')
            handle.abort()
            return NavigateToPose.Result()
        with self.lock:
            self.goal = (gx, gy, gyaw)
        fb, t0, dt = NavigateToPose.Feedback(), time.time(), 0.1
        try:
            while True:
                if handle.is_cancel_requested:
                    handle.canceled()
                    return NavigateToPose.Result()
                with self.lock:
                    x, y, _ = self.pose
                    d = math.hypot(gx - x, gy - y)
                    if d < SPEED * dt:
                        self.pose = [gx, gy, gyaw]
                        break
                    h = math.atan2(gy - y, gx - x)
                    self.pose = [x + SPEED * dt * math.cos(h), y + SPEED * dt * math.sin(h), h]
                fb.distance_remaining = float(d)
                fb.estimated_time_remaining.sec = int(d / SPEED)
                fb.navigation_time.sec = int(time.time() - t0)
                handle.publish_feedback(fb)
                time.sleep(dt)
            handle.succeed()
            return NavigateToPose.Result()
        finally:
            with self.lock:
                self.goal = None


def main():
    rclpy.init()
    ex = MultiThreadedExecutor()
    ex.add_node(FakeWorld())
    ex.spin()


if __name__ == '__main__':
    main()
