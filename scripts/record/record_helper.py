#!/usr/bin/env python3
"""YAML/JSON side of scripts/record/record_drive.sh, run on orintwo's host (python3 +
python3-yaml, no ROS). Every output line is `<kind> <json>` or `error <reason>`; the shell
wraps them into its JSON lines.

  presets PRESETS_YAML                      group/preset lines
  resolve PRESETS_YAML PRESET [+T|-T ...]   topics + sensor lines for `record start`
  silent PRESETS_YAML TOPICS_FILE WATCH_JSON WINDOW
                                            selected topics without a message in the last
                                            WINDOW s, from record_watch.py's file
  baginfo BAG_DIR                           duration + message count from metadata.yaml
"""
import json
import re
import sys
import time

import yaml

TOPIC_RE = re.compile(r'^/[A-Za-z0-9_/]+$')


def out(kind, obj):
    print(f'{kind} {json.dumps(obj)}', flush=True)


def fail(reason):
    print(f'error {reason}', flush=True)
    sys.exit(2)


def load(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    groups = cfg.get('groups') or {}
    presets = cfg.get('presets') or {}
    for name, p in presets.items():
        topics = []
        for g in p.get('groups', []):
            if g not in groups:
                fail(f'preset {name}: unknown group {g}')
            topics += groups[g]['topics']
        topics += p.get('topics', [])
        p['resolved'] = list(dict.fromkeys(topics))
    return cfg, groups, presets


def cmd_presets(path):
    cfg, groups, presets = load(path)
    for name, g in groups.items():
        out('group', {'name': name, 'label': g.get('label', name), 'topics': g['topics']})
    for name, p in presets.items():
        out('preset', {'name': name, 'label': p.get('label', name), 'default': bool(p.get('default')),
                       'groups': p.get('groups', []), 'topics': p['resolved']})
    out('quiet_ok', cfg.get('quiet_ok') or [])


def cmd_resolve(path, preset, mods):
    cfg, groups, presets = load(path)
    if preset not in presets:
        fail(f'unknown preset {preset} (have {" ".join(presets)})')
    topics = list(presets[preset]['resolved'])
    for m in mods:
        sign, t = m[0], m[1:]
        if sign not in '+-' or not TOPIC_RE.match(t) or '//' in t or t.endswith('/'):
            fail(f'bad topic argument {m!r} (want +/topic or -/topic)')
        if sign == '+' and t not in topics:
            topics.append(t)
        elif sign == '-':
            if t not in topics:
                fail(f'-{t}: not in the selection')
            topics.remove(t)
    if not topics:
        fail('no topics left to record')
    out('topics', topics)
    sel = set(topics)
    for name, s in (cfg.get('sensors') or {}).items():
        mine = [t for g in s.get('groups', []) for t in groups.get(g, {}).get('topics', []) if t in sel]
        if not mine:
            continue
        check = [t for t in s.get('check', []) if t in sel] or \
            [t for t in mine if t not in (cfg.get('quiet_ok') or [])][:1]
        out('sensor', {'name': name, 'container': s.get('container'), 'stop_first': s.get('stop_first', []),
                       'check': check})


def cmd_silent(path, topics_file, watch_file, window):
    cfg, _, _ = load(path)
    quiet = set(cfg.get('quiet_ok') or [])
    with open(topics_file) as f:
        topics = [t.strip() for t in f if t.strip()]
    try:
        with open(watch_file) as f:
            w = json.load(f)
    except (OSError, ValueError):
        out('silent', {'silent': None, 'input_mbps': None, 'watch': 'no watch file yet'})
        return
    now = time.time()
    if now - w.get('t', 0) > 5:
        out('silent', {'silent': None, 'input_mbps': None, 'watch': f'watch file {now - w.get("t", 0):.0f} s old'})
        return
    if w['t'] - w.get('start', w['t']) < window:      # watcher younger than the window: no verdict yet
        out('silent', {'silent': None, 'input_mbps': w.get('mbps'), 'watch': 'starting'})
        return
    seen = w.get('topics', {})
    blind = set(w.get('unloadable', []))
    silent = [t for t in topics if t not in quiet and t not in blind
              and now - seen.get(t, {}).get('last', 0) > window]
    out('silent', {'silent': silent, 'input_mbps': w.get('mbps'), 'watch': 'ok',
                   'unwatched': [t for t in topics if t in blind]})


def cmd_baginfo(bag):
    try:
        with open(f'{bag}/metadata.yaml') as f:
            info = yaml.safe_load(f)['rosbag2_bagfile_information']
    except (OSError, KeyError, TypeError, yaml.YAMLError) as e:
        fail(f'no readable metadata.yaml: {type(e).__name__}')
    out('baginfo', {'duration_s': round(info['duration']['nanoseconds'] / 1e9, 1),
                    'messages': info.get('message_count'),
                    'topics': len(info.get('topics_with_message_count') or []),
                    'files': len(info.get('relative_file_paths') or [])})


def main(a):
    if not a:
        fail('no command')
    cmd, rest = a[0], a[1:]
    if cmd == 'presets' and len(rest) == 1:
        cmd_presets(*rest)
    elif cmd == 'resolve' and len(rest) >= 2:
        cmd_resolve(rest[0], rest[1], rest[2:])
    elif cmd == 'silent' and len(rest) == 4:
        cmd_silent(rest[0], rest[1], rest[2], float(rest[3]))
    elif cmd == 'baginfo' and len(rest) == 1:
        cmd_baginfo(*rest)
    else:
        fail(f'bad command {" ".join(a)}')


if __name__ == '__main__':
    main(sys.argv[1:])
