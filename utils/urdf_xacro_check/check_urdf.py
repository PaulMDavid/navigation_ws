#!/usr/bin/env python3
"""Compare a rendered xacro model against a reference URDF.

Every link and joint in the new model must exist in the reference with the same
content (attributes compared numerically, 1e-9). Links/joints only in the reference
are listed as dropped. Exit 1 on any mismatch or on a frame missing from the reference.

usage: check_urdf.py NEW.urdf REFERENCE.urdf
       check_urdf.py --shift DZ NEW.urdf REFERENCE.urdf

--shift DZ: the root frame was moved instead (new root = old root lowered by DZ).
Then every link frame and every visual/collision pose, with all joints at zero, must
sit where it was in the reference: new pose == reference pose + (0, 0, DZ), to 1e-6.
"""
import math
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


def tf(origin):
    """<origin> -> 4x4 (URDF rpy = fixed-axis XYZ)."""
    xyz = [float(v) for v in (origin.get('xyz', '0 0 0') if origin is not None else '0 0 0').split()]
    r, p, y = [float(v) for v in (origin.get('rpy', '0 0 0') if origin is not None else '0 0 0').split()]
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [[cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr, xyz[0]],
            [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr, xyz[1]],
            [-sp, cp*sr, cp*cr, xyz[2]],
            [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def poses(root):
    """{name: 4x4 in root frame} for links and their visual/collision elements."""
    joints = {j.find('child').get('link'): j for j in root.findall('joint')}
    links = items(root, 'link')
    out = {}

    def link_pose(name):
        if name not in joints:
            return tf(None)
        j = joints[name]
        return mul(link_pose(j.find('parent').get('link')), tf(j.find('origin')))

    for name, el in links.items():
        T = link_pose(name)
        out[name] = T
        for kind in ('visual', 'collision'):
            for i, v in enumerate(el.findall(kind)):
                out[f'{name}/{kind}{i}'] = mul(T, tf(v.find('origin')))
    return out


def main_shift(dz, new_path, ref_path):
    new = poses(ET.parse(new_path).getroot())
    ref = poses(ET.parse(ref_path).getroot())
    bad = 0
    new_root = ET.parse(new_path).getroot()
    children = {j.find('child').get('link') for j in new_root.findall('joint')}
    roots = [n for n in items(new_root, 'link') if n not in children]
    for name, T in sorted(new.items()):
        if name in roots:
            continue  # the root frame is the one that moved on purpose
        if name not in ref:
            print(f'NEW-ONLY {name}'); bad += 1; continue
        R = [row[:] for row in ref[name]]
        R[2][3] += dz
        err = max(abs(T[i][j] - R[i][j]) for i in range(3) for j in range(4))
        if err > 1e-6:
            print(f'MOVED    {name}  max err {err:.6f}'); bad += 1
    print(f'{len(new) - len(roots)} frames/visuals checked against reference + {dz} m in z')
    print('OK' if not bad else f'FAIL ({bad})')
    return 1 if bad else 0


if __name__ == '__main__':
    if sys.argv[1] == '--shift':
        sys.exit(main_shift(float(sys.argv[2]), *sys.argv[3:5]))
    sys.exit(main(*sys.argv[1:3]))
