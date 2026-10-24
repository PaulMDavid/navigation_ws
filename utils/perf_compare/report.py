#!/usr/bin/env python3
"""Build results/<date>-<label>.md from a perf_compare.sh work dir and add a README row."""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'odom_rate_hang'))
from summarize import mean, tegrastats  # noqa: E402  (same tegrastats parser)

MARKER = '<!-- perf_compare rows above -->'
ODOM, COSTMAP = '/rtabmap/odom_reliable', '/local_costmap/costmap'


def to_mib(s):
    m = re.match(r'([\d.]+)\s*([KMG]i?B)', s)
    if not m:
        return 0.0
    return float(m[1]) * {'KiB': 1 / 1024, 'MiB': 1, 'GiB': 1024, 'KB': 1 / 1024,
                          'MB': 1, 'GB': 1024}[m[2]]


def docker_stats(path):
    per = {}
    for line in path.read_text().splitlines():
        f = line.split('\t')
        if len(f) == 3:
            cpu, mem = float(f[1].rstrip('%')), to_mib(f[2].split('/')[0])
            per.setdefault(f[0], []).append((cpu, mem))
    return {name: (mean(c for c, _ in v), mean(m for _, m in v)) for name, v in per.items()}


def fmt(x, spec='.1f'):
    return '—' if x is None else format(x, spec)


def main(label, secs, work, here):
    work, here = Path(work), Path(here)
    teg = tegrastats(work / 'tegrastats.log')
    containers = docker_stats(work / 'docker_stats.log')
    topics = json.loads((work / 'topics.json').read_text() or '{}')
    date = time.strftime('%Y-%m-%d')
    name = f'{date}-{label}.md'
    cpu, ram = mean(r['cpu'] for r in teg), mean(r['ram'] for r in teg)
    gpu, power = mean(r['gpu'] for r in teg), mean(r['power'] for r in teg)

    out = [f'# perf_compare: {label}', '', f'{date}, {secs} s', '',
           '## System (tegrastats)', '',
           f'CPU avg {fmt(cpu)} % · RAM {fmt(ram, ".0f")} MB · GPU {fmt(gpu)} % · power {fmt(power)} W', '',
           '## Containers (docker stats, mean)', '', '| container | CPU % | memory MiB |', '|---|---|---|']
    out += [f'| {n} | {fmt(c)} | {fmt(m, ".0f")} |' for n, (c, m) in sorted(containers.items())]
    out += ['', '## Topics', '', '| topic | Hz | latency p50 ms | latency p95 ms |', '|---|---|---|---|']
    for t, s in topics.items():
        if not s['advertised']:
            out.append(f'| {t} | not advertised | | |')
        else:
            out.append(f'| {t} | {fmt(s["hz"])} | {fmt(s["lat_p50_ms"])} | {fmt(s["lat_p95_ms"])} |')
    (here / 'results').mkdir(exist_ok=True)
    (here / 'results' / name).write_text('\n'.join(out) + '\n')
    print('\n'.join(out))

    get = lambda t, k: topics.get(t, {}).get(k) if topics.get(t, {}).get('advertised') else None
    row = (f'| {date} | {label} | {secs} | {fmt(cpu)} | {fmt(ram, ".0f")} | {fmt(gpu)} | {fmt(power)} '
           f'| {fmt(get("/ouster/points", "hz"))} | {fmt(get(ODOM, "hz"))} '
           f'| {fmt(get(ODOM, "lat_p50_ms"))} / {fmt(get(ODOM, "lat_p95_ms"))} '
           f'| {fmt(get(COSTMAP, "hz"))} | [{name}](results/{name}) |')
    readme = here / 'README.md'
    text = readme.read_text()
    readme.write_text(text.replace(MARKER, f'{row}\n{MARKER}'))


if __name__ == '__main__':
    main(*sys.argv[1:5])
