"""scripts/record/record_drive.sh (+ `phone_ctl.sh record …`) with the fakes of
utils/phone_ctl/fakes: fake docker (containers = files, recorder = fakes/fake_recorder),
fake df/mountpoint. No ROS, no robot. The real recorder and probes: test_record_ros.py."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get('REPO', HERE.parent.parent))
FAKES = REPO / 'utils/phone_ctl/fakes'
RECORD = REPO / 'scripts/record/record_drive.sh'
PHONE_CTL = REPO / 'scripts/phone_ctl.sh'

# the 48 topics recorded in orintwo's drive_2026-11-14_130343 (its metadata.yaml)
BAG_2026_11_14 = '''
/state /zed2i/zed_node/right/color/rect/image/compressed /zed2i/zed_node/depth/camera_info /Motor_vel
/zed2i/zed_node/odom /zed2i/zed_node/pose /zed2i/zed_node/pose/status /zed2i/zed_node/left/color/rect/camera_info
/zed2i/zed_node/status/health /zed2i/zed_node/status/heartbeat /Motor_temp /odom_wheels
/forward_position_controller/commands /ekf/odometry_earth /rover_wheels_status /ekf/status
/ekf/dual_antenna_heading /gnss_1/velocity /gnss_2/llh_position /Motor_torq /gnss_2/velocity /imu/data
/gnss_1/llh_position /mip/ekf/status /nmea /rosout /diagnostics /forward_velocity_controller/commands
/zed2i/zed_node/rgb/color/rect/image/compressed /Motor_pos /mip/ekf/gnss_dual_antenna_status
/zed2i/zed2i_description /tf_static /teleop/state /rtcm /mip/gnss_1/rf_error_detection /mip/gnss_1/fix_info
/zed2i/zed_node/rgb/color/rect/camera_info /mip/gnss_corrections/rtk_corrections_status /tf
/mip/gnss_2/fix_info /cmd_vel /imu/data_raw /zed2i/zed_node/right/color/rect/camera_info
/mip/gnss_2/rf_error_detection /zed2i/zed_node/left/color/rect/image/compressed /zed2i/zed_node/imu/data
'''.split()
BAG_RE = re.compile(r'^drive_\d{4}-\d\d-\d\d_\d{6}$')


@pytest.fixture
def env(tmp_path):
    fake = tmp_path / 'fake'
    (fake / 'containers').mkdir(parents=True)
    (fake / 'containers/app_teleop_container').write_text('')
    bags = tmp_path / 'bags'
    bags.mkdir()
    e = {
        'PATH': f'{FAKES}:/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(tmp_path), 'FAKE': str(fake),
        'NAVWS_REPO': str(REPO), 'BAGS_DIR': str(bags), 'SSD_MOUNT': str(tmp_path),
        'RECORD_LOCK': str(tmp_path / 'record.lock'), 'PHONE_CTL_LOCK': str(tmp_path / 'phone_ctl.lock'),
        'PHONE_CTL_POLL': '0.2', 'SENSOR_TIMEOUT': '2', 'RECORD_SETTLE': '1', 'STATUS_PERIOD': '0.3',
        'STOP_TIMEOUT': '10',
    }
    yield e
    # stop whatever fake recorder is left
    for f in (fake / 'containers').iterdir():
        pid = f.read_text().strip()
        if pid:
            subprocess.run(['kill', '-KILL', '--', f'-{pid}'], capture_output=True)


def run(env, *args, via_phone=None, extra=None, timeout=60):
    e = dict(env, **(extra or {}))
    if via_phone is not None:
        e['SSH_ORIGINAL_COMMAND'] = via_phone
        cmd = ['bash', str(PHONE_CTL)]
    else:
        cmd = ['bash', str(RECORD), *args]
    p = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=timeout)
    lines = [json.loads(line) for line in p.stdout.splitlines()]   # every line must be JSON
    return p, lines


def check_format(lines):
    assert lines[-1] == {'done': True, 'ok': lines[-1]['ok']} and isinstance(lines[-1]['ok'], bool)
    ts = []
    for line in lines[:-1]:
        assert set(line) >= {'step', 'state', 'reason', 't'}, line
        assert line['state'] in ('running', 'ok', 'fail', 'warn', 'skipped')
        assert isinstance(line['reason'], str) and isinstance(line['t'], (int, float))
        ts.append(line['t'])
    assert ts == sorted(ts)


def final(lines):
    return {ln['step']: ln for ln in lines if 'step' in ln}


def fake(env, name, content=''):
    (Path(env['FAKE']) / name).write_text(content)


def ev_texts(env):
    f = Path(env['FAKE']) / 'events'
    return [ln.split(' ', 1)[1] for ln in f.read_text().splitlines()] if f.exists() else []


def recording(env):
    return (Path(env['FAKE']) / 'containers/rec_drive').exists()


def start(env, *args, **kw):
    p, lines = run(env, 'start', *(args or ('drive',)), **kw)
    check_format(lines)
    return p, lines


# ---------- presets ----------

def test_presets(env):
    p, lines = run(env, 'presets')
    check_format(lines)
    assert p.returncode == 0 and lines[-1]['ok']
    groups = {ln['group']['name']: ln['group'] for ln in lines if 'group' in ln}
    presets = {ln['preset']['name']: ln['preset'] for ln in lines if 'preset' in ln}
    assert set(presets) == {'drive', 'minimal', 'lidar'}
    assert [n for n, pr in presets.items() if pr['default']] == ['drive']
    for g in groups.values():
        assert isinstance(g['label'], str) and g['topics'] and all(t.startswith('/') for t in g['topics'])
    drive = presets['drive']['topics']
    assert set(BAG_2026_11_14) <= set(drive), set(BAG_2026_11_14) - set(drive)
    assert len(drive) == len(set(drive))
    for t in ('/robot_description', '/tf', '/tf_static', '/cmd_vel', '/teleop/state', '/odom_wheels'):
        assert t in drive
    assert not any('/ouster/' in t for t in drive)
    assert presets['lidar']['topics'] == drive + ['/ouster/points', '/ouster/imu']
    assert not any(t.endswith('/compressed') or 'camera_info' in t for t in presets['minimal']['topics'])
    assert set(presets['minimal']['topics']) < set(drive)
    # a topic is in one group only
    every = [t for g in groups.values() for t in g['topics']]
    assert len(every) == len(set(every))
    quiet = [ln['quiet_ok'] for ln in lines if 'quiet_ok' in ln][0]
    assert '/tf_static' in quiet and '/robot_description' in quiet


# ---------- start ----------

def test_start_ok(env):
    p, lines = start(env)
    assert p.returncode == 0 and lines[-1]['ok'], p.stdout + p.stderr
    f = final(lines)
    assert [s for s in f] == ['preflight', 'sensors', 'record']
    assert f['preflight']['state'] == 'ok' and f['preflight']['free_gb'] == 500.0
    assert f['sensors']['state'] == 'ok' and f['sensors']['silent'] == []
    r = f['record']
    assert r['state'] == 'ok' and BAG_RE.match(r['bag']) and r['preset'] == 'drive'
    assert r['subscribed'] == len(r['topics']) and set(BAG_2026_11_14) <= set(r['topics'])
    assert recording(env)
    ev = ev_texts(env)
    # ZED: the compose camera stopped before zed2i_rec starts; GQ7 started
    assert 'docker start app_microstrain_container' in ev
    assert 'docker start zed2i_rec' in ev
    assert not any(t == 'docker stop app_zed2i_camera' for t in ev), 'only stopped when running'
    probe = [t for t in ev if t.startswith('probe topics')]
    assert probe and '--window 8' in probe[0]
    for t in ('/imu/data', '/gnss_1/llh_position', '/odom_wheels',
              '/zed2i/zed_node/left/color/rect/image/compressed', '/zed2i/zed_node/right/color/rect/image/compressed'):
        assert t in probe[0]
    bags = Path(env['BAGS_DIR'])
    assert (bags / f'{r["bag"]}_record.topics').read_text().split() == r['topics']
    cur = (bags / '.record_current').read_text()
    assert f'bag={r["bag"]}' in cur and 'preset=drive' in cur


def test_start_docker_run_args(env):
    start(env)
    args = (Path(env['FAKE']) / 'run_args').read_text().splitlines()
    joined = ' '.join(args)
    for a in ('--rm', '--init', '--network host', '--ipc host', '--stop-signal SIGINT', '--name rec_drive',
              f'{REPO}/src/config/dds/cyclonedds.xml:/etc/cyclonedds.xml:ro', f'{env["BAGS_DIR"]}:/bags',
              f'{REPO}/scripts/record:/navws_record:ro', 'zed2i_rec:2026-11-14', 'ROS_DOMAIN_ID=0',
              'CYCLONEDDS_URI=file:///etc/cyclonedds.xml', 'RMW_IMPLEMENTATION=rmw_cyclonedds_cpp'):
        assert a in joined, a
    cmd = (Path(env['FAKE']) / 'run_cmd').read_text()
    for a in ('AMENT_PREFIX_PATH=/bags/.overlay_microstrain_msgs:', 'LD_LIBRARY_PATH=/bags/.overlay_microstrain_msgs/lib:',
              'ros2 bag record -o /bags/drive_', '-s sqlite3', '--compression-mode file', '--compression-format zstd',
              '--max-bag-size 2000000000', '--qos-profile-overrides-path /navws_record/qos_latched_overrides.yaml',
              'record_watch.py', '_record.log 2>&1'):
        assert a in cmd, a


def test_start_stops_compose_zed_first(env):
    fake(env, 'containers/app_zed2i_camera')
    start(env)
    ev = ev_texts(env)
    assert ev.index('docker stop app_zed2i_camera') < ev.index('docker start zed2i_rec')


def test_start_sensors_running_not_restarted(env):
    for c in ('app_microstrain_container', 'zed2i_rec'):
        fake(env, f'containers/{c}')
    start(env)
    assert not any(t.startswith('docker start') for t in ev_texts(env))


def test_start_refuses_when_recording(env):
    start(env)
    p, lines = start(env)
    f = final(lines)
    assert p.returncode == 1 and not lines[-1]['ok']
    assert f['preflight']['state'] == 'fail' and f['preflight']['reason'].startswith('already recording drive_')
    assert f['sensors']['state'] == 'skipped' and f['record']['state'] == 'skipped'
    assert sum(t.startswith('docker run') for t in ev_texts(env)) == 1


@pytest.mark.parametrize('avail,state', [(19_999_000_000, 'fail'), (20_000_000_000, 'ok')])
def test_start_free_space(env, avail, state):
    p, lines = start(env, extra={'FAKE_AVAIL': str(avail)})
    f = final(lines)
    assert f['preflight']['state'] == state, f['preflight']
    if state == 'fail':
        assert 'only 20.0 GB free' in f['preflight']['reason'] or 'only 19' in f['preflight']['reason']
        assert 'need 20' in f['preflight']['reason'] and not recording(env)
        assert not any(t.startswith('docker') for t in ev_texts(env)), 'nothing started'


def test_start_no_ssd(env):
    fake(env, 'no_ssd')
    _, lines = start(env)
    assert 'not mounted' in final(lines)['preflight']['reason'] and not recording(env)


def test_start_sensor_silent_warns_and_records(env):
    fake(env, 'silent_topics', '/odom_wheels\n')
    p, lines = start(env)
    f = final(lines)
    assert f['sensors']['state'] == 'warn' and f['sensors']['silent'] == ['/odom_wheels']
    assert 'recording anyway' in f['sensors']['reason']
    assert any(ln['state'] == 'running' and 'waiting for /odom_wheels' in ln['reason'] for ln in lines)
    assert f['record']['state'] == 'ok' and p.returncode == 0


def test_start_teleop_down_warns(env):
    (Path(env['FAKE']) / 'containers/app_teleop_container').unlink()
    _, lines = start(env)
    f = final(lines)
    assert f['sensors']['state'] == 'warn' and "can't check sensors (app_teleop not running)" in f['sensors']['reason']
    assert f['record']['state'] == 'ok'


def test_start_minimal_and_lidar_checks(env):
    _, lines = start(env, 'minimal')
    probe = [t for t in ev_texts(env) if t.startswith('probe topics')][0]
    assert '/zed2i/zed_node/imu/data' in probe and 'compressed' not in probe
    assert not any('compressed' in t or 'camera_info' in t for t in final(lines)['record']['topics'])
    run(env, 'stop')
    (Path(env['FAKE']) / 'events').unlink()
    _, lines = start(env, 'lidar')
    probe = [t for t in ev_texts(env) if t.startswith('probe topics')][0]
    assert '/ouster/points' in probe
    assert '/ouster/imu' in final(lines)['record']['topics']


def test_start_plus_minus_topics(env):
    _, lines = start(env, 'drive', '+/extra/topic', '-/rosout', '+/imu/data')
    t = final(lines)['record']['topics']
    assert t[-1] == '/extra/topic' and '/rosout' not in t and t.count('/imu/data') == 1


def test_start_via_phone_ctl(env):
    p, lines = run(env, via_phone='record start drive +/ouster/points,-/rosout')
    check_format(lines)
    t = final(lines)['record']['topics']
    assert p.returncode == 0 and '/ouster/points' in t and '/rosout' not in t


@pytest.mark.parametrize('args,msg', [
    ((), 'needs a preset'), (('nope',), 'unknown preset nope'), (('Drive',), 'bad preset name'),
    (('drive', 'imu'), 'bad topic argument'), (('drive', '+imu'), 'bad topic argument'),
    (('drive', '-/not/there'), 'not in the selection'), (('drive', '+/a//b'), 'bad topic argument'),
    (('drive', '+/a b'), 'bad topic argument'),
])
def test_start_refused_args(env, args, msg):
    p, lines = run(env, 'start', *args)
    check_format(lines)
    assert p.returncode == 64 and lines[0]['step'] == 'command' and msg in lines[0]['reason'], lines
    assert ev_texts(env) == []


@pytest.mark.parametrize('cmd', ['record start drive;id', 'record start drive +/a$(id)', 'record start drive "x"',
                                 'record stop &', 'UP', 'record start drive +/a|b'])
def test_phone_ctl_refuses_metachars(env, cmd):
    p, lines = run(env, via_phone=cmd)
    assert p.returncode == 64 and 'refused' in lines[0]['reason'], lines
    assert ev_texts(env) == []


@pytest.mark.parametrize('cmd,msg', [('record', 'unknown record verb'), ('record bogus', 'unknown record verb'),
                                     ('record stop now', 'takes no arguments'), ('record status x', "nothing or 'once'")])
def test_record_verb_refused(env, cmd, msg):
    p, lines = run(env, via_phone=cmd)
    assert p.returncode == 64 and msg in lines[0]['reason']


def test_start_recorder_crashes(env):
    _, lines = start(env, extra={'FAKE_REC_CRASH': '1'})
    r = final(lines)['record']
    assert r['state'] == 'fail' and 'recorder exited' in r['reason'] and 'no space left' in r['reason']
    assert not lines[-1]['ok']


def test_start_docker_run_fails(env):
    fake(env, 'run_fail')
    _, lines = start(env)
    assert final(lines)['record']['reason'].startswith('docker run failed: docker: Error')


def test_start_lock_busy(env):
    lockf = Path(env['RECORD_LOCK'])
    holder = subprocess.Popen(['flock', str(lockf), 'sleep', '5'])
    time.sleep(0.3)
    try:
        p, lines = start(env)
        assert p.returncode == 75 and lines[0]['reason'].startswith('busy')
        assert ev_texts(env) == []
    finally:
        holder.kill()


# ---------- status ----------

def test_status_not_recording(env):
    p, lines = run(env, 'status')
    check_format(lines)
    assert len(lines) == 2 and p.returncode == 0
    s = lines[0]
    assert s['step'] == 'status' and s['state'] == 'ok' and s['recording'] is False and s['bag'] is None
    assert s['reason'] == 'not recording' and s['unclosed'] == [] and isinstance(s['free_gb'], float)


def test_status_once_recording(env):
    rec = final(start(env)[1])['record']
    bag = rec['bag']
    time.sleep(1.5)
    p, lines = run(env, 'status', 'once', extra={'SILENT_WINDOW': '1'})
    check_format(lines)
    s = lines[0]
    assert len(lines) == 2 and s['state'] == 'ok', s
    assert s['recording'] is True and s['bag'] == bag and s['preset'] == 'drive'
    assert isinstance(s['elapsed_s'], int) and s['elapsed_s'] >= 1
    assert s['size_mb'] > 0 and s['rate_mbps'] > 0 and s['free_gb'] == 500.0
    assert s['left_h'] > 0 and s['input_mbps'] == 1.0
    assert s['topics'] == len(rec['topics'])
    assert s['silent'] == [] and s['unclosed'] == [] and s['unwatched'] == []
    assert s['reason'].startswith(f'recording {bag} 00:00:0')


def test_status_silent_topics(env):
    fake(env, 'silent_topics', '/zed2i/zed_node/left/color/rect/image/compressed\n/tf_static\n')
    start(env, extra={'SENSOR_TIMEOUT': '0'})
    time.sleep(1.2)
    p, lines = run(env, 'status', 'once', extra={'SILENT_WINDOW': '1'})
    s = lines[0]
    assert s['state'] == 'warn', s
    # /tf_static is latched (quiet_ok): never reported
    assert s['silent'] == ['/zed2i/zed_node/left/color/rect/image/compressed'], s
    assert 'no messages for 1 s: /zed2i/zed_node/left/color/rect/image/compressed' in s['reason']


def test_status_watch_starting(env):
    start(env)
    _, lines = run(env, 'status', 'once', extra={'SILENT_WINDOW': '600'})
    assert lines[0]['silent'] is None and lines[0]['state'] == 'ok' and 'topic watch starting' in lines[0]['reason']


def test_status_stream_and_end(env):
    start(env)
    _, lines = run(env, 'status', extra={'STATUS_MAX': '2'})
    check_format(lines)
    st = [ln for ln in lines if ln.get('step') == 'status']
    assert len(st) >= 4 and all(ln['recording'] for ln in st)
    # recording ends while streaming: last line says so, then done
    p = subprocess.Popen(['bash', str(RECORD), 'status'], env=dict(env, STATUS_MAX='30'),
                         stdout=subprocess.PIPE, text=True)
    time.sleep(1)
    run(env, 'stop')
    out, _ = p.communicate(timeout=20)
    lines = [json.loads(x) for x in out.splitlines()]
    check_format(lines)
    assert lines[-2]['recording'] is False and lines[-2]['bag'] is not None and lines[0]['recording'] is True


def test_status_unclosed(env):
    d = Path(env['BAGS_DIR']) / 'drive_2026-11-14_120000'
    d.mkdir()
    (d / 'drive_2026-11-14_120000_0.db3').write_text('x')
    (Path(env['BAGS_DIR']) / 'orbslam3_zed2i').mkdir()          # not a bag: no chunks
    closed = Path(env['BAGS_DIR']) / 'drive_2026-11-14_110000'
    closed.mkdir()
    (closed / 'x_0.db3.zstd').write_text('x')
    (closed / 'metadata.yaml').write_text('x')
    _, lines = run(env, 'status')
    s = lines[0]
    assert s['state'] == 'warn' and s['unclosed'] == ['drive_2026-11-14_120000']
    assert 'ros2 bag reindex -s sqlite3' in s['reason']


# ---------- stop ----------

def test_stop_ok(env):
    bag = final(start(env)[1])['record']['bag']
    time.sleep(1)
    p, lines = run(env, 'stop')
    check_format(lines)
    assert p.returncode == 0 and lines[-1]['ok']
    assert lines[0]['state'] == 'running' and 'SIGINT' in lines[0]['reason'] and lines[0]['bag'] == bag
    s = final(lines)['stop']
    assert s['state'] == 'ok' and s['bag'] == bag and s['size_mb'] > 0 and s['duration_s'] >= 1
    assert s['messages'] == 1234 and s['files'] == 1
    assert 'docker kill -s INT rec_drive' in ev_texts(env) and not recording(env)
    assert (Path(env['BAGS_DIR']) / bag / 'metadata.yaml').exists()
    # stop again: not recording, still ok
    p, lines = run(env, 'stop')
    assert lines[0]['state'] == 'ok' and lines[0]['reason'] == 'not recording' and p.returncode == 0


def test_stop_no_metadata(env):
    bag = final(start(env, extra={'FAKE_NO_METADATA': '1'})[1])['record']['bag']
    p, lines = run(env, 'stop')
    s = final(lines)['stop']
    assert s['state'] == 'fail' and p.returncode == 1
    assert f'ros2 bag reindex -s sqlite3 {env["BAGS_DIR"]}/{bag}' in s['reason']


def test_stop_timeout_does_not_kill(env):
    start(env, extra={'FAKE_CLOSE_DELAY': '6'})
    p, lines = run(env, 'stop', extra={'STOP_TIMEOUT': '1'})
    s = final(lines)['stop']
    assert s['state'] == 'fail' and 'still running after 1 s; not killed' in s['reason']
    assert recording(env)
    assert not any('KILL' in t for t in ev_texts(env))
    # a second stop waits for it
    p, lines = run(env, 'stop')
    assert final(lines)['stop']['state'] == 'ok'


# ---------- topics ----------

def test_topics(env):
    fake(env, 'probe_topics_lines',
         'topic {"name": "/imu/data", "type": "sensor_msgs/msg/Imu", "hz": 500.0, "mbps": 0.16}\n'
         'topic {"name": "/mip/ekf/status", "type": "microstrain_inertial_msgs/msg/MipFilterStatus", "hz": null, "mbps": null}\n')
    p, lines = run(env, 'topics')
    check_format(lines)
    t = [ln for ln in lines if 'topic' in ln]
    assert [x['reason'] for x in t] == ['/imu/data', '/mip/ekf/status']
    assert t[0]['topic'] == {'name': '/imu/data', 'type': 'sensor_msgs/msg/Imu', 'hz': 500.0, 'mbps': 0.16}
    assert t[1]['topic']['hz'] is None
    assert lines[-2]['count'] == 2 and p.returncode == 0
    assert any(x.startswith('probe topics --window 3') for x in ev_texts(env))


def test_topics_teleop_down(env):
    (Path(env['FAKE']) / 'containers/app_teleop_container').unlink()
    p, lines = run(env, 'topics')
    assert lines[-2]['state'] == 'fail' and 'app_teleop not running' in lines[-2]['reason'] and p.returncode == 1
