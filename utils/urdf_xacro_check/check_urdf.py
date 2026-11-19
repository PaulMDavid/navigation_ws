#!/usr/bin/env python3
"""Compare a rendered xacro model against a reference URDF.

Every link and joint in the new model must exist in the reference with the same
content (attributes compared numerically, 1e-9). Links/joints only in the reference
are listed as dropped. Exit 1 on any mismatch or on a frame missing from the reference.

usage: check_urdf.py NEW.urdf REFERENCE.urdf
"""
import sys
import xml.etree.ElementTree as ET


def norm(v):
    try:
        return tuple(round(float(x), 9) for x in v.split())
    except ValueError:
        return v.strip()


def canon(el):
    """Element -> comparable tuple, ignoring child order and gazebo-only extras."""
    attrs = tuple(sorted((k, norm(v)) for k, v in el.attrib.items()))
    kids = tuple(sorted(canon(c) for c in el))
    return (el.tag, attrs, (el.text or '').strip(), kids)


def items(root, tag):
    return {e.get('name'): e for e in root.findall(tag)}


def main(new_path, ref_path):
    new, ref = ET.parse(new_path).getroot(), ET.parse(ref_path).getroot()
    bad = 0
    for tag in ('link', 'joint'):
        n, r = items(new, tag), items(ref, tag)
        for name, el in sorted(n.items()):
            if name not in r:
                print(f'NEW-ONLY {tag} {name}'); bad += 1
            elif canon(el) != canon(r[name]):
                print(f'DIFFERS  {tag} {name}'); bad += 1
        print(f'{tag}s: {len(n)} kept, identical={len(n) - sum(1 for k in n if k not in r or canon(n[k]) != canon(r[k]))}')
        print(f'  dropped: {", ".join(sorted(set(r) - set(n))) or "-"}')
    kids = {j.find('child').get('link') for j in new.findall('joint')}
    roots = [l for l in items(new, 'link') if l not in kids]
    print(f'roots: {roots}')
    if roots != ['chassis_link']:
        bad += 1
    print('OK' if not bad else f'FAIL ({bad})')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
