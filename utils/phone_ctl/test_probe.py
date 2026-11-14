"""phone_probe.py (the ROS checks phone_ctl.sh runs in app_teleop_container) against the
real teleop_mux + rover_arming on loopback DDS. Domains as in utils/rover_arming:
77 = robot (main), 79 = phone. Runs inside the container from run.sh."""
import json
import os
import subprocess
import threading
import time

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Joy
from std_msgs.msg import String

APP = os.environ.get('APP_DIR', '/repo/src/app_teleop')
PHONE = int(os.environ.get('TELEOP_PHONE_DOMAIN', '79'))


def probe(*args, timeout=40):
    p = subprocess.run(['python3', f'{APP}/phone_probe.py', *args], capture_output=True, text=True,
                       timeout=timeout, cwd=os.path.dirname(APP))
    out = p.stdout.strip().splitlines()
    assert out, p.stderr
    return p.returncode, out[-1]


class Side:
    """A node in one domain, spinning in its own thread."""
    def __init__(self, domain, name):
        self.ctx = rclpy.Context()
        rclpy.init(context=self.ctx, domain_id=domain)
        self.node = Node(name, context=self.ctx)
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(self.node)
        self.stop = False
        self.th = threading.Thread(target=self._spin, daemon=True)
        self.th.start()

    def _spin(self):
        while not self.stop:
            self.ex.spin_once(timeout_sec=0.05)

    def close(self):
        self.stop = True
        self.th.join(2)
        rclpy.shutdown(context=self.ctx)


@pytest.fixture(scope='module')
def stack():
    env = dict(os.environ, TELEOP_SOURCE='phone')
    params = ['--ros-args', '--params-file', f'{APP}/config/teleop.yaml']
    procs = [subprocess.Popen(['python3', f'{APP}/{n}.py', *params], env=env)
             for n in ('teleop_mux', 'rover_arming')]
    main = Side(int(os.environ.get('ROS_DOMAIN_ID', '77')), 'test_main')
    joy = []
    main.node.create_subscription(Joy, '/joy', lambda m: joy.append(m), 10)   # stands in for robot_control
    # wait until both nodes are up
    rc, out = probe('mux_source', '--timeout', '30')
    assert rc == 0, out
    yield main, joy
    main.close()
    for p in procs:
        p.terminate()
        p.wait(5)


def test_mux_source(stack):
    assert probe('mux_source') == (0, 'ok phone')


def test_subs(stack):
    rc, out = probe('subs', '/joy', '/cmd_vel_auto')
    assert rc == 0 and out.startswith('ok /joy:') and '/cmd_vel_auto:' in out
    rc, out = probe('subs', '/joy', '/nobody_here', '--timeout', '2')
    assert rc == 1 and out == 'fail no subscriber on /nobody_here'


def test_rover_cmd_reset_after_arm(stack):
    main, joy = stack
    rc, out = probe('rover_cmd', 'arm', '--timeout', '10')
    assert rc == 0 and out == 'ok arm by phone: autonomous/ackermann/running', out
    rc, out = probe('rover_cmd', 'reset', '--timeout', '10')
    assert rc == 0 and out == 'ok reset by phone: manual/crab/stopped', out
    assert any(m.buttons[16] == 1 for m in joy)


def test_rover_cmd_refused(stack):
    rc, out = probe('rover_cmd', 'bogus', '--timeout', '5')
    assert rc == 1 and out.startswith('fail rover_arming refused bogus'), out


def test_rate_phone_domain(stack):
    side = Side(PHONE, 'test_camera')
    pub = side.node.create_publisher(CompressedImage, '/teleop/camera/compressed', 10)
    stop = threading.Event()

    def feed():
        while not stop.is_set():
            pub.publish(CompressedImage(format='jpeg', data=b'\xff\xd8\xff\xd9'))
            time.sleep(0.1)
    th = threading.Thread(target=feed, daemon=True)
    th.start()
    try:
        rc, out = probe('rate', '/teleop/camera/compressed', '--phone', '--window', '3', '--timeout', '10')
        assert rc == 0, out
        assert 8.0 <= float(out.split()[1]) <= 11.0, out
        # the same topic in the main domain has nothing
        rc, out = probe('rate', '/teleop/camera/compressed', '--window', '1', '--timeout', '2')
        assert rc == 1 and out.startswith('fail no message'), out
    finally:
        stop.set()
        th.join(2)
        side.close()


def test_no_mux():
    # a domain nobody uses: clean failure with a reason, exit 1
    p = subprocess.run(['python3', f'{APP}/phone_probe.py', 'mux_source', '--timeout', '1'],
                       capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, ROS_DOMAIN_ID='88'))
    assert p.returncode == 1
    assert p.stdout.strip().splitlines()[-1].startswith('fail no /teleop/state within 1 s')


def test_json_state_shape(stack):
    # rover_state seen by the probe's check has the fields phone_ctl relies on
    main, _ = stack
    got = {}
    main.node.create_subscription(String, '/teleop/rover_state', lambda m: got.update(json.loads(m.data)), 10)
    end = time.monotonic() + 5
    while not got and time.monotonic() < end:
        time.sleep(0.1)
    assert {'last_cmd', 'last_cmd_age', 'rejected', 'input', 'steering', 'motion'} <= set(got)
