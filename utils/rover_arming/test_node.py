"""ROS-level test of rover_arming.py with the real teleop_mux, on loopback DDS.

Domains as in utils/teleop_link: 77 = robot (main), 79 = phone. Runs inside the
container from run.sh. Checks what crosses the topics: /joy messages, the JSON on
/teleop/rover_state in both domains, source gating, and teleop_mux's max_angular
following the tracked steering."""
import json
import os
import subprocess
import time

import pytest
import rclpy
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import String

APP = os.environ.get('APP_DIR', '/workspace/app_teleop')
MAIN, PHONE = int(os.environ.get('ROS_DOMAIN_ID', '77')), int(os.environ.get('TELEOP_PHONE_DOMAIN', '79'))


class Probe:
    def __init__(self, domain, name):
        self.ctx = rclpy.Context()
        rclpy.init(context=self.ctx, domain_id=domain)
        self.node = Node(name, context=self.ctx)
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(self.node)
        self.rover_state = None
        self.mux_state = None
        self.joy = []
        self.node.create_subscription(String, '/teleop/rover_state',
                                      lambda m: setattr(self, 'rover_state', json.loads(m.data)), 10)
        self.node.create_subscription(String, '/teleop/state',
                                      lambda m: setattr(self, 'mux_state', json.loads(m.data)), 10)
        self.node.create_subscription(Joy, '/joy', lambda m: self.joy.append((time.monotonic(), m)), 10)
        self.cmd = {s: self.node.create_publisher(String, f'/teleop/{s}/rover_cmd', 10)
                    for s in ('ground', 'phone')}

    def spin(self, secs):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            self.ex.spin_once(timeout_sec=0.02)


@pytest.fixture(scope='module')
def stack():
    env = dict(os.environ, TELEOP_SOURCE='phone')
    params = ['--ros-args', '--params-file', f'{APP}/config/teleop.yaml']
    procs = [subprocess.Popen(['python3', f'{APP}/{n}.py', *params], env=env)
             for n in ('teleop_mux', 'rover_arming')]
    main, phone = Probe(MAIN, 'probe_main'), Probe(PHONE, 'probe_phone')
    # both nodes up and discovered
    end = time.monotonic() + 30
    while time.monotonic() < end and not (main.rover_state and phone.rover_state and main.mux_state):
        main.spin(0.1)
        phone.spin(0.1)
    assert main.rover_state and phone.rover_state and main.mux_state, 'stack did not come up'
    yield main, phone
    for p in procs:
        p.terminate()
        p.wait(5)


def both(main, phone, secs):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        main.spin(0.02)
        phone.spin(0.02)


def send(main, phone, probe, source, cmd, secs=2.0):
    for _ in range(20):                 # until the publisher is matched
        if probe.cmd[source].get_subscription_count():
            break
        both(main, phone, 0.1)
    probe.cmd[source].publish(String(data=cmd))
    both(main, phone, secs)


def pressed(joy):
    return [list(m.buttons).index(1) for _, m in joy if any(m.buttons)]


def test_boot_state_both_domains(stack):
    main, phone = stack
    for p in stack:
        s = p.rover_state
        assert s['tracked'] is True
        assert (s['input'], s['steering'], s['motion']) == ('manual', 'crab', 'stopped')
        assert s['last_cmd'] is None and s['rejected'] is None
    assert main.mux_state['source'] == 'phone'


def test_state_rate(stack):
    main, phone = stack
    n = []
    sub = main.node.create_subscription(String, '/teleop/rover_state', lambda m: n.append(1), 10)
    both(main, phone, 3.0)
    main.node.destroy_subscription(sub)
    assert 2.0 <= len(n) / 3.0 <= 5.5     # 4 Hz plus on-change publishes


def test_ground_rejected_while_phone_active(stack):
    main, phone = stack
    main.joy.clear()
    send(main, phone, main, 'ground', 'arm')
    assert main.joy == []
    assert 'active source is phone' in phone.rover_state['rejected']
    assert phone.rover_state['input'] == 'manual'


def test_phone_arm(stack):
    main, phone = stack
    main.joy.clear()
    send(main, phone, phone, 'phone', 'arm', secs=3.0)
    assert pressed(main.joy) == [1, 16, 2]
    assert len(main.joy) == 6
    for _, m in main.joy:
        assert len(m.axes) == 8 and not any(m.axes) and len(m.buttons) == 17
    t = [t for t, _ in main.joy]
    assert min(b - a for a, b in zip(t, t[1:])) > 0.1
    s = phone.rover_state
    assert (s['input'], s['steering'], s['motion']) == ('autonomous', 'ackermann', 'running')
    assert (s['last_cmd'], s['last_cmd_by'], s['presses'], s['rejected']) == ('arm', 'phone', 3, None)
    assert main.mux_state['max_angular'] == pytest.approx(1.0)


def test_steer_idempotent_and_crab_limit(stack):
    main, phone = stack
    main.joy.clear()
    send(main, phone, phone, 'phone', 'steer_ackermann', secs=1.0)
    assert main.joy == []
    send(main, phone, phone, 'phone', 'steer_crab')
    send(main, phone, phone, 'phone', 'steer_crab')
    assert pressed(main.joy) == [16]
    assert phone.rover_state['steering'] == 'crab'
    assert main.mux_state['max_angular'] == pytest.approx(0.1)


def test_reset(stack):
    main, phone = stack
    send(main, phone, phone, 'phone', 'steer_ackermann')
    assert main.mux_state['max_angular'] == pytest.approx(1.0)
    main.joy.clear()
    send(main, phone, phone, 'phone', 'reset')
    assert main.joy == []
    s = phone.rover_state
    assert (s['input'], s['steering'], s['motion'], s['last_cmd']) == ('manual', 'crab', 'stopped', 'reset')
    assert main.mux_state['max_angular'] == pytest.approx(0.1)


def test_ground_accepted_after_source_switch(stack):
    main, phone = stack
    cli = main.node.create_client(SetParameters, '/teleop_mux/set_parameters')
    assert cli.wait_for_service(timeout_sec=5)
    fut = cli.call_async(SetParameters.Request(parameters=[Parameter(
        name='source', value=ParameterValue(type=ParameterType.PARAMETER_STRING, string_value='ground'))]))
    while not fut.done():
        main.spin(0.05)
    both(main, phone, 1.0)
    assert main.mux_state['source'] == 'ground'
    main.joy.clear()
    send(main, phone, phone, 'phone', 'input_auto')
    assert main.joy == [] and 'active source is ground' in main.rover_state['rejected']
    send(main, phone, main, 'ground', 'input_auto')
    assert pressed(main.joy) == [1]
    assert (main.rover_state['input'], main.rover_state['last_cmd_by']) == ('autonomous', 'ground')
