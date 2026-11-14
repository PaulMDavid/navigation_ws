"""Unit tests of app_teleop/nav_relay_core.py (no ROS)."""
import json
import math
import os
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.environ.get('APP_DIR', os.path.join(os.path.dirname(__file__), '../../src/app_teleop')))
import nav_relay_core as core  # noqa: E402


# ---- commands ---------------------------------------------------------------

def test_parse_goal():
    assert core.parse_cmd('{"cmd": "goal", "x": 1, "y": -2.5, "yaw": 0.3}') == \
        {'cmd': 'goal', 'x': 1.0, 'y': -2.5, 'yaw': 0.3}


@pytest.mark.parametrize('text', ['{"cmd": "cancel"}', '{"cmd": "bringup_go"}', '{"cmd": " BRINGUP_STOP "}'])
def test_parse_simple(text):
    assert core.parse_cmd(text)['cmd'] in core.NAV_COMMANDS


@pytest.mark.parametrize('text,why', [
    ('goal', 'not JSON'),
    ('[1, 2]', 'JSON object'),
    ('{"x": 1}', 'JSON object'),
    ('{"cmd": "fly"}', 'unknown cmd'),
    ('{"cmd": "goal", "x": 1, "y": 2}', 'yaw'),
    ('{"cmd": "goal", "x": "1", "y": 2, "yaw": 0}', 'x'),
    ('{"cmd": "goal", "x": true, "y": 2, "yaw": 0}', 'x'),
    ('{"cmd": "goal", "x": NaN, "y": 2, "yaw": 0}', 'x'),
])
def test_parse_bad(text, why):
    with pytest.raises(ValueError, match=why):
        core.parse_cmd(text)


# ---- yaw --------------------------------------------------------------------

@pytest.mark.parametrize('yaw', [0.0, 0.7, -1.2, math.pi / 2, 3.1])
def test_yaw_quat_roundtrip(yaw):
    q = core.yaw_to_quat(yaw)
    assert math.isclose(sum(v * v for v in q), 1.0)
    assert core.quat_to_yaw(*q) == pytest.approx(yaw)


def test_yaw_is_ccw_from_x():
    # +90 deg about +z: quaternion (0, 0, sin 45, cos 45)
    assert core.yaw_to_quat(math.pi / 2) == pytest.approx((0, 0, math.sqrt(0.5), math.sqrt(0.5)))


# ---- map --------------------------------------------------------------------

def test_small_map_not_downsampled_and_flipped():
    # 3 wide, 2 high; row 0 (lowest y): free, occupied, unknown; row 1: unknown, free, 50
    data = [0, 100, -1, -1, 0, 50]
    img, factor = core.downsample_grid(data, 3, 2, 1000)
    assert factor == 1 and img.shape == (2, 3) and img.dtype == np.uint8
    # image row 0 = highest y = grid row 1
    assert img[0].tolist() == [core.UNKNOWN, core.FREE, core.UNKNOWN]
    assert img[1].tolist() == [core.FREE, core.OCCUPIED, core.UNKNOWN]


def test_block_rule_occupied_then_free_then_unknown():
    g = np.full((4, 4), -1, np.int8)
    g[0, 0] = 0                    # block (0,0): one free cell -> free
    g[0, 2], g[1, 3] = 0, 100      # block (0,1): free + occupied -> occupied
    img, factor = core.downsample_grid(g.ravel().tolist(), 4, 4, 2)   # 2x2 blocks
    assert factor == 2 and img.shape == (2, 2)
    # bottom image row = grid blocks row 0
    assert img[1].tolist() == [core.FREE, core.OCCUPIED]
    assert img[0].tolist() == [core.UNKNOWN, core.UNKNOWN]


@pytest.mark.parametrize('w,h,size,factor,out', [
    (1000, 1000, 1000, 1, (1000, 1000)),
    (1001, 10, 1000, 2, (5, 501)),
    (2500, 1800, 1000, 3, (600, 834)),
    (4000, 4000, 1000, 4, (1000, 1000)),
])
def test_size_limit(w, h, size, factor, out):
    img, f = core.downsample_grid(np.zeros(w * h, np.int8), w, h, size)
    assert f == factor and img.shape == out and max(img.shape) <= size
    assert (img == core.FREE).all()     # padding is unknown, but every block has a free cell


def test_padding_is_unknown():
    img, f = core.downsample_grid([0] * 5, 5, 1, 2)   # factor 3: blocks [0..2], [3,4,pad]
    assert f == 3 and img.tolist() == [[core.FREE, core.FREE]]
    img, f = core.downsample_grid([0, 0, 0, 0, -1], 5, 1, 2)
    assert img.tolist() == [[core.FREE, core.FREE]]
    img, f = core.downsample_grid([0, 0, 0, -1, -1], 5, 1, 2)
    assert img.tolist() == [[core.FREE, core.UNKNOWN]]


def test_thresholds():
    img, _ = core.downsample_grid([25, 26, 64, 65], 4, 1, 1000)
    assert img.tolist() == [[core.FREE, core.UNKNOWN, core.UNKNOWN, core.OCCUPIED]]


def test_png_roundtrip_and_size():
    rng = np.random.default_rng(1)
    g = np.where(rng.random((1800, 2500)) < 0.02, 100, 0).astype(np.int8)
    g[:, :600] = -1
    img, _ = core.downsample_grid(g.ravel(), 2500, 1800, 1000)
    png = core.encode_png(img)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    back = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert back.shape == img.shape and back.dtype == np.uint8 and (back == img).all()
    assert len(png) < 1_000_000     # foxglove_bridge send_buffer_limit


# ---- plan -------------------------------------------------------------------

def test_path_short_unchanged():
    pts = [(i, 0) for i in range(5)]
    assert core.downsample_path(pts, 200) == pts


def test_path_downsampled_keeps_ends():
    pts = [(i * 0.05, 0.0) for i in range(1234)]
    out = core.downsample_path(pts, 200)
    assert len(out) == 200 and out[0] == pts[0] and out[-1] == pts[-1]
    xs = [p[0] for p in out]
    assert xs == sorted(xs)


def test_transform_2d():
    out = core.transform_2d([(1.0, 0.0)], 2.0, 3.0, math.pi / 2)
    assert out[0] == pytest.approx((2.0, 4.0))


# ---- bringup ----------------------------------------------------------------

def test_compact_bringup_drops_logs():
    status = {'stamp': 100.0, 'overall': 'failed', 'project': 'navbringup', 'events': [{'t': 1}],
              'stages': [{'name': 'slam', 'title': 'SLAM', 'state': 'failed', 'required': True,
                          'message': 'TF map → chassis_link: missing', 'services': ['a'],
                          'timeout': 60, 'started_at': 1, 'ready_at': None,
                          'checks': [{'label': 'TF', 'ok': False, 'value': 'missing', 'hint': 'h'}],
                          'containers': [{'name': 'x'}], 'logs': {'x': ['line'] * 200}}]}
    c = core.compact_bringup(status)
    assert c == {'overall': 'failed', 'stamp': 100.0, 'stages': [{
        'name': 'slam', 'title': 'SLAM', 'state': 'failed', 'required': True,
        'message': 'TF map → chassis_link: missing',
        'checks': [{'label': 'TF', 'ok': False, 'value': 'missing', 'hint': 'h'}]}]}
    json.dumps(c)
