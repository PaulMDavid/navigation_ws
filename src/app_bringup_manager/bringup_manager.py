#!/usr/bin/env python3
"""Staged bringup of the Nav2 stack, driven from the ground station.

Starts the compose services in stages.yaml one stage at a time, gating each
stage on health checks instead of sleeps, keeps watching them afterwards, and
publishes everything it sees as JSON on /bringup/status. Stages can also load
composable nodes into a running component container (stages_master.yaml), so
recovering one stage reloads its nodes without restarting the whole process.

Interface (all std types, so the GUI needs no custom messages):
  /bringup/go          std_srvs/Trigger  start, or restart from the first stage that isn't ready
  /bringup/stop        std_srvs/Trigger  stop every stage, last first
  /bringup/status      std_msgs/String   JSON snapshot, 1 Hz, transient local
  /bringup/log_request std_msgs/String   container name -> reply on /bringup/logs
  /bringup/logs        std_msgs/String   JSON {container, lines}
"""
import collections
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

import rclpy
import tf2_ros
import yaml
from composition_interfaces.srv import LoadNode, UnloadNode
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from rosidl_runtime_py.utilities import get_message
from std_msgs.msg import String
from std_srvs.srv import Trigger

SELF_CONTAINER = os.environ.get('BRINGUP_SELF_CONTAINER', 'app_bringup_manager_container')
WS_MOUNT = '/navws'          # where src/ is mounted inside this container
STAGES = os.environ.get('BRINGUP_STAGES', 'stages.yaml')  # in app_bringup_manager/
LOAD_TIMEOUT = 60.0          # waiting for the container's load service + the load itself
RATE_WINDOW = 3.0            # seconds of history used for topic_rate
RATE_PERIOD = 15.0           # once up, each topic is sampled for RATE_WINDOW this often
MONITOR_FAILS = 3            # consecutive failed sweeps before a ready stage turns red
LOG_TAIL = 60
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')  # colour codes ROS/rtabmap put in their logs


def sh(cmd, timeout=60):
    """Run a command, return (returncode, combined output)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f'timed out after {timeout}s: {" ".join(cmd)}'


class Docker:
    """docker / docker compose against the host daemon, as the host would run them."""

    def __init__(self):
        info = self.inspect(SELF_CONTAINER)
        if info is None:
            raise RuntimeError(f'cannot inspect own container {SELF_CONTAINER}')
        labels = info['Config']['Labels'] or {}
        self.project = labels.get('com.docker.compose.project', 'navbringup')
        mounts = {m['Destination']: m['Source'] for m in info['Mounts']}
        if WS_MOUNT not in mounts:
            raise RuntimeError(f'{WS_MOUNT} is not mounted into {SELF_CONTAINER}')
        # Host path of src/: relative paths in the compose file must resolve on the host.
        self.host_dir = mounts[WS_MOUNT]
        self.compose_file = os.path.join(WS_MOUNT, 'docker-compose.yaml')
        rc, out = self.compose('config', '--format', 'json')
        if rc != 0:
            raise RuntimeError(f'docker compose config failed:\n{out}')
        services = json.loads(out)['services']
        self.container_of = {s: v.get('container_name', f'{self.project}-{s}-1')
                             for s, v in services.items()}

    def compose(self, *args, timeout=300):
        return sh(['docker', 'compose', '-p', self.project, '-f', self.compose_file,
                   '--project-directory', self.host_dir, *args], timeout)

    @staticmethod
    def inspect(name):
        rc, out = sh(['docker', 'inspect', name], timeout=10)
        return json.loads(out)[0] if rc == 0 else None

    def container_state(self, service):
        name = self.container_of[service]
        info = self.inspect(name)
        if info is None:
            return {'name': name, 'status': 'absent', 'exit_code': None, 'restarts': 0}
        st = info['State']
        project = (info['Config']['Labels'] or {}).get('com.docker.compose.project')
        if project != self.project and not st['Running']:
            # a stopped leftover from another checkout says nothing about our stack
            return {'name': name, 'status': 'absent', 'exit_code': None, 'restarts': 0,
                    'project': project}
        return {'name': name, 'status': 'restarting' if st['Restarting'] else st['Status'],
                'exit_code': st['ExitCode'], 'restarts': info.get('RestartCount', 0),
                'project': project}

    def logs(self, container, tail=LOG_TAIL):
        rc, out = sh(['docker', 'logs', '--tail', str(tail), container], timeout=10)
        return ANSI.sub('', out).splitlines()


class Watcher:
    """Everything the checks read from the ROS graph: topic rates, TF, services."""

    def __init__(self, node):
        self.node = node
        self.group = ReentrantCallbackGroup()
        self.topics = {}  # topic -> {sub, since, arrivals, hz, at}
        self.lock = threading.Lock()
        self.tf_buffer = tf2_ros.Buffer(cache_time=Duration(seconds=10))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, node, spin_thread=False)
        self.clients = {}

    def advertised(self, topic):
        return topic in dict(self.node.get_topic_names_and_types())

    def rate(self, topic, continuous):
        """Messages/s over the last full RATE_WINDOW, or None until one was measured.

        Just receiving /ouster/points costs the manager ~35% of a core, so outside
        bringup (continuous=False) a topic is only subscribed for one window every
        RATE_PERIOD, and the last measurement is reported in between.
        """
        now = time.monotonic()
        t = self.topics.setdefault(topic, {'sub': None, 'since': 0.0, 'hz': None, 'at': 0.0,
                                           'arrivals': collections.deque(maxlen=2000)})
        if t['sub'] is not None and now - t['since'] >= RATE_WINDOW:
            with self.lock:
                n = sum(1 for a in t['arrivals'] if now - a <= RATE_WINDOW)
            t['hz'], t['at'] = n / RATE_WINDOW, now
            if not continuous:
                self.node.destroy_subscription(t['sub'])
                t['sub'] = None
        if t['sub'] is None and (continuous or now - t['at'] >= RATE_PERIOD):
            types = dict(self.node.get_topic_names_and_types()).get(topic)
            if types:
                t['since'] = now
                with self.lock:
                    t['arrivals'].clear()
                # raw=True: count messages without deserializing point clouds
                t['sub'] = self.node.create_subscription(
                    get_message(types[0]), topic,
                    lambda _msg, a=t['arrivals']: self._arrived(a),
                    qos_profile_sensor_data, raw=True, callback_group=self.group)
        if continuous and t['at'] < t['since']:
            return None  # a rate from before this (re)start must not pass a bringup
        return t['hz']

    def _arrived(self, arrivals):
        with self.lock:
            arrivals.append(time.monotonic())

    def transform_age(self, parent, child):
        """Seconds since the transform was stamped; 0 for static; None if missing."""
        try:
            t = self.tf_buffer.lookup_transform(parent, child, Time())
        except tf2_ros.TransformException:
            return None
        stamp = Time.from_msg(t.header.stamp)
        if stamp.nanoseconds == 0:
            return 0.0
        return (self.node.get_clock().now() - stamp).nanoseconds / 1e9

    def call(self, srv_type, service, request, timeout=2.0, wait=0.0):
        """Call a service; None if it isn't available within `wait` s or doesn't answer."""
        client = self.clients.get(service)
        if client is None:
            client = self.clients[service] = self.node.create_client(
                srv_type, service, callback_group=self.group)
        deadline = time.monotonic() + wait
        while not client.service_is_ready():
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.5)
        done = threading.Event()
        future = client.call_async(request)
        future.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            return None
        return future.result()

    def trigger(self, service, timeout=2.0):
        return self.call(Trigger, service, Trigger.Request(), timeout)

    def node_names(self):
        return {f'{ns.rstrip("/")}/{n}' for n, ns in self.node.get_node_names_and_namespaces()}


def params_from_yaml(path, node):
    """Parameters for `node` from a ros__parameters file, as rcl_interfaces messages.

    LoadNode takes parameter messages, not a file, so the file is flattened here.
    A file with a single top-level entry is used as-is, otherwise the entry for the
    node's name (or /**) is.
    """
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if len(data) == 1:
        section = next(iter(data.values()))
    else:
        section = next((data[k] for k in (node, f'/{node}', '/**') if k in data), {})
    params = []

    def flatten(d, prefix=''):
        for k, v in d.items():
            if isinstance(v, dict):
                flatten(v, f'{prefix}{k}.')
            elif v != []:  # an empty list has no type to declare
                params.append(Parameter(f'{prefix}{k}', value=v).to_parameter_msg())
    flatten(section.get('ros__parameters', {}))
    return params


def host_mounts():
    # pid: host makes /proc/1 the host's init, so this is the host's mount table.
    with open('/proc/1/mountinfo') as f:
        return {line.split()[4] for line in f}


class Stage:
    def __init__(self, spec):
        self.name = spec['name']
        self.title = spec.get('title', self.name)
        self.services = spec.get('services', [])
        self.checks = spec.get('checks', [])
        self.pre = spec.get('pre', [])
        self.components = spec.get('components', [])
        self.timeout = spec.get('timeout', 60)
        self.required = spec.get('required', True)
        self.loaded = {}         # component node name -> unique_id in the container
        self.reset()

    def reset(self, state='pending'):
        self.state = state       # pending starting ready warn failed blocked stopped
        self.message = ''
        self.results = []
        self.containers = []
        self.logs = {}
        self.started_at = None
        self.ready_at = None
        self.monitor_fails = 0


class BringupManager(Node):
    def __init__(self, config_path):
        super().__init__('bringup_manager')
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        self.stages = [Stage(s) for s in cfg['stages']]
        self.container = cfg.get('container')           # component container node
        self.config_dir = os.path.join(WS_MOUNT, cfg.get('config_dir', ''))
        self.docker = Docker()
        self.watch = Watcher(self)
        self.lock = threading.RLock()
        self.actions = queue.Queue()
        self.abort = threading.Event()
        self.overall = 'idle'
        self.events = collections.deque(maxlen=100)

        missing = [s for st in self.stages for s in st.services if s not in self.docker.container_of]
        if missing:
            raise RuntimeError(f'services not in docker-compose.yaml: {missing}')

        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        group = ReentrantCallbackGroup()
        self.status_pub = self.create_publisher(String, '/bringup/status', latched)
        self.logs_pub = self.create_publisher(String, '/bringup/logs', 10)
        self.create_service(Trigger, '/bringup/go', self._srv_go, callback_group=group)
        self.create_service(Trigger, '/bringup/stop', self._srv_stop, callback_group=group)
        self.create_subscription(String, '/bringup/log_request', self._on_log_request, 10,
                                 callback_group=group)
        self.create_timer(1.0, self.publish_status, callback_group=group)

        self.event('info', f'manager up: project "{self.docker.project}", '
                           f'compose dir {self.docker.host_dir}')
        threading.Thread(target=self.worker, daemon=True).start()

    # ---- interface ---------------------------------------------------------

    def event(self, level, text):
        self.events.append({'t': time.time(), 'level': level, 'text': text})
        # one call site per severity: rclpy rejects mixed severities from the same line
        if level == 'error':
            self.get_logger().error(text)
        elif level == 'warn':
            self.get_logger().warning(text)
        else:
            self.get_logger().info(text)

    def _srv_go(self, _req, res):
        self.abort.clear()
        self.actions.put('go')
        res.success, res.message = True, 'bringup queued'
        return res

    def _srv_stop(self, _req, res):
        self.abort.set()
        self.actions.put('stop')
        res.success, res.message = True, 'stop queued'
        return res

    def _on_log_request(self, msg):
        container = msg.data.strip()
        if container not in self.docker.container_of.values():
            return
        self.logs_pub.publish(String(data=json.dumps(
            {'container': container, 'lines': self.docker.logs(container, 200)})))

    def publish_status(self):
        with self.lock:
            snap = {
                'stamp': time.time(),
                'overall': self.overall,
                'project': self.docker.project,
                'stages': [{
                    'name': s.name, 'title': s.title, 'state': s.state,
                    'required': s.required, 'message': s.message,
                    'services': s.services, 'timeout': s.timeout,
                    'started_at': s.started_at, 'ready_at': s.ready_at,
                    'checks': s.results, 'containers': s.containers, 'logs': s.logs,
                } for s in self.stages],
                'events': list(self.events),
            }
        self.status_pub.publish(String(data=json.dumps(snap)))

    # ---- checks ------------------------------------------------------------

    def run_check(self, c, continuous):
        """Return (ok, value-for-display); ok is None while a measurement is pending."""
        kind = c['type']
        if kind == 'mount':
            ok = c['path'] in host_mounts()
            return ok, 'mounted' if ok else 'not mounted'
        if kind == 'file':
            ok = os.path.exists(os.path.join(WS_MOUNT, c['path']))
            return ok, 'present' if ok else 'missing'
        if kind == 'ping':
            rc, _ = sh(['ping', '-c', '1', '-W', '1', c['host']], timeout=5)
            return rc == 0, 'reachable' if rc == 0 else 'no reply'
        if kind == 'topic_exists':
            n = self.count_publishers(c['topic'])
            return n > 0, f'{n} publisher(s)'
        if kind == 'topic_rate':
            hz = self.watch.rate(c['topic'], continuous)
            if hz is None:
                if not self.watch.advertised(c['topic']):
                    return False, 'not advertised'
                return None, 'measuring…'
            return hz >= c['min_hz'], f'{hz:.1f} Hz (need ≥{c["min_hz"]})'
        if kind == 'tf':
            age = self.watch.transform_age(c['parent'], c['child'])
            if age is None:
                return False, 'missing'
            if c.get('static'):
                return True, 'present'
            return age <= c['max_age'], f'{age:.2f} s old (max {c["max_age"]})'
        if kind == 'lifecycle':
            r = self.watch.trigger(c['service'])
            if r is None:
                return False, 'service not available'
            return r.success, 'active' if r.success else 'not active'
        if kind == 'subscribers':
            n = self.count_subscribers(c['topic'])
            return n >= c.get('min', 1), f'{n} subscriber(s)'
        if kind == 'node':
            ok = c['node'] in self.watch.node_names()
            return ok, 'running' if ok else 'not in graph'
        return False, f'unknown check type {kind}'

    @staticmethod
    def label(c):
        return {
            'mount': lambda: f'mount {c["path"]}', 'file': lambda: f'file {c["path"]}',
            'ping': lambda: f'ping {c["host"]}', 'topic_exists': lambda: c['topic'],
            'topic_rate': lambda: c['topic'], 'lifecycle': lambda: c['service'],
            'tf': lambda: f'TF {c["parent"]} → {c["child"]}',
            'subscribers': lambda: f'{c["topic"]} subscribers',
            'node': lambda: f'node {c["node"]}',
        }.get(c['type'], lambda: c['type'])()

    def evaluate(self, stage, checks=None, continuous=True):
        """Run a stage's checks and container states.

        True when everything passes, False when something failed, None when
        nothing failed but a measurement is still pending.
        """
        results = []
        for c in checks if checks is not None else stage.checks:
            try:
                ok, value = self.run_check(c, continuous)
            except Exception as e:  # a broken check must not kill the worker
                ok, value = False, f'check error: {e}'
            results.append({'label': self.label(c), 'ok': ok, 'value': value,
                            'hint': c.get('hint', '') if ok is False else ''})
        if checks is None and stage.components:
            names = self.watch.node_names()
            for c in stage.components:
                node = self.component_node(c)
                ok = node in names
                results.append({'label': f'node {node}', 'ok': ok,
                                'value': 'running' if ok else 'not in graph', 'hint': ''})
        containers = [self.docker.container_state(s) for s in stage.services]
        with self.lock:
            stage.results = results
            stage.containers = containers
        if any(r['ok'] is False for r in results):
            return False
        return None if any(r['ok'] is None for r in results) else True

    def dead_container(self, stage):
        for c in stage.containers:
            if c['status'] in ('exited', 'dead', 'absent', 'restarting'):
                return c
        return None

    def first_failure(self, stage):
        for r in stage.results:
            if r['ok'] is not True:
                hint = f' — {r["hint"]}' if r['hint'] else ''
                return f'{r["label"]}: {r["value"]}{hint}'
        return ''

    def grab_logs(self, stage):
        with self.lock:
            stage.logs = {c: self.docker.logs(c) for c in
                          (self.docker.container_of[s] for s in stage.services)}

    # ---- docker ------------------------------------------------------------

    def clear_conflicts(self, stage):
        """Fixed container_names collide with other copies of this repo (e.g. erc25)."""
        for s in stage.services:
            name = self.docker.container_of[s]
            info = self.docker.inspect(name)
            if info is None:
                continue
            project = (info['Config']['Labels'] or {}).get('com.docker.compose.project')
            if project == self.docker.project:
                continue
            if info['State']['Running']:
                return (f'{name} is running from another copy of the repo '
                        f'(compose project "{project}"); stop it there first')
            sh(['docker', 'rm', name], timeout=30)
            self.event('warn', f'removed stopped {name} left by project "{project}"')
        return None

    def start_services(self, stage):
        if not stage.services:
            return None
        conflict = self.clear_conflicts(stage)
        if conflict:
            return conflict
        rc, out = self.docker.compose('up', '-d', '--no-deps', '--no-build', *stage.services)
        if rc != 0:
            return f'docker compose up failed: {out.splitlines()[-1] if out else rc}'
        return None

    @staticmethod
    def component_node(c):
        ns = c.get('namespace', '').strip('/')
        return f'/{ns}/{c["name"]}' if ns else f'/{c["name"]}'

    def load_components(self, stage):
        for c in stage.components:
            req = LoadNode.Request()
            req.package_name, req.plugin_name, req.node_name = c['package'], c['plugin'], c['name']
            req.node_namespace = '/' + c.get('namespace', '').strip('/')  # must be absolute
            req.remap_rules = [f'{a}:={b}' for a, b in c.get('remaps', {}).items()]
            if 'params' in c:
                try:
                    req.parameters = params_from_yaml(
                        os.path.join(self.config_dir, c['params']), c['name'])
                except (OSError, yaml.YAMLError, TypeError) as e:
                    return f'parameters for {c["name"]}: {e}'
            # file_params: {param: path under src/} sets a string parameter to a file's
            # text, e.g. robot_description to the URDF
            for key, path in c.get('file_params', {}).items():
                try:
                    with open(os.path.join(WS_MOUNT, path)) as f:
                        req.parameters.append(Parameter(key, value=f.read()).to_parameter_msg())
                except OSError as e:
                    return f'{key} for {c["name"]}: {e}'
            req.extra_arguments = [Parameter('use_intra_process_comms',
                                             value=c.get('intra_process', False)).to_parameter_msg()]
            res = self.watch.call(LoadNode, f'{self.container}/_container/load_node', req,
                                  timeout=LOAD_TIMEOUT, wait=LOAD_TIMEOUT)
            if res is None:
                return f'{self.container} load service not available'
            if not res.success:
                return f'loading {c["plugin"]} failed: {res.error_message}'
            stage.loaded[c['name']] = res.unique_id
            self.event('info', f'{stage.title}: loaded {res.full_node_name}')
        return None

    def unload_components(self, stage):
        for name, uid in reversed(list(stage.loaded.items())):
            self.watch.call(UnloadNode, f'{self.container}/_container/unload_node',
                            UnloadNode.Request(unique_id=uid), timeout=10.0)
        stage.loaded.clear()

    def stop_services(self, stage):
        self.unload_components(stage)
        if stage.services:
            self.docker.compose('stop', '-t', '10', *stage.services, timeout=120)
            self.docker.compose('rm', '-f', *stage.services, timeout=60)

    # ---- actions -----------------------------------------------------------

    def worker(self):
        while True:
            try:
                action = self.actions.get(timeout=2.0)
            except queue.Empty:
                self.monitor()
                continue
            try:
                {'go': self.go, 'stop': self.stop_all}[action]()
            except Exception as e:
                self.event('error', f'{action} crashed: {e}')
                self.overall = 'failed'

    def go(self):
        """Start from the first required stage that isn't ready; leave earlier ones alone."""
        start = next((i for i, s in enumerate(self.stages)
                      if s.required and s.state != 'ready'), None)
        if start is None:
            self.event('info', 'everything already ready')
            return
        self.overall = 'bringing_up'
        if any(s.state != 'pending' for s in self.stages[start:]):
            self.event('info', f'recovering from stage "{self.stages[start].title}"')
            for s in reversed(self.stages[start:]):
                self.stop_services(s)
        for s in self.stages[start:]:
            with self.lock:
                s.reset()
        for i, stage in enumerate(self.stages[start:], start):
            if self.abort.is_set():
                self.event('warn', 'bringup aborted')
                return
            ok = self.bring_up(stage)
            if not ok and stage.required:
                with self.lock:
                    for later in self.stages[i + 1:]:
                        later.reset('blocked')
                        later.message = f'waiting for "{stage.title}"'
                self.overall = 'failed'
                return
        self.overall = 'ready'
        self.event('info', 'bringup complete')

    def bring_up(self, stage):
        with self.lock:
            stage.state = 'starting'
            stage.started_at = time.time()
            stage.message = ''
        self.event('info', f'{stage.title}: starting')

        if stage.pre and self.evaluate(stage, stage.pre) is not True:
            return self.fail(stage, self.first_failure(stage), grab=False)

        err = self.start_services(stage) or self.load_components(stage)
        if err:
            return self.fail(stage, err)

        deadline = time.monotonic() + stage.timeout
        while time.monotonic() < deadline:
            if self.abort.is_set():
                return False
            passed = self.evaluate(stage)
            dead = self.dead_container(stage)
            if dead:
                return self.fail(stage, f'container {dead["name"]} {dead["status"]} '
                                        f'(exit code {dead["exit_code"]})')
            if passed is True:
                with self.lock:
                    stage.state = 'ready'
                    stage.ready_at = time.time()
                    stage.message = f'ready after {stage.ready_at - stage.started_at:.0f} s'
                self.event('info', f'{stage.title}: {stage.message}')
                return True
            with self.lock:
                stage.message = (f'waiting ({int(deadline - time.monotonic())} s left): '
                                 f'{self.first_failure(stage)}')
            self.monitor(skip=stage)
            time.sleep(1.0)
        return self.fail(stage, f'timed out after {stage.timeout} s — {self.first_failure(stage)}')

    def fail(self, stage, reason, grab=True):
        if grab:
            self.grab_logs(stage)
        with self.lock:
            stage.state = 'failed' if stage.required else 'warn'
            stage.message = reason
        self.event('error' if stage.required else 'warn', f'{stage.title}: {reason}')
        return False

    def monitor(self, skip=None):
        """Re-check ready stages; a stage that keeps failing turns red."""
        for i, stage in enumerate(self.stages):
            if stage is skip or stage.state not in ('ready', 'warn'):
                continue
            ok = (self.evaluate(stage, continuous=False) is not False
                  and self.dead_container(stage) is None)
            if ok:
                stage.monitor_fails = 0
                if stage.state == 'warn':
                    with self.lock:
                        stage.state, stage.message = 'ready', 'recovered'
                continue
            stage.monitor_fails += 1
            if stage.monitor_fails < MONITOR_FAILS or stage.state == 'warn':
                continue
            dead = self.dead_container(stage)
            reason = (f'container {dead["name"]} {dead["status"]} (exit code {dead["exit_code"]})'
                      if dead else self.first_failure(stage))
            self.fail(stage, f'lost after ready: {reason}')
            if stage.required:
                self.overall = 'failed'
                with self.lock:
                    for later in self.stages[i + 1:]:
                        if later.state in ('ready', 'starting'):
                            later.message = f'upstream "{stage.title}" failed'

    def stop_all(self):
        self.overall = 'stopping'
        self.event('info', 'stopping all stages')
        for stage in reversed(self.stages):
            self.stop_services(stage)
            with self.lock:
                stage.reset('stopped' if stage.services else 'pending')
        self.overall = 'idle'
        self.abort.clear()
        self.event('info', 'all stopped')


def main():
    config = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        WS_MOUNT, 'app_bringup_manager', STAGES)
    rclpy.init()
    node = BringupManager(config)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    executor.spin()


if __name__ == '__main__':
    main()
