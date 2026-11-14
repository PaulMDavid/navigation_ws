"""Unit tests of rover_tracker.py: press sequencing, idempotent steering, source gating,
reset, queueing and the /teleop/rover_state fields. No ROS needed."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.environ.get('APP_DIR', os.path.join(os.path.dirname(__file__), '../../src/app_teleop')))
from rover_tracker import BOOT, N_BUTTONS, RoverTracker, buttons  # noqa: E402

GAP = 0.2


def run(tracker, t0=0.0, until=10.0, dt=0.01):
    """Step the tracker on a fake clock; returns [(t, event), ...]."""
    out, t = [], t0
    while t <= until:
        out += [(round(t, 3), e) for e in tracker.step(t)]
        t += dt
    return out


def joys(events):
    return [(t, e[1]) for t, e in events if e[0] == 'joy']


def pressed(events):
    """Buttons pressed, in order (all-zero messages left out)."""
    return [b.index(1) for _, b in joys(events) if any(b)]


def fresh(cmds, source='phone', active='phone'):
    tr = RoverTracker(gap=GAP)
    for c in cmds:
        assert tr.submit(c, source, active) is None
    return tr


def test_joy_message_shape():
    assert len(buttons()) == N_BUTTONS == 17
    assert buttons(16) == [0] * 16 + [1]
    assert sum(buttons()) == 0


@pytest.mark.parametrize('cmd,presses,state', [
    ('input_auto', [1], {'input': 'autonomous', 'steering': 'crab', 'motion': 'stopped'}),
    ('steer_ackermann', [16], {'input': 'manual', 'steering': 'ackermann', 'motion': 'stopped'}),
    ('steer_crab', [], BOOT),
    ('resume', [2], {'input': 'manual', 'steering': 'crab', 'motion': 'running'}),
    ('arm', [1, 16, 2], {'input': 'autonomous', 'steering': 'ackermann', 'motion': 'running'}),
    ('reset', [], BOOT),
])
def test_each_command_from_boot(cmd, presses, state):
    tr = fresh([cmd])
    ev = run(tr)
    assert pressed(ev) == presses
    assert tr.state == state
    assert tr.presses == len(presses)


def test_every_press_followed_by_all_zero():
    ev = joys(run(fresh(['arm'])))
    assert len(ev) == 6
    for i, (_, b) in enumerate(ev):
        assert len(b) == 17
        assert any(b) == (i % 2 == 0)      # press, zero, press, zero, ...


def test_gap_between_messages():
    ev = joys(run(fresh(['arm', 'steer_crab'])))
    times = [t for t, _ in ev]
    assert times[0] == 0.0
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= GAP - 1e-9
    assert max(gaps) < GAP + 0.02          # 10 ms clock steps


def test_steer_idempotent():
    tr = fresh(['steer_ackermann', 'steer_ackermann', 'steer_ackermann'])
    assert pressed(run(tr)) == [16]
    assert tr.state['steering'] == 'ackermann'
    for c in ('steer_crab', 'steer_crab'):
        tr.submit(c, 'phone', 'phone')
    assert pressed(run(tr, 20, 30)) == [16]
    assert tr.state['steering'] == 'crab'


def test_arm_when_already_ackermann_skips_16():
    tr = fresh(['steer_ackermann', 'arm'])
    assert pressed(run(tr)) == [16, 1, 2]
    assert tr.state == {'input': 'autonomous', 'steering': 'ackermann', 'motion': 'running'}
    assert tr.last_cmd == 'arm' and tr.presses == 2


def test_arm_twice_does_not_toggle_back():
    tr = fresh(['arm', 'arm'])
    assert pressed(run(tr)) == [1, 16, 2, 1, 2]
    assert tr.state['steering'] == 'ackermann'


def test_steering_events_for_max_angular():
    tr = fresh(['arm', 'steer_ackermann', 'steer_crab', 'reset'])
    steer = [e[1] for _, e in run(tr) if e[0] == 'steering']
    # every command that decides steering re-sends the limit, also without a press
    assert steer == ['ackermann', 'ackermann', 'crab', 'crab']


def test_steering_event_right_after_its_press():
    ev = run(fresh(['arm']))
    kinds = [(e[0], e[1].index(1) if e[0] == 'joy' and any(e[1]) else None) for _, e in ev]
    i16 = kinds.index(('joy', 16))
    assert kinds[i16 + 1] == ('steering', None)


def test_queued_not_interleaved():
    tr = fresh(['arm'])
    run(tr, 0.0, 0.25)                     # mid-sequence: press 1 + its zero sent
    assert tr.submit('steer_crab', 'phone', 'phone') is None
    ev = run(tr, 0.26, 10)
    assert pressed(ev) == [16, 2, 16]      # arm finishes first, then crab toggles
    assert tr.state['steering'] == 'crab'


def test_source_gating():
    tr = RoverTracker(gap=GAP)
    r = tr.submit('arm', 'ground', 'phone')
    assert r and 'active source is phone' in r
    assert tr.rejected == r
    assert not tr.busy()
    assert tr.submit('arm', 'phone', None) and 'unknown' in tr.rejected
    assert tr.submit('fly', 'phone', 'phone') and 'unknown command' in tr.rejected
    assert run(tr) == []
    assert tr.state == BOOT
    # an accepted command clears `rejected`
    assert tr.submit('arm', 'ground', 'ground') is None
    assert tr.rejected is None


def test_reset_after_states():
    tr = fresh(['arm', 'reset'])
    run(tr)
    assert tr.state == BOOT
    assert tr.last_cmd == 'reset' and tr.presses == 0
    # after reset steering is crab again, so ackermann presses 16
    tr.submit('steer_ackermann', 'phone', 'phone')
    assert pressed(run(tr, 20, 30)) == [16]


def test_queue_limit():
    tr = RoverTracker(gap=GAP, max_queue=2)
    assert tr.submit('arm', 'phone', 'phone') is None
    assert tr.submit('arm', 'phone', 'phone') is None
    assert 'queued' in tr.submit('arm', 'phone', 'phone')


def test_report_json():
    tr = RoverTracker(gap=GAP)
    r = tr.report(0.0)
    assert r == {'tracked': True, 'input': 'manual', 'steering': 'crab', 'motion': 'stopped',
                 'last_cmd': None, 'last_cmd_age': None, 'last_cmd_by': None,
                 'presses': 0, 'rejected': None}
    tr.submit('arm', 'phone', 'phone')
    run(tr, 5.0, 7.0)
    r = json.loads(json.dumps(tr.report(8.2)))
    assert r['last_cmd'] == 'arm' and r['last_cmd_by'] == 'phone'
    assert r['last_cmd_age'] == pytest.approx(3.2)
    assert r['presses'] == 3
    assert (r['input'], r['steering'], r['motion']) == ('autonomous', 'ackermann', 'running')
    tr.submit('resume', 'ground', 'phone')
    assert 'active source is phone' in tr.report(9)['rejected']
