"""nav_relay's pure parts (no ROS), so they can be unit-tested: command parsing, map
downsampling + PNG encoding, plan downsampling, yaw <-> quaternion, the compact copy of
/bringup/status. The message formats are documented in README.md ("Autonav relay")."""
import json
import math

import numpy as np

# PNG grey values, as map_server writes trinary maps (and RViz shows them)
FREE, OCCUPIED, UNKNOWN = 254, 0, 205
NAV_COMMANDS = ('goal', 'cancel', 'bringup_go', 'bringup_stop')


def parse_cmd(text):
    """`/teleop/phone/nav_cmd` JSON -> dict. Raises ValueError with the reason."""
    try:
        cmd = json.loads(text)
    except ValueError:
        raise ValueError(f'not JSON: {text[:80]!r}') from None
    if not isinstance(cmd, dict) or not isinstance(cmd.get('cmd'), str):
        raise ValueError('expected a JSON object with a "cmd" string')
    name = cmd['cmd'].strip().lower()
    if name not in NAV_COMMANDS:
        raise ValueError(f'unknown cmd {name!r}')
    out = {'cmd': name}
    if name == 'goal':
        for k in ('x', 'y', 'yaw'):
            v = cmd.get(k)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f'goal needs finite numbers x, y, yaw; {k} = {v!r}')
            out[k] = float(v)
    return out


def yaw_to_quat(yaw):
    """Rotation about +z (REP-103: CCW from +x) -> (x, y, z, w)."""
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def quat_to_yaw(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def downsample_grid(data, width, height, max_size, occupied_thresh=65, free_thresh=25):
    """OccupancyGrid data (row-major, row 0 = lowest y) -> (image, factor).

    Each cell becomes free (0..free_thresh), occupied (>= occupied_thresh) or unknown
    (-1 and everything between). Blocks of factor x factor cells, factor =
    ceil(max(width, height) / max_size), reduce to one pixel: occupied if any cell is,
    else free if any cell is, else unknown. The grid is padded with unknown on the +x / +y
    side to a multiple of factor, so the origin stays where it was.

    image: uint8, shape (ceil(height/factor), ceil(width/factor)), FREE / OCCUPIED /
    UNKNOWN, rows flipped: image row 0 is the highest y (a north-up picture when the
    map's +y is north).
    """
    grid = np.asarray(data, dtype=np.int16).reshape(height, width)
    factor = max(1, math.ceil(max(width, height) / max_size))
    h, w = math.ceil(height / factor), math.ceil(width / factor)
    occ = np.zeros((h * factor, w * factor), bool)
    free = np.zeros_like(occ)
    occ[:height, :width] = grid >= occupied_thresh
    free[:height, :width] = (grid >= 0) & (grid <= free_thresh)
    occ = occ.reshape(h, factor, w, factor).any(axis=(1, 3))
    free = free.reshape(h, factor, w, factor).any(axis=(1, 3))
    img = np.full((h, w), UNKNOWN, np.uint8)
    img[free] = FREE
    img[occ] = OCCUPIED
    return np.ascontiguousarray(img[::-1]), factor


def encode_png(img):
    import cv2  # only the node needs it; the unit tests decode with it too
    ok, buf = cv2.imencode('.png', img, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        raise RuntimeError('PNG encoding failed')
    return buf.tobytes()


def downsample_path(points, max_points):
    """Evenly spaced subset of `points`, at most max_points, first and last kept."""
    n = len(points)
    if n <= max_points:
        return list(points)
    if max_points < 2:
        return [points[-1]]
    idx = np.linspace(0, n - 1, max_points).round().astype(int)
    return [points[i] for i in idx]


def transform_2d(points, tx, ty, yaw):
    """Apply the planar transform (tx, ty, yaw) to [(x, y), ...]."""
    c, s = math.cos(yaw), math.sin(yaw)
    return [(tx + c * x - s * y, ty + s * x + c * y) for x, y in points]


def compact_bringup(status):
    """/bringup/status JSON -> what the phone needs: overall, stages and their checks.
    Drops logs, events, containers and services (large, and the app has no use for them)."""
    return {
        'overall': status.get('overall'),
        'stamp': status.get('stamp'),
        'stages': [{
            'name': s.get('name'), 'title': s.get('title'), 'state': s.get('state'),
            'required': s.get('required'), 'message': s.get('message'),
            'checks': [{'label': c.get('label'), 'ok': c.get('ok'), 'value': c.get('value'),
                        'hint': c.get('hint')} for c in s.get('checks') or []],
        } for s in status.get('stages') or []],
    }
