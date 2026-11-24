"""phone_ctl.sh + the rover's rover_wheels_ctl.sh / rover_wheels_run.sh, with fakes.

The fakes (fakes/) stand in for ssh, docker, ping, mountpoint, df, systemctl, ros2 and
mdtool. The fake ssh runs the real rover_wheels_ctl.sh, whose fake systemctl runs the
real rover_wheels_run.sh, whose fake `ros2 launch` holds a fake /dev/ttyACM0 open, so
the whole chain phone → orintwo → rover runs locally. No ROS, no robot.
"""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get('REPO', HERE.parent.parent))
PHONE_CTL = REPO / 'scripts/phone_ctl.sh'
ROVER = REPO / 'scripts/robot_setup/rover'
GAP = 0.4   # MDTOOL_GAP in the tests (3 s on the rover)


@pytest.fixture
def env(tmp_path):
    fake = tmp_path / 'fake'
    fake.mkdir()
    ws = tmp_path / 'wheels_ws/install'
    ws.mkdir(parents=True)
    (ws / 'setup.bash').write_text('')
    (tmp_path / 'ros_setup.bash').write_text('')
    (tmp_path / '.ssh').mkdir()
    e = {
        'PATH': f'{HERE / "fakes"}:/usr/bin:/bin:/usr/sbin:/sbin',
        'HOME': str(tmp_path), 'FAKE': str(fake), 'NAVWS_REPO': str(REPO),
        'PHONE_CTL_LOCK': str(tmp_path / 'phone_ctl.lock'), 'PHONE_CTL_POLL': '0.3',
        'MUX_TIMEOUT': '3', 'WHEELS_TIMEOUT': '20', 'CAMERA_TIMEOUT': '3',
        # rover side
        'ROVER_CTL': str(ROVER / 'rover_wheels_ctl.sh'), 'FAKE_RUNNER': str(ROVER / 'rover_wheels_run.sh'),
        'ROVER_WHEELS_ENV': str(tmp_path / 'none.env'), 'ROS_SETUP': str(tmp_path / 'ros_setup.bash'),
        'WHEELS_WS': str(tmp_path / 'wheels_ws'), 'WHEELS_LOG': str(tmp_path / 'wheels.log'),
        'WHEELS_STATE': str(tmp_path / 'wheels.state'), 'MD80_PORT': str(tmp_path / 'ttyACM0'),
        'MDTOOL_GAP': str(GAP), 'MD80_SETTLE': '1', 'MD80_QUIET': '2',
        'XDG_RUNTIME_DIR': str(tmp_path), 'CYCLONEDDS_URI': 'file:///bad.xml',
    }
    (tmp_path / 'ttyACM0').write_text('')
    yield e
    # stop whatever the fake systemctl left running
    subprocess.run([str(HERE / 'fakes/systemctl'), '--user', 'stop', 'rover-wheels.service'], env=e,
                   timeout=30, capture_output=True)


def run(env, *args, ssh_cmd=None, extra=None, timeout=60):
    e = dict(env, **(extra or {}))
    if ssh_cmd is not None:
        e['SSH_ORIGINAL_COMMAND'] = ssh_cmd
    p = subprocess.run(['bash', str(PHONE_CTL), *args], env=e, capture_output=True, text=True, timeout=timeout)
    lines = [json.loads(line) for line in p.stdout.splitlines()]   # every line must be JSON
    return p, lines


def fake(env, name, content=''):
    (Path(env['FAKE']) / name).write_text(content)


def events(env):
    f = Path(env['FAKE']) / 'events'
    out = []
    for line in (f.read_text().splitlines() if f.exists() else []):
        t, text = line.split(' ', 1)
        out.append((float(t), text))
    return out


def ev_texts(env):
    return [t for _, t in events(env)]


def final(env_lines):
    by = {}
    for line in env_lines:
        if 'step' in line:
            by[line['step']] = line
    return by


def check_format(lines):
    assert lines[-1] == {'done': True, 'ok': lines[-1]['ok']} and isinstance(lines[-1]['ok'], bool)
    ts = []
    for line in lines[:-1]:
        assert set(line) >= {'step', 'state', 'reason', 't'}, line
        assert line['state'] in ('running', 'ok', 'fail', 'warn', 'skipped')
        assert isinstance(line['reason'], str) and isinstance(line['t'], (int, float))
        ts.append(line['t'])
    assert ts == sorted(ts)


# ---------- up ----------

def test_up_all_green(env):
    p, lines = run(env, 'up')
    check_format(lines)
    assert lines[-1]['ok'] and p.returncode == 0, p.stdout + p.stderr
    f = final(lines)
    assert [s for s in f] == ['preflight', 'teleop', 'rover_link', 'wheels']
    assert all(f[s]['state'] == 'ok' for s in f), f
    # each step: a running line first, then its result
    assert [ln['state'] for ln in lines if ln.get('step') == 'preflight'] == ['running', 'ok']
    assert 'MD80 11 12 13 14 added' in f['wheels']['reason']
    assert 'rover_arming reset' in f['wheels']['reason']
    ev = ev_texts(env)
    assert 'compose up app_teleop app_foxglove_bridge app_rover_arming app_nav_relay TELEOP_SOURCE=phone cwd=src' in ev
    assert 'probe rover_cmd reset --timeout 5' in ev
    # issue #49: Cyclone pinned by the rover's own XML, never the inherited/bashrc one
    xml = ROVER / 'cyclonedds_rover.xml'
    assert f'dds RMW=rmw_cyclonedds_cpp DOMAIN=0 URI=file://{xml}' in ev, ev


def test_up_ssh_options(env):
    run(env, 'up')
    first = (Path(env['FAKE']) / 'ssh.log').read_text().splitlines()[0]
    for opt in ('BatchMode=yes', 'IdentitiesOnly=yes', 'ConnectTimeout=5', 'StrictHostKeyChecking=accept-new'):
        assert opt in first
    assert f'-i {env["HOME"]}/.ssh/navws_rover_ed25519' in first
    assert first.endswith('rover@192.168.1.230 status')


def test_up_stops_at_first_failure_preflight(env):
    fake(env, 'no_ssd')
    p, lines = run(env, 'up')
    check_format(lines)
    f = final(lines)
    assert f['preflight']['state'] == 'fail' and '/mnt/ssd not mounted' in f['preflight']['reason']
    assert [f[s]['state'] for s in ('teleop', 'rover_link', 'wheels')] == ['skipped'] * 3
    assert all(f[s]['reason'] == 'preflight failed' for s in ('teleop', 'rover_link', 'wheels'))
    assert not lines[-1]['ok'] and p.returncode == 1
    assert ev_texts(env) == [], 'nothing may start after a failed step'


def test_up_stops_at_first_failure_rover_link(env):
    fake(env, 'ping_fail')
    _, lines = run(env, 'up')
    f = final(lines)
    assert f['teleop']['state'] == 'ok'
    assert f['rover_link']['state'] == 'fail' and "doesn't answer ping" in f['rover_link']['reason']
    assert f['wheels']['state'] == 'skipped'
    assert not any(t.startswith('systemctl') for t in ev_texts(env))


def test_up_ssh_fails(env):
    fake(env, 'ssh_fail')
    _, lines = run(env, 'up')
    f = final(lines)
    assert f['rover_link']['state'] == 'fail' and 'Connection timed out' in f['rover_link']['reason']


@pytest.mark.parametrize('pct,state', [(94, 'ok'), (95, 'warn'), (99, 'warn'), (100, 'fail')])
def test_preflight_root_full(env, pct, state):
    _, lines = run(env, 'up', extra={'FAKE_DF': str(pct)})
    f = final(lines)
    assert f['preflight']['state'] == state and f'{pct} %' in f['preflight']['reason']
    # warn does not stop `up`
    assert f['teleop']['state'] == ('skipped' if state == 'fail' else 'ok')


def test_teleop_wrong_source(env):
    fake(env, 'probe_mux_source', 'ok ground')
    _, lines = run(env, 'up')
    f = final(lines)
    assert f['teleop']['state'] == 'fail' and 'source is ground' in f['teleop']['reason']
    assert f['wheels']['state'] == 'skipped'


def test_teleop_compose_fails(env):
    fake(env, 'compose_fail')
    _, lines = run(env, 'up')
    assert final(lines)['teleop']['reason'] == 'compose up failed: Error response from daemon: boom'


def test_up_twice_keeps_running_wheels(env):
    run(env, 'up')
    n_launch = Path(env['FAKE'], 'launches').read_text().strip()
    Path(env['FAKE'], 'events').unlink()
    _, lines = run(env, 'up')
    f = final(lines)
    assert f['wheels']['state'] == 'ok' and f['wheels']['reason'].startswith('already running')
    assert Path(env['FAKE'], 'launches').read_text().strip() == n_launch
    assert not any(t.startswith('probe rover_cmd') for t in ev_texts(env)), 'no reset if not restarted'


def test_wheels_reset_fails(env):
    fake(env, 'probe_rover_cmd', 'fail nobody listens on /teleop/phone/rover_cmd')
    _, lines = run(env, 'up')
    w = final(lines)['wheels']
    assert w['state'] == 'fail' and 'reset failed: nobody listens' in w['reason']


def test_wheels_no_subscriber(env):
    fake(env, 'probe_subs', 'fail no subscriber on /joy')
    _, lines = run(env, 'up', extra={'WHEELS_TIMEOUT': '3'})
    w = final(lines)['wheels']
    assert w['state'] == 'fail' and 'no subscriber on /joy' in w['reason']


# ---------- MD80 retry ----------

def test_md80_retry_recovers(env):
    p, lines = run(env, 'up', extra={'FAKE_FAIL_LAUNCHES': '1', 'FAKE_FAIL_ID': '12'})
    check_format(lines)
    f = final(lines)
    assert f['wheels']['state'] == 'ok', p.stdout
    retry = [ln for ln in lines if ln.get('step') == 'wheels' and ln['reason'].startswith('retry')]
    assert retry and retry[0]['reason'].startswith('retry 1/3: MD80 12 failed to add')
    ev = events(env)
    texts = [t for _, t in ev]
    assert texts.count('mdtool encoder 12') == 1
    assert not any('PORT-BUSY' in t for t in texts), texts
    # launch 1 stopped, gap, mdtool, gap, launch 2
    t = {txt: tt for tt, txt in ev}
    assert t['launch 1 stop'] < t['mdtool encoder 12'] < t['launch 2 start']
    assert t['mdtool encoder 12'] - t['launch 1 stop'] >= GAP
    assert t['launch 2 start'] - t['mdtool encoder interrupted'] >= GAP - 0.05
    log = Path(env['WHEELS_LOG']).read_text()
    assert 'Failed to add MD80 with ID: 12' in log and '### rover-wheels: attempt 2' in log


def test_md80_retry_gives_up(env):
    p, lines = run(env, 'up', extra={'FAKE_FAIL_LAUNCHES': '99', 'WHEELS_TIMEOUT': '60'}, timeout=90)
    w = final(lines)['wheels']
    assert w['state'] == 'fail' and w['reason'] == 'MD80 11 failed to add after 3 retries', p.stdout
    assert Path(env['FAKE'], 'launches').read_text().strip() == '4'   # first launch + 3 retries
    texts = ev_texts(env)
    assert texts.count('mdtool encoder 11') == 3
    assert not any('PORT-BUSY' in t for t in texts)
    retries = [ln['reason'][:9] for ln in lines if ln.get('step') == 'wheels' and ln['reason'].startswith('retry')]
    assert retries == ['retry 1/3', 'retry 2/3', 'retry 3/3']
    st = subprocess.run([env['ROVER_CTL'], 'status'], env=env, capture_output=True, text=True).stdout
    assert 'phase=gave_up' in st and 'failed_id=11' in st and 'active=failed' in st


def test_wheels_quiet_log_is_warn(env):
    _, lines = run(env, 'up', extra={'FAKE_NO_ADDED': '1'})
    f = final(lines)
    assert f['wheels']['state'] == 'warn' and "no 'Added MD80' lines" in f['wheels']['reason']
    assert lines[-1]['ok']


def test_wheels_launch_crash(env):
    _, lines = run(env, 'up', extra={'FAKE_NO_ADDED': '1', 'FAKE_EXIT_AFTER': '0.5'})
    w = final(lines)['wheels']
    assert w['state'] == 'fail' and 'launch exited' in w['reason']


def test_rover_start_refuses_when_port_held(env):
    holder = subprocess.Popen(['bash', '-c', f'exec 3<>{env["MD80_PORT"]}; sleep 30'])
    try:
        time.sleep(0.3)
        _, lines = run(env, 'up')
        w = final(lines)['wheels']
        assert w['state'] == 'fail' and 'held by' in w['reason'] and 'tmux' in w['reason']
        assert not any(t.startswith('launch') for t in ev_texts(env))
    finally:
        holder.kill()


# ---------- zero ----------

def test_zero_sequence(env):
    run(env, 'up')
    Path(env['FAKE'], 'events').unlink()
    p, lines = run(env, ssh_cmd='zero 14 11')
    check_format(lines)
    f = final(lines)
    assert lines[-1]['ok'], p.stdout
    assert [f[s]['state'] for s in ('rover_link', 'zero', 'wheels')] == ['ok', 'ok', 'ok']
    assert 'rover_arming reset' in f['wheels']['reason']
    ev = events(env)
    seq = [t for _, t in ev if t.startswith(('systemctl', 'mdtool', 'launch'))]
    assert seq == ['systemctl stop', 'launch 1 stop',
                   'mdtool config zero 14', 'mdtool config save 14',
                   'mdtool config zero 11', 'mdtool config save 11',
                   'systemctl start', 'launch 2 start'], seq
    md = [tt for tt, t in ev if t.startswith('mdtool')]
    stop = next(tt for tt, t in ev if t == 'launch 1 stop')
    assert md[0] - stop >= GAP
    assert all(b - a >= GAP for a, b in zip(md, md[1:]))
    zero_lines = [ln['reason'] for ln in lines if ln.get('step') == 'zero' and ln['state'] == 'running']
    assert any('mdtool config save 11 ok' in r for r in zero_lines)


def test_zero_mdtool_fails_restarts_wheels(env):
    run(env, 'up')
    p, lines = run(env, ssh_cmd='zero 12 13', extra={'FAKE_MDTOOL_FAIL': 'config save 12'})
    f = final(lines)
    assert f['zero']['state'] == 'fail' and 'mdtool config save 12 failed' in p.stdout
    assert f['wheels']['state'] == 'ok'          # controller back even after the failure
    texts = ev_texts(env)
    assert 'mdtool config zero 13' not in texts
    assert texts[-1].startswith('launch') or 'systemctl start' in texts
    assert not lines[-1]['ok']


# ---------- command parsing ----------

REFUSED = ['', '   ', 'upp', 'UP', 'up now', 'up; rm -rf /', 'up && id', '$(id)', 'status|cat',
           'zero', 'zero 10', 'zero 11 15', 'zero 11;ls', 'zero -1', 'zero 011', 'log', 'log foo',
           'log wheels extra', 'stop 1', 'camera on', 'rm', '../phone_ctl.sh up', "up'"]


@pytest.mark.parametrize('cmd', REFUSED)
def test_refused(env, cmd):
    p, lines = run(env, ssh_cmd=cmd)
    check_format(lines)
    assert len(lines) == 2 and lines[0]['step'] == 'command' and lines[0]['state'] == 'fail'
    assert lines[0]['reason'].startswith('refused')
    assert p.returncode == 64 and not lines[-1]['ok']
    assert ev_texts(env) == [] and not Path(env['FAKE'], 'ssh.log').exists()


def test_ssh_command_wins_over_args(env):
    p, lines = run(env, 'up', ssh_cmd='log foo')
    assert lines[0]['reason'].startswith('refused')


def test_commas_and_duplicates(env):
    run(env, 'up')
    p, lines = run(env, ssh_cmd='zero 11,11, 12')
    assert lines[-1]['ok'], p.stdout
    texts = ev_texts(env)
    assert texts.count('mdtool config zero 11') == 1 and 'mdtool config zero 12' in texts


@pytest.mark.parametrize('cmd', ['zero 15', 'zero 11 x', 'start now', 'reboot', 'status; id', ''])
def test_rover_ctl_refused(env, cmd):
    p = subprocess.run([env['ROVER_CTL']], env=dict(env, SSH_ORIGINAL_COMMAND=cmd),
                       capture_output=True, text=True)
    assert p.returncode == 64 and p.stdout.startswith('error: refused')
    assert ev_texts(env) == []


# ---------- status / stop / camera / log ----------

def test_status_starts_nothing(env):
    p, lines = run(env, 'status')
    check_format(lines)
    f = final(lines)
    assert f['teleop']['state'] == 'fail' and 'not running' in f['teleop']['reason']
    assert f['wheels']['state'] == 'fail' and f['camera']['state'] == 'skipped'
    assert not any(t.startswith(('compose up', 'systemctl start')) for t in ev_texts(env))
    run(env, 'up')
    _, lines = run(env, 'status')
    f = final(lines)
    assert [f[s]['state'] for s in ('preflight', 'teleop', 'rover_link', 'wheels', 'camera')] == \
        ['ok', 'ok', 'ok', 'ok', 'skipped']
    assert lines[-1]['ok']


def test_stop(env):
    run(env, 'up')
    run(env, 'camera')
    p, lines = run(env, 'stop')
    check_format(lines)
    assert [ln['step'] for ln in lines if ln.get('state') == 'ok'] == ['wheels', 'camera', 'teleop']
    ev = ev_texts(env)
    assert 'compose stop app_zed2i_camera app_teleop_camera TELEOP_SOURCE= cwd=src' in ev
    assert 'compose stop app_rover_arming app_nav_relay TELEOP_SOURCE= cwd=src' in ev
    c = Path(env['FAKE'], 'containers')
    assert (c / 'app_teleop_container').exists() and (c / 'app_foxglove_bridge_container').exists()
    assert not (c / 'app_rover_arming_container').exists()
    assert 'active=inactive' in subprocess.run([env['ROVER_CTL'], 'status'], env=env,
                                               capture_output=True, text=True).stdout


def test_stop_continues_after_failure(env):
    fake(env, 'ssh_fail')
    _, lines = run(env, 'stop')
    f = final(lines)
    assert f['wheels']['state'] == 'fail' and f['camera']['state'] == 'ok' and f['teleop']['state'] == 'ok'
    assert not lines[-1]['ok']


@pytest.mark.parametrize('hz,state', [('9.9', 'ok'), ('4.0', 'warn')])
def test_camera(env, hz, state):
    run(env, 'up')
    fake(env, 'probe_rate', f'ok {hz}')
    _, lines = run(env, 'camera')
    c = final(lines)['camera']
    assert c['state'] == state and hz in c['reason']
    assert 'compose up app_zed2i_camera app_teleop_camera TELEOP_SOURCE= cwd=src' in ev_texts(env)
    assert 'probe rate /teleop/camera/compressed --phone --window 3 --timeout 10' in ev_texts(env)


def test_camera_no_image(env):
    run(env, 'up')
    fake(env, 'probe_rate', 'fail no message on /teleop/camera/compressed within 10 s')
    _, lines = run(env, 'camera')
    c = final(lines)['camera']
    assert c['state'] == 'fail' and c['reason'].startswith('no image after 3 s')


def test_log_wheels(env):
    run(env, 'up')
    _, lines = run(env, ssh_cmd='log wheels')
    check_format(lines)
    body = [ln['reason'] for ln in lines[:-1]]
    assert all(ln['log'] is True and ln['step'] == 'wheels' for ln in lines[:-1])
    assert any('Added MD80 with ID: 14' in r for r in body)
    assert len(body) <= 50


def test_log_escaping(env):
    run(env, 'up')
    _, lines = run(env, ssh_cmd='log teleop')
    body = [ln['reason'] for ln in lines[:-1]]
    assert '== app_teleop_container ==' in body
    line = next(r for r in body if r.startswith('log of app_teleop_container'))
    assert '"quoted" back\\slash' in line and '\tend' in line and '\x1b' not in line


def test_lock_busy(env):
    holder = subprocess.Popen(['flock', env['PHONE_CTL_LOCK'], 'sleep', '30'])
    try:
        time.sleep(0.3)
        p, lines = run(env, 'up')
        assert lines[0]['reason'].startswith('busy') and p.returncode == 75
        # status and log don't need the lock
        _, lines = run(env, 'status')
        assert 'preflight' in final(lines)
    finally:
        holder.send_signal(signal.SIGTERM)


def test_zero_without_teleop_says_why(env):
    # wheels come back, but the subscriber check / reset need app_teleop: red with that reason
    _, lines = run(env, ssh_cmd='zero 11', extra={'WHEELS_TIMEOUT': '4'})
    f = final(lines)
    assert f['zero']['state'] == 'ok'
    assert f['wheels']['state'] == 'fail' and 'app_teleop not running' in f['wheels']['reason']
