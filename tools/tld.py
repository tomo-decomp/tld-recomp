#!/usr/bin/env python3
"""tld-recomp driver: read your own packages, build the dump folder, inspect the game binary.

    python tools/tld.py info
    python tools/tld.py exefs   [--base P] [--update P] [--out DIR]
    python tools/tld.py romfs   [--base P] [--update P] [--out DIR] [--list]
    python tools/tld.py elf     [--out DIR]
    python tools/tld.py all

Defaults point at this repository's roms/switch layout. Nothing derived from the game is
written outside the output folder (private/dump by default).
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'extract'))
import romfs_extract as rx  # noqa: E402


def repo_root():
    return rx._repo_root() or os.path.dirname(HERE)


def default_base():
    return os.path.join(repo_root(), 'roms', 'switch', 'base', 'tomo', 'tomodachi.xci')


def default_update():
    d = os.path.join(repo_root(), 'roms', 'switch', 'updates', 'tomo')
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d)):
        if name.lower().endswith(('.nsp', '.nsp')):
            return os.path.join(d, name)
    return None


def default_out():
    # TLDRecomp keeps everything derived from the game in one gitignored private/<game>/ tree.
    return os.path.join(repo_root(), 'tld-recomp', 'private', 'tld')


KNOWN_VERSIONS = {0: 'base game, 1.0.0', 262144: 'update, 1.0.4'}


def version_string(ver):
    """The raw title version, which is what packages and the CNMT carry.
    The published retail versions of this game are v0 (1.0.0) and v262144 (1.0.4)."""
    if ver is None:
        return 'unknown'
    note = KNOWN_VERSIONS.get(ver)
    return 'v%d (0x%X)%s' % (ver, ver, '  = ' + note if note else '')


def open_pair(base_path, update_path):
    base = rx.Nca(rx.open_package(base_path))
    update = rx.Nca(rx.open_package(update_path)) if update_path else None
    if update is not None and base.is_patch() and not update.is_patch():
        base, update = update, base
        print('note: base and update were swapped; using them the right way round')
    if update is None and base.is_patch():
        raise SystemExit('%s is an update, not the base game' % base_path)
    return base, update


def _sections(nca):
    names = {0: 'RomFS', 1: 'PFS0/ExeFS'}
    return ', '.join('%d:%s/%s/%.1fMB' % (s['index'], names.get(s['type'], 'fs%d' % s['type']),
                                          'patch' if s['crypto'] == 4 else 'crypto%d' % s['crypto'],
                                          s['size'] / 2 ** 20) for s in nca.sections)


def cmd_info(args):
    print('keys                  %s' % rx.KEYS_PATH)
    print('title keys            %d entries' % len(rx.TITLE_KEYS))
    base_pkg = rx.open_package(args.base)
    base = rx.Nca(base_pkg)
    b_tid, b_ver = rx.meta_version(base_pkg)
    print()
    print('base package          %s' % args.base)
    print('base title id         %016X  (CNMT; program NCA %s)' % (b_tid, base.name))
    print('base version          %s' % version_string(b_ver))
    print('base sections         %s' % _sections(base))
    if args.update:
        up_pkg = rx.open_package(args.update)
        up = rx.Nca(up_pkg)
        u_tid, u_ver = rx.meta_version(up_pkg)
        print()
        print('update package        %s' % args.update)
        print('update title id       %016X  (CNMT; program NCA %s)' % (u_tid, up.name))
        print('update version        %s' % version_string(u_ver))
        print('update sections       %s' % _sections(up))
        ok = (u_tid & ~0x800) == (b_tid & ~0x800) and up.is_patch()
        print('update patches base   %s' % ('yes' if ok else 'NO'))
    return 0


def cmd_exefs(args):
    base, update = open_pair(args.base, args.update)
    nca = update or base
    out = os.path.join(args.out, 'exefs')
    print('ExeFS from the %s program NCA -> %s' % ('update' if update else 'base', out))
    written = rx.extract_exefs(nca, out)
    for name, size in written:
        if name == 'main':
            print('main NSO: %.2f MB' % (size / 2 ** 20))
    return 0


def cmd_update(args):
    """Extract the update's own ExeFS next to the base one, so 1.0.0 and 1.0.4 can be compared."""
    if not args.update:
        raise SystemExit('no update package found')
    up = rx.Nca(rx.open_package(args.update))
    out = os.path.join(args.out, 'exefs_update')
    print('ExeFS from the update program NCA -> %s' % out)
    written = rx.extract_exefs(up, out)
    for name, size in written:
        if name == 'main':
            print('update main NSO: %.2f MB' % (size / 2 ** 20))
    return 0


def cmd_romfs(args):
    base, update = open_pair(args.base, args.update)
    rx.extract(base, update, os.path.join(args.out, 'romfs'), list_only=args.list)
    return 0


def cmd_elf(args):
    import nso2elf
    main = os.path.join(args.out, 'exefs', 'main')
    if not os.path.isfile(main):
        raise SystemExit('%s not found: run "tld.py exefs" first' % main)
    out = os.path.join(args.out, 'elf')
    os.makedirs(out, exist_ok=True)
    dst = os.path.join(out, 'main.elf')
    print('NSO -> ELF: %s' % dst)
    nso2elf.convert(main, dst)
    data = open(dst, 'rb').read()
    print('  .text is %.2f MB of AArch64' % (struct.unpack('<Q', data[0x40 + 0x20:0x40 + 0x28])[0] / 2 ** 20))
    return 0


def cmd_all(args):
    cmd_info(args)
    print()
    cmd_exefs(args)
    print()
    cmd_elf(args)
    print()
    if not args.exefs_only:
        cmd_romfs(args)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', choices=['info', 'exefs', 'update', 'romfs', 'elf', 'all'])
    p.add_argument('--base', default=default_base())
    p.add_argument('--update', default=default_update())
    p.add_argument('--out', default=default_out())
    p.add_argument('--list', action='store_true', help='romfs: list files, do not write them')
    p.add_argument('--exefs-only', action='store_true', help='all: skip the (multi-GB) RomFS')
    args = p.parse_args(argv)
    if args.update == '':
        args.update = None
    return {'info': cmd_info, 'exefs': cmd_exefs, 'update': cmd_update, 'romfs': cmd_romfs,
            'elf': cmd_elf, 'all': cmd_all}[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
