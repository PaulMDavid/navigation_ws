"""The real pieces on loopback DDS (domain from ROS_DOMAIN_ID, 83 in run.sh):
- phone_probe.py `topics`: type, Hz, MB/s of live publishers;
- record_drive.sh start/status/stop with the real recorder command: the fake docker runs
  the `bash -c` body itself (FAKE_REC_REAL), i.e. real `ros2 bag record` + record_watch.py,
  and the real probe for the sensor check (FAKE_PROBE_REAL);
- a power cut (SIGKILL) leaves an unclosed bag; `ros2 bag reindex -s sqlite3` recovers it.
Runs inside the container from run.sh (/bags is a tmpfs, /navws_record = scripts/record)."""
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
import rclpy
import yaml
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Imu
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage
from geometry_msgs.msg import TransformStamped

from test_record import FAKES, RECORD, check_format, final

APP = os.environ.get('APP_DIR', '/repo/src/app_teleop')
BAGS = Path('/bags')
IMG_BYTES = 20000


class Pubs:
    """/imu/data 50 Hz, /cam/compressed 10 Hz (20 kB), /slow 2 Hz, latched /tf_static."""
    def __init__(self):
        self.ctx = rclpy.Context()
        rclpy.init(context=self.ctx)
        self.node = Node('record_test_pubs', context=self.ctx)
        n = self.node
        self.imu = n.create_publisher(Imu, '/imu/data', 10)
        self.cam = n.create_publisher(CompressedImage, '/cam/compressed', 10)
        self.slow = n.create_publisher(String, '/slow', 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.tfs = n.create_publisher(TFMessage, '/tf_static', latched)
        self.tfs.publish(TFMessage(transforms=[TransformStamped()]))
        self.slow_on = True
        img = CompressedImage(format='jpeg', data=bytes(IMG_BYTES))
        n.create_timer(0.02, lambda: self.imu.publish(Imu()))
        n.create_timer(0.1, lambda: self.cam.publish(img))
        n.create_timer(0.5, lambda: self.slow_on and self.slow.publish(String(data='x')))
        self.ex = SingleThreadedExecutor(context=self.ctx)
        self.ex.add_node(n)
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
def pubs():
    p = Pubs()
    time.sleep(1)
    yield p
    p.close()


def probe(*args, timeout=60):
    p = subprocess.run(['python3', f'{APP}/phone_probe.py', *args], capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip().splitlines()
    rows = {}
    for line in out:
        if line.startswith('topic '):
            r = json.loads(line[6:])
            rows[r['name']] = r
    return p.returncode, out[-1], rows


def test_probe_topics_all(pubs):
    t0 = time.monotonic()
    rc, last, rows = probe('topics', '--window', '3')
    assert rc == 0 and last.startswith('ok '), last
    assert time.monotonic() - t0 < 15, 'bounded: discover 2 s + match 0.5 s + window 3 s'
    imu, cam = rows['/imu/data'], rows['/cam/compressed']
    assert imu['type'] == 'sensor_msgs/msg/Imu' and 40 <= imu['hz'] <= 55, imu
    assert cam['type'] == 'sensor_msgs/msg/CompressedImage' and 8 <= cam['hz'] <= 11, cam
    assert 0.15 <= cam['mbps'] <= 0.23, cam                     # 10 Hz x ~20 kB
    assert rows['/tf_static']['hz'] == 0.0                      # latched: volatile probe gets no history
    assert 1 <= rows['/slow']['hz'] <= 3


def test_probe_topics_named(pubs):
    rc, last, rows = probe('topics', '--window', '2', '/imu/data', '/not/there')
    assert rc == 0 and 'not in the graph: /not/there' in last
    assert set(rows) == {'/imu/data', '/not/there'}
    assert rows['/not/there'] == {'name': '/not/there', 'type': None, 'hz': None, 'mbps': None}
    assert rows['/imu/data']['hz'] > 30


PRESETS = {
    'groups': {'test': {'label': 'test', 'topics': ['/imu/data', '/cam/compressed', '/slow', '/tf_static']}},
    'presets': {'t': {'label': 'T', 'default': True, 'groups': ['test']}},
    'sensors': {'s': {'groups': ['test'], 'container': 'fake_sensor', 'check': ['/imu/data', '/cam/compressed']}},
    'quiet_ok': ['/tf_static'],
}


@pytest.fixture
def env(tmp_path, pubs):
    fake = tmp_path / 'fake'
    (fake / 'containers').mkdir(parents=True)
    (fake / 'containers/app_teleop_container').write_text('')
    (tmp_path / 'presets.yaml').write_text(yaml.safe_dump(PRESETS))
    for d in BAGS.iterdir():
        shutil.rmtree(d) if d.is_dir() else d.unlink()
    e = dict(os.environ, PATH=f'{FAKES}:{os.environ["PATH"]}', FAKE=str(fake), BAGS_DIR=str(BAGS),
             SSD_MOUNT='/bags', RECORD_PRESETS=str(tmp_path / 'presets.yaml'), RECORD_DDS='/etc/cyclonedds.xml',
             RECORD_DOMAIN=os.environ.get('ROS_DOMAIN_ID', '83'), RECORD_LOCK=str(tmp_path / 'rec.lock'),
             FAKE_REC_REAL='1', FAKE_PROBE_REAL='1', FAKE_AVAIL='500000000000', PHONE_CTL_POLL='0.3',
             SILENT_WINDOW='3', SENSOR_TIMEOUT='20', RECORD_SETTLE='3', STOP_TIMEOUT='60')
    yield e
    for f in (fake / 'containers').iterdir():
        pid = f.read_text().strip()
        if pid:
            subprocess.run(['kill', '-KILL', '--', f'-{pid}'], capture_output=True)


def rec(env, *args, timeout=120):
    p = subprocess.run(['bash', str(RECORD), *args], env=env, capture_output=True, text=True, timeout=timeout)
    lines = [json.loads(x) for x in p.stdout.splitlines()]
    check_format(lines)
    return p, lines


def bag_info(bag):
    return yaml.safe_load((BAGS / bag / 'metadata.yaml').read_text())['rosbag2_bagfile_information']


def test_record_cycle(env, pubs):
    p, lines = rec(env, 'start', 't')
    f = final(lines)
    assert p.returncode == 0, p.stdout + p.stderr + (BAGS / 'x').as_posix()
    assert f['sensors']['state'] == 'ok', f['sensors']
    bag = f['record']['bag']
    assert f['record']['subscribed'] == 4, (BAGS / f'{bag}_record.log').read_text()
    time.sleep(4)                                # > SILENT_WINDOW of watcher age
    _, lines = rec(env, 'status', 'once')
    s = lines[0]
    assert s['recording'] and s['silent'] == [] and s['state'] == 'ok', (s, (BAGS / f'{bag}_watch.log').read_text())
    assert s['size_mb'] > 0 and 0.1 < s['input_mbps'] < 0.4, s
    # /slow stops: reported after the window; latched /tf_static never
    pubs.slow_on = False
    time.sleep(4)
    _, lines = rec(env, 'status', 'once')
    assert lines[0]['silent'] == ['/slow'] and lines[0]['state'] == 'warn', lines[0]
    pubs.slow_on = True
    p, lines = rec(env, 'stop')
    s = final(lines)['stop']
    assert s['state'] == 'ok' and p.returncode == 0, lines
    info = bag_info(bag)
    assert info['storage_identifier'] == 'sqlite3'
    assert info['compression_format'] == 'zstd' and info['compression_mode'] == 'FILE'
    assert all(x.endswith('.db3.zstd') for x in info['relative_file_paths'])
    counts = {t['topic_metadata']['name']: t['message_count'] for t in info['topics_with_message_count']}
    assert counts['/imu/data'] > 200 and counts['/cam/compressed'] > 50
    assert counts['/tf_static'] == 1, 'QoS override: latched message published before the recorder started'
    assert s['messages'] == info['message_count'] and abs(s['duration_s'] - info['duration']['nanoseconds'] / 1e9) < 0.2


def test_power_cut_reindex(env, pubs):
    p, lines = rec(env, 'start', 't')
    bag = final(lines)['record']['bag']
    time.sleep(3)
    pid = (Path(env['FAKE']) / 'containers/rec_drive').read_text().strip()
    subprocess.run(['kill', '-KILL', '--', f'-{pid}'])            # power cut
    time.sleep(1)
    _, lines = rec(env, 'status')
    s = lines[0]
    assert not s['recording'] and s['bag'] == bag and s['unclosed'] == [bag] and s['state'] == 'warn'
    assert not (BAGS / bag / 'metadata.yaml').exists()
    r = subprocess.run(['ros2', 'bag', 'reindex', '-s', 'sqlite3', str(BAGS / bag)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    info = bag_info(bag)
    counts = {t['topic_metadata']['name']: t['message_count'] for t in info['topics_with_message_count']}
    assert counts.get('/imu/data', 0) > 0, info
    _, lines = rec(env, 'status')
    assert lines[0]['unclosed'] == []
