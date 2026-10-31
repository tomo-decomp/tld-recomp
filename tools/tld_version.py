#!/usr/bin/env python3
"""What build a game folder holds: main's build id, the version name, and the hooks of that build.

    python3 tools/tld_version.py <data folder>          write <folder>/version.ini and print it
    python3 tools/tld_version.py <folder> --get version  print one value
    python3 tools/tld_version.py <folder> --get hooks    print the hooks file for main, or "-"

Modelled on TLDRecomp/tools/tld_version.py. The build id is the first 16 bytes of main's ModuleId
(NSO header 0x40); games/tld/versions.txt maps it to a name and a hook list. A build that is not
listed gets no hooks and the game runs as dumped (docs/VERSIONS.md).
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSIONS = os.path.join(ROOT, 'games', 'tld', 'versions.txt')


def read_versions():
    out = {}
    with open(VERSIONS) as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            build_id, version, hooks = line.split()[:3]
            out[build_id.upper()] = (version, hooks)
    return out


def build_id(folder):
    path = os.path.join(folder, 'exefs', 'main')
    if not os.path.exists(path):
        sys.exit('%s: no exefs/main (run the game stage first)' % folder)
    with open(path, 'rb') as f:
        head = f.read(0x50)
    if head[:4] != b'NSO0':
        sys.exit('%s: exefs/main is not an NSO0' % path)
    return head[0x40:0x50].hex()


def title_version(folder):
    """The update's title version from the folder's version.ini or game.ini, when it has one."""
    for name in ('version.ini', 'game.ini'):
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for line in f:
                m = re.match(r'\s*(?:update_)?title_version\s*=\s*(0x[0-9a-fA-F]+|\d+)', line)
                if m:
                    return int(m.group(1), 0)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder', help='the data folder (private/tld) holding exefs/main')
    ap.add_argument('--get', default=None, help='print one value: build_id, version, hooks, title_version')
    a = ap.parse_args()

    bid = build_id(a.folder)
    known = read_versions().get(bid.upper())
    version, hooks = known if known else ('', '-')
    tv = title_version(a.folder)
    if not version:
        version = ('1.0.%d' % (tv >> 16)) if tv else '1.0.0'

    values = {'build_id': bid, 'version': version, 'title_version': str(tv), 'hooks': hooks}
    if a.get:
        print(values[a.get])
        return 0
    path = os.path.join(a.folder, 'version.ini')
    with open(path, 'w') as f:
        for k, v in values.items():
            f.write('%s = %s\n' % (k, v))
    for k, v in values.items():
        print('%-14s %s' % (k, v))
    print('wrote          %s' % path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
