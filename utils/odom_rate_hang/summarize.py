#!/usr/bin/env python3
"""Turn a logger.sh run directory into a per-step table (and a plot if matplotlib exists).

    python3 summarize.py /mnt/ssd/pdavid/logs/<run>

Writes summary.md (and summary.png) into the run directory and prints the table.
"max gap" is the longest stretch without a 1 Hz sample: the logger itself stalled,
which is what a freeze looks like from the inside.
"""
import re
import sys
import time
from datetime import datetime
from pathlib import Path


def tegrastats(path):
    rows = []
    for line in path.read_text(errors='replace').splitlines():
        m = re.match(r'(\d\d-\d\d-\d{4} \d\d:\d\d:\d\d) ', line)
        if not m:
            continue
        t = time.mktime(datetime.strptime(m[1], '%m-%d-%Y %H:%M:%S').timetuple())
        ram = re.search(r'RAM (\d+)/', line)
        cpus = [int(c) for c in re.findall(r'(\d+)%@\d+', line)]
        gpu = re.search(r'GR3D_FREQ (\d+)%', line)
        tj = re.search(r'tj@([\d.]+)C', line)
        mw = [int(p) for p in re.findall(r' (\d+)mW/', line)]
        rows.append({'t': t, 'ram': int(ram[1]) if ram else None,
                     'cpu': sum(cpus) / len(cpus) if cpus else None,
                     'cpu_max': max(cpus) if cpus else None,
                     'gpu': int(gpu[1]) if gpu else None,
                     'tj': float(tj[1]) if tj else None,
                     'power': sum(mw) / 1000 if mw else None})
    return rows


def vmstat(path):
    rows = []
    for line in path.read_text(errors='replace').splitlines():
        f = line.split()
        if len(f) < 19 or not f[0].isdigit():
            continue
        t = time.mktime(datetime.strptime(f'{f[17]} {f[18]}', '%Y-%m-%d %H:%M:%S').timetuple())
        rows.append({'t': t, 'run_q': int(f[0]), 'blocked': int(f[1]),
                     'swap_io': int(f[6]) + int(f[7]), 'iowait': int(f[15])})
    return rows


def keyvals(path):
    """Lines of 'epoch k=v k=v ...' (udp.log) -> [{'t':..., k: int}]."""
    rows = []
    for line in path.read_text(errors='replace').splitlines():
        f = line.split()
        if not f or not f[0].isdigit():
            continue
        row = {'t': float(f[0])}
        for kv in f[1:]:
            if '=' in kv:
                k, v = kv.split('=', 1)
                row[k.rstrip(':')] = int(v)
        rows.append(row)
    return rows


def load_times(path):
    return [float(l.split()[0]) for l in path.read_text().splitlines() if l[:1].isdigit()]


def windows(run, start, end):
    events = []
    if (run / 'events.log').exists():
        for line in (run / 'events.log').read_text().splitlines():
            t, _, text = line.partition(' ')
            events.append((float(t), text))
    marks = [(start, 'before steps')] + events
    out = []
    for i, (t, label) in enumerate(marks):
        if label == 'end':
            continue
        t_end = marks[i + 1][0] if i + 1 < len(marks) else end
        out.append((label, t, t_end))
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fmt(x, spec='.0f'):
    return '—' if x is None else format(x, spec)


def main(run):
    run = Path(run)
    teg = tegrastats(run / 'tegrastats.log')
    vm = vmstat(run / 'vmstat.log')
    udp = keyvals(run / 'udp.log')
    ticks = load_times(run / 'load.log')
    if not ticks:
        sys.exit('no samples in load.log')

    header = ('| window | s | CPU avg % | CPU max core % | RAM MB | GPU % | Tj max °C | power W '
              '| run queue | iowait % | swap io | UDP rcvbuf err/s | max gap s |')
    lines = [f'# {run.name}', '', (run / 'metadata.txt').read_text().split('\n', 1)[0], '',
             header, '|' + '---|' * (header.count('|') - 1)]
    for label, a, b in windows(run, ticks[0], ticks[-1]):
        inside = lambda rows: [r for r in rows if a <= r['t'] < b]
        t, v, u = inside(teg), inside(vm), inside(udp)
        tk = [x for x in ticks if a <= x < b]
        gap = max((y - x for x, y in zip(tk, tk[1:])), default=None)
        err = None
        if len(u) > 1 and 'UdpRcvbufErrors' in u[0]:
            err = (u[-1]['UdpRcvbufErrors'] - u[0]['UdpRcvbufErrors']) / (u[-1]['t'] - u[0]['t'])
        lines.append('| ' + ' | '.join([
            label, fmt(b - a), fmt(mean(r['cpu'] for r in t)), fmt(max((r['cpu_max'] for r in t), default=None)),
            fmt(mean(r['ram'] for r in t)), fmt(mean(r['gpu'] for r in t)),
            fmt(max((r['tj'] for r in t if r['tj']), default=None), '.1f'), fmt(mean(r['power'] for r in t), '.1f'),
            fmt(mean(r['run_q'] for r in v), '.1f'), fmt(mean(r['iowait'] for r in v)),
            fmt(sum(r['swap_io'] for r in v)), fmt(err), fmt(gap)]) + ' |')
    table = '\n'.join(lines) + '\n'
    (run / 'summary.md').write_text(table)
    print(table)

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return
    t0 = ticks[0]
    fig, ax = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
    ax[0].plot([r['t'] - t0 for r in teg], [r['cpu'] for r in teg]); ax[0].set_ylabel('CPU %')
    ax[1].plot([r['t'] - t0 for r in teg], [r['ram'] for r in teg]); ax[1].set_ylabel('RAM MB')
    ax[2].plot([r['t'] - t0 for r in vm], [r['run_q'] for r in vm]); ax[2].set_ylabel('run queue')
    ax[3].plot([x - t0 for x in ticks[1:]], [y - x for x, y in zip(ticks, ticks[1:])])
    ax[3].set_ylabel('sample gap s'); ax[3].set_xlabel('s')
    for label, a, _ in windows(run, ticks[0], ticks[-1])[1:]:
        for x in ax:
            x.axvline(a - t0, color='grey', lw=0.8)
        ax[0].text(a - t0, ax[0].get_ylim()[1], label, fontsize=7, rotation=90, va='top')
    fig.tight_layout()
    fig.savefig(run / 'summary.png', dpi=100)


if __name__ == '__main__':
    main(sys.argv[1])
