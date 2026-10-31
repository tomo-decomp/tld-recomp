#!/usr/bin/env python3
"""Inventory the archive formats of the game's RomFS, from its own file table.

    python3 tools/inventory.py                          # read the packages, print the inventory
    python3 tools/inventory.py --json private/tld/inventory.json
    python3 tools/inventory.py --dir private/tld/romfs  # an already-extracted tree instead

Walking 66k extracted files on a slow disk takes minutes; the RomFS file table in the update's
NCA has every path, offset and size already, so the histogram comes from metadata and only a
small sample per extension is ever read. Nothing is modified.

Two levels are reported:

  * by extension (what the port has to be able to open), with byte totals, and
  * the bytes behind each extension: the magic of the stored file, and for `.zs` (a bare
    Zstandard frame) the magic after decompression, which is the real format.
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'extract'))
sys.path.insert(0, HERE)
import romfs_extract as rx            # noqa: E402
import tld as driver                  # noqa: E402

MAGICS = [
    (b'\x28\xb5\x2f\xfd', 'zstd frame'),
    (b'Yaz0', 'Yaz0 (Nintendo RLE)'),
    (b'BYML', 'BYML (binary YAML)'),
    (b'AAMP', 'AAMP (parameter archive)'),
    (b'BFRES', 'BFRES (model)'),
    (b'BNTX', 'BNTX (texture)'),
    (b'BNSH', 'BNSH (shader archive)'),
    (b'FWAV', 'FWAV (audio)'),
    (b'FSAR', 'FSAR (sound archive)'),
    (b'FSND', 'FSND (sound)'),
    (b'SARC', 'SARC (archive)'),
    (b'CRAG', 'CRAG (compressed archive)'),
    (b'BCH\x00', 'BCH (layout)'),
    (b'FLYT', 'FLYT (layout)'),
    (b'CLAN', 'CLAN (animation)'),
    (b'ANIM', 'ANIM (animation)'),
    (b'EFTF', 'EFTF (effect)'),
    (b'BNTX', 'BNTX'),
    (b'\x1f\x8b', 'gzip'),
    (b'PK\x03\x04', 'zip'),
    (b'\x89PNG', 'PNG'),
    (b'RIFF', 'RIFF/WAV'),
]


def magic(head):
    for m, name in MAGICS:
        if head.startswith(m):
            return name
    if not head.strip(b'\x00'):
        return 'zero-filled'
    return 'other (%s)' % head[:4].hex()


def ext_of(path):
    base = path.rsplit('/', 1)[-1]
    i = base.rfind('.')
    return base[i:].lower() if i > 0 else '(none)'


def inner_of(blob):
    """The magic under a .zs: the whole point of the inventory."""
    try:
        import zstandard
    except ImportError:
        return 'zstandard not installed'
    try:
        d = zstandard.ZstdDecompressor().decompress(blob, max_output_size=32 << 20)
    except Exception as e:
        return 'not a zstd frame (%s)' % type(e).__name__
    return magic(d[:16])


def entries_from_packages(base, update):
    """-> [(path, reader, offset, size)] straight from the NCA file tables."""
    b = rx.Nca(rx.open_package(base))
    u = rx.Nca(rx.open_package(update)) if update else None
    if u is not None and b.is_patch() and not u.is_patch():
        b, u = u, b
    romfs = rx.PatchedRomfs(b, u) if u is not None else rx.PlainRomfs(b)
    return romfs, sorted(rx.walk(romfs, romfs.level6))


def entries_from_dir(root):
    out = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            out.append(('/' + os.path.relpath(p, root).replace(os.sep, '/'), p, 0,
                        os.path.getsize(p)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', default=None)
    ap.add_argument('--update', default=None)
    ap.add_argument('--dir', default=None, help='inventory an extracted tree instead of the packages')
    ap.add_argument('--sample', type=int, default=2, help='files read per extension (0: none)')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv)

    if a.dir:
        entries = entries_from_dir(a.dir)
        reader = None
    else:
        romfs, entries = entries_from_packages(a.base or driver.default_base(),
                                               a.update if a.update is not None else driver.default_update())
        reader = romfs
        print('read from        %s' % os.path.basename(a.base or driver.default_base()))

    exts = collections.Counter()
    sizes = collections.defaultdict(int)
    top = collections.Counter()
    outer = collections.Counter()
    inner = collections.defaultdict(collections.Counter)
    sampled = collections.Counter()
    total = 0

    for path, offset, size in entries:
        e = ext_of(path)
        exts[e] += 1
        sizes[e] += size
        total += size
        top[path.strip('/').split('/')[0] if '/' in path.strip('/') else '(root)'] += 1
        if not a.sample or sampled[e] >= a.sample or size == 0:
            continue
        try:
            head = reader.read(offset, min(16, size)) if reader else open(offset, 'rb').read(16)
        except Exception:
            continue
        sampled[e] += 1
        outer[magic(head)] += 1
        if head.startswith(b'\x28\xb5\x2f\xfd'):
            blob = reader.read(offset, min(size, 4 << 20)) if reader else open(offset, 'rb').read(min(size, 4 << 20))
            inner[e][inner_of(blob)] += 1

    print('files            %d' % len(entries))
    print('bytes            %.2f GB' % (total / 2 ** 30))
    print()
    print('by extension')
    for e, n in exts.most_common(18):
        print('  %8d  %9.1f MB  %-8s %s'
              % (n, sizes[e] / 2 ** 20, e,
                 ', '.join('%s x%d' % (k, v) for k, v in inner[e].most_common(2)) if inner[e] else ''))
    print()
    print('top-level folders')
    for name, n in top.most_common(12):
        print('  %8d  %s' % (n, name))

    if a.json:
        with open(a.json, 'w') as f:
            json.dump({'files': len(entries), 'bytes': total,
                       'extensions': dict(exts), 'bytes_by_extension': dict(sizes),
                       'top_level': dict(top), 'stored_magic': dict(outer),
                       'inner_magic': {k: dict(v) for k, v in inner.items()}}, f, indent=2)
            f.write('\n')
        print('\nreport written to %s' % a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
