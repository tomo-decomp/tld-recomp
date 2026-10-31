#!/usr/bin/env python3
"""From your own packages to a native build: every stage in order, like TLDRecomp's setup_tld.py.

    python3 tools/setup_tld.py                       # all stages, defaults below
    python3 tools/setup_tld.py --base X.xci --update Y.nsp
    python3 tools/setup_tld.py --only recompile      # one stage
    python3 tools/setup_tld.py --no-build            # stop before compiling

Stages, each skipped when its output is already there, so a run can be repeated after a failure
or an update of the repository. Lines starting with "== " name the stage:

    tools       python packages (capstone, lz4, zstandard), cmake/ninja, a C++ compiler
    game        the dump: ExeFS (main, sdk, and subsdk0 when the game has one) and the RomFS
    version     what build this is (build id, version, hooks) -> private/tld/version.ini
    recompile   tools/recomp: sdk, then main, each at its own base -> private/tld/gen/<module>
    build       the runtime in runtime/ plus the generated modules

The layout is TLDRecomp's: every module is recompiled on its own and linked at its module base
(sdk 0x4010000000, subsdk0 0x4018000000, main 0x4000000000), so a call into the SDK runs the
recompiled SDK instead of an HLE stub.

Everything derived from the game stays in private/tld/ (gitignored): the extracted RomFS, the ELF,
the generated C++ and the build. Nothing here is ever committed.

env: JOBS=<compile jobs>   FORCE=<stage> to redo one stage (game, recompile, build)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'extract'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import romfs_extract as rx       # noqa: E402
import tld as tld_driver         # noqa: E402

# (module, base): the order matters, a module is recompiled after the ones it imports from.
MODULES = (('sdk', '0x4010000000'), ('subsdk0', '0x4018000000'), ('main', '0x4000000000'))


def say(stage):
    print('\n== %s' % stage, flush=True)


def fail(msg):
    print(msg, flush=True)
    sys.exit(1)


def force(stage):
    return os.environ.get('FORCE') == stage


def run(cmd, log=None, cwd=ROOT, env=None, check=True):
    exe = shutil.which(cmd[0]) or cmd[0]
    if log:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, 'w', encoding='utf-8', errors='replace') as f:
            rc = subprocess.call([exe] + cmd[1:], stdout=f, stderr=subprocess.STDOUT, cwd=cwd, env=env)
        if rc and check:
            with open(log, encoding='utf-8', errors='replace') as f:
                print(''.join(f.readlines()[-25:]))
            fail('failed: %s ... (log: %s)' % (' '.join(cmd[:3]), log))
        return rc
    rc = subprocess.call([exe] + cmd[1:], cwd=cwd, env=env)
    if rc and check:
        fail('failed: %s ...' % ' '.join(cmd[:3]))
    return rc


def newest(paths):
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def count_files(path):
    return sum(len(files) for _, _, files in os.walk(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', default=None, help='the base game package (.xci/.nsp)')
    ap.add_argument('--update', default=None, help='the update package (.nsp); omit for none')
    ap.add_argument('--out', default=os.path.join(ROOT, 'private', 'tld'))
    ap.add_argument('--only', action='append', default=[],
                    choices=['tools', 'game', 'version', 'recompile', 'build'])
    ap.add_argument('--no-build', action='store_true', help='stop before compiling the runtime')
    ap.add_argument('--limit', type=int, default=None, help='recompile: lift at most this many functions')
    a = ap.parse_args()

    G = os.path.abspath(a.out)
    logs = os.path.join(G, 'logs')
    os.makedirs(logs, exist_ok=True)
    py = sys.executable
    jobs = int(os.environ.get('JOBS') or (os.cpu_count() or 1))
    stages = a.only or ['tools', 'game', 'version', 'recompile', 'build']

    base = a.base or tld_driver.default_base()
    if a.update is None:
        a.update = tld_driver.default_update() or ''

    # ---- tools ---------------------------------------------------------------------------
    if 'tools' in stages:
        say('tools (python packages, cmake, ninja, a C++ compiler)')
        missing = [m for m in ('Crypto', 'zstandard', 'lz4', 'capstone') if
                   subprocess.call([py, '-c', 'import %s' % m], stderr=subprocess.DEVNULL)]
        if missing:
            print('installing: %s' % ' '.join(missing))
            run([py, '-m', 'pip', 'install', '-q', 'pycryptodome', 'zstandard', 'lz4', 'capstone'])
        for tool in ('cmake', 'ninja', 'c++'):
            if not shutil.which(tool):
                fail('missing: %s (needed for the build stage)' % tool)
        print('python   %s' % sys.version.split()[0])
        print('cmake    %s' % subprocess.run(['cmake', '--version'], capture_output=True, text=True)
              .stdout.splitlines()[0])

    # ---- game ----------------------------------------------------------------------------
    if 'game' in stages:
        say('game (ExeFS, main.elf, the RomFS with the update applied)')
        tld = os.path.join('tools', 'tld.py')
        run([py, tld, 'info', '--base', base, '--update', a.update, '--out', G],
            log=os.path.join(logs, 'info.log'))
        with open(os.path.join(logs, 'info.log'), encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.strip():
                    print('  ' + line.rstrip())
        if not os.path.exists(os.path.join(G, 'exefs', 'main')) or force('game'):
            run([py, tld, 'exefs', '--base', base, '--update', a.update, '--out', G],
                log=os.path.join(logs, 'exefs.log'))
        if not os.path.exists(os.path.join(G, 'elf', 'main.elf')):
            run([py, tld, 'elf', '--base', base, '--update', a.update, '--out', G],
                log=os.path.join(logs, 'elf.log'))
        print('  romfs now        %d file(s)' % count_files(os.path.join(G, 'romfs')))
        if force('game') or not os.path.exists(os.path.join(G, 'romfs', 'Font')):
            print('  extracting the RomFS (resumable, this is the multi-GB one)')
            run([py, os.path.join('tools', 'extract', 'romfs.py'), '--base', base,
                 '--update', a.update or '', '--root', G], log=os.path.join(logs, 'romfs.log'))
        print('  romfs            %d file(s)' % count_files(os.path.join(G, 'romfs')))

    # ---- version -------------------------------------------------------------------------
    if 'version' in stages:
        say('version')
        if not os.path.exists(os.path.join(G, 'exefs', 'main')):
            fail('no game in %s: run the game stage first' % G)
        run([py, os.path.join('tools', 'tld_version.py'), G])
        with open(os.path.join(G, 'version.ini')) as f:
            print(''.join('  ' + l for l in f))

    def get(key):
        r = subprocess.run([py, os.path.join('tools', 'tld_version.py'), G, '--get', key],
                           capture_output=True, text=True, cwd=ROOT)
        return r.stdout.strip()

    # ---- recompile -----------------------------------------------------------------------
    if 'recompile' in stages:
        present = [(m, b) for m, b in MODULES if os.path.exists(os.path.join(G, 'exefs', m))]
        if not present:
            fail('no exefs modules in %s: run the game stage first' % G)
        say('recompile (%s)' % ', '.join(m for m, _ in present))
        hooks = get('hooks') or '-'
        recomp_mtime = newest([os.path.join('tools', 'recomp', f)
                               for f in os.listdir(os.path.join(ROOT, 'tools', 'recomp')) if f.endswith('.py')])
        for mod, base_addr in present:
            h = ['--hooks', hooks] if mod == 'main' and hooks != '-' else []
            profile = ' '.join(h) or 'none'
            gen = os.path.join(G, 'gen', mod)
            table, prof = os.path.join(gen, 'table.cpp'), os.path.join(gen, 'profile.txt')
            stale = (force('recomp') or not os.path.exists(table) or recomp_mtime > os.path.getmtime(table)
                     or not os.path.exists(prof) or open(prof).read().strip() != profile)
            if stale:
                run([py, '-m', 'recomp', os.path.join(G, 'exefs', mod), gen, '--name', mod,
                     '--base', base_addr, '--jobs', str(jobs)] + h,
                    cwd=os.path.join(ROOT, 'tools'), log=os.path.join(logs, 'recomp_%s.log' % mod))
                open(prof, 'w').write(profile + '\n')
                with open(os.path.join(logs, 'recomp_%s.log' % mod), encoding='utf-8', errors='replace') as f:
                    tail = [l.rstrip() for l in f if l.strip()][-4:]
                print('  %s: %s' % (mod, ' | '.join(tail)))
            else:
                print('  %s: up to date' % mod)
            man = os.path.join(gen, 'manifest.json')
            if os.path.exists(man):
                m = json.load(open(man))
                print('    functions %d, instructions %d, files %d'
                      % (m['functions'], m['instructions'], m['source_files']))

    # ---- build ---------------------------------------------------------------------------
    if 'build' in stages:
        if a.no_build:
            say('done (build skipped: --no-build)')
            return
        mods = [m for m, _ in MODULES if os.path.exists(os.path.join(G, 'gen', m, 'table.cpp'))]
        say('build (-j%d: the runtime plus the generated code)' % jobs)
        build = os.path.join(G, 'build')
        run(['cmake', '-S', ROOT, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
             '-DNX_GAME=tld', '-DNX_GEN_DIR=' + os.path.join(G, 'gen'),
             '-DNX_MODULES=' + ';'.join(mods)],
            log=os.path.join(logs, 'cmake.log'))
        run(['cmake', '--build', build, '-j%d' % jobs], log=os.path.join(logs, 'build.log'))
        exe = os.path.join(build, 'tld')
        say('done: %s   (data: %s)' % (exe, G))
    else:
        say('done')


if __name__ == '__main__':
    main()
