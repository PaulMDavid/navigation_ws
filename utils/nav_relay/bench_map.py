"""Time nav_relay's map work (downsample + PNG) for a few map sizes. No ROS.
Run: ./run.sh bench"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get('APP_DIR', os.path.join(os.path.dirname(__file__), '../../src/app_teleop')))
import nav_relay_core as core  # noqa: E402

rng = np.random.default_rng(0)
for w, h in ((800, 600), (2000, 2000), (2500, 1800), (4000, 4000)):
    g = np.full((h, w), -1, np.int8)
    y0, x0 = h // 8, w // 8
    g[y0:h - y0, x0:w - x0] = np.where(rng.random((h - 2 * y0, w - 2 * x0)) < 0.03, 100, 0)
    data = g.ravel()
    ts = []
    for _ in range(5):
        t0 = time.perf_counter()
        img, f = core.downsample_grid(data, w, h, 1000)
        png = core.encode_png(img)
        ts.append(time.perf_counter() - t0)
    print(f'{w}x{h} -> {img.shape[1]}x{img.shape[0]} (x{f}): {len(png) / 1024:.0f} KiB PNG, '
          f'median {sorted(ts)[2] * 1e3:.0f} ms')
