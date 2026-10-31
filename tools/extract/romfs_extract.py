"""Read a Switch title's Program NCA straight out of its package, apply the update, and extract.

    python romfs_extract.py <base.nsp|.xci|.nca> <update.nsp|.xci|.nca> <out_dir> [--list]

This is the hactool-free reader used by the reference ports in this repository: it parses
PFS0 (.nsp), HFS0/HEAD (.xci), NCA3 (AES-XTS header, AES-CTR body), the update's BKTR
patch tables, and RomFS/IVFC directly. Only pycryptodome is needed.

Keys are looked up in this order (first file found wins):
    $TLD_PROD_KEYS, <repo>/keys/prod.keys, ~/.switch/prod.keys, $XDG_DATA_HOME/...
Title keys (rights id -> encrypted title key) come from the ticket inside the package,
or from a title.keys file next to the prod.keys that was used.
"""
import bisect
import os
import struct
import sys

from Crypto.Cipher import AES

# Tomodachi Life: Living the Dream
BASE_TITLE_ID = 0x010051F0207B2000
UPDATE_TITLE_ID = 0x010051F0207B2800

# Upper bound on one decrypt+write step. Deliberately small: a 64 MB step costs more memory
# than a small machine has, and got an earlier run of this extractor OOM-killed on a 3 GB box.
CHUNK = 8 << 20


def _repo_root():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, 'keys')):
            return d
        d = os.path.dirname(d)
    return None


def _key_files(name):
    """Candidate locations for prod.keys / title.keys, most specific first."""
    env = os.environ.get('TLD_PROD_KEYS' if name == 'prod.keys' else 'TLD_TITLE_KEYS')
    if env:
        yield env
    root = _repo_root()
    if root:
        yield os.path.join(root, 'keys', name)
    home = os.path.expanduser('~')
    yield os.path.join(home, '.switch', name)
    xdg = os.environ.get('XDG_DATA_HOME') or os.path.join(home, '.local', 'share')
    for emu in ('eden', 'yuzu', 'suyu', 'sudachi', 'citron', 'torzu', 'ryujinx'):
        yield os.path.join(xdg, emu, 'keys', name)
        yield os.path.join(xdg, emu, name)
    ad = os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming')
    for emu in ('eden', 'Eden', 'yuzu', 'suyu', 'sudachi', 'citron', 'torzu', 'sumi', 'lime'):
        yield os.path.join(ad, emu, 'keys', name)
    yield os.path.join(ad, 'Ryujinx', 'system', name)


def load_keys(name='prod.keys'):
    """-> (dict: lowercased key name -> bytes, path used or None)."""
    for path in _key_files(name):
        if os.path.isfile(path):
            out = {}
            for line in open(path, errors='replace'):
                if '=' in line and not line.lstrip().startswith('#'):
                    k, v = line.split('=', 1)
                    try:
                        out[k.strip().lower()] = bytes.fromhex(v.strip())
                    except ValueError:
                        pass
            return out, path
    return {}, None


KEYS, KEYS_PATH = load_keys('prod.keys')
# title.keys sits next to whichever prod.keys was used, so a self-contained keys/ folder works.
TITLE_KEYS, _ = ({}, None) if not KEYS_PATH else load_keys('title.keys')


def need_keys():
    if 'header_key' not in KEYS:
        raise SystemExit('prod.keys not found or incomplete (looked at $TLD_PROD_KEYS, <repo>/keys/prod.keys, '
                         '~/.switch/prod.keys, the emulators\' key folders). Dump it from your own console.')


def xts_decrypt(key, data, sector, sector_size=0x200):
    """AES-128-XTS, as used by the NCA header."""
    k1, k2 = AES.new(key[:16], AES.MODE_ECB), AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for s in range(len(data) // sector_size):
        tweak = int.from_bytes(k2.encrypt((sector + s).to_bytes(16, 'big')), 'little')
        for b in range(0, sector_size, 16):
            block = data[s * sector_size + b:s * sector_size + b + 16]
            t = tweak.to_bytes(16, 'little')
            out += bytes(x ^ y for x, y in zip(k1.decrypt(bytes(x ^ y for x, y in zip(block, t))), t))
            tweak <<= 1
            if tweak >> 128:
                tweak = (tweak & ((1 << 128) - 1)) ^ 0x87
    return bytes(out)


def not_a_package(path, head):
    size = os.path.getsize(path) if os.path.exists(path) else 0
    kinds = ((b'PK\x03\x04', 'a ZIP archive'), (b'Rar!', 'a RAR archive'),
             (b'7z\xbc\xaf', 'a 7-Zip archive'), (b'\x1f\x8b', 'a GZIP archive'))
    what = next((k for m, k in kinds if head.startswith(m)), None)
    if what:
        why = 'it is %s renamed; extract it and use the .nsp/.xci inside' % what
    elif not head.strip(b'\x00'):
        why = 'it starts with zeros: the download is incomplete or damaged'
    elif size < 64 << 20:
        why = 'it is only %.1f MB, too small to be a game package' % (size / 1048576.0)
    else:
        why = 'it is not an NSP or XCI package (starts with %s)' % head[:4].hex(' ')
    return '%s: cannot be read as the game: %s.' % (path, why)


class Nsp:
    """A PFS0 package (.nsp)."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        head = self.f.read(16)
        if len(head) < 16 or head[:4] != b'PFS0':
            raise SystemExit(not_a_package(path, head))
        _, count, strings_size, _ = struct.unpack('<4sIII', head)
        entries = [struct.unpack('<QQII', self.f.read(24)) for _ in range(count)]
        strings = self.f.read(strings_size)
        base = 16 + 24 * count + strings_size
        self.files = {}
        for off, size, name_off, _ in entries:
            name = strings[name_off:strings.index(b'\0', name_off)].decode()
            self.files[name] = (base + off, size)

    def read(self, name, offset, size):
        base, _ = self.files[name]
        self.f.seek(base + offset)
        return self.f.read(size)

    def program_nca(self):
        return max((n for n in self.files if n.endswith('.nca')), key=lambda n: self.files[n][1])

    def ticket(self):
        for n in self.files:
            if n.endswith('.tik'):
                return self.read(n, 0, self.files[n][1])
        return None


def hfs0_files(f, off):
    """name -> (absolute offset, size) for the HFS0 partition at `off`."""
    f.seek(off)
    magic, count, strings_size, _ = struct.unpack('<4sIII', f.read(16))
    assert magic == b'HFS0', 'HFS0 partition not found at %#x' % off
    entries = [struct.unpack('<QQII8x32s', f.read(0x40)) for _ in range(count)]
    strings = f.read(strings_size)
    base = off + 16 + 0x40 * count + strings_size
    return {strings[n:strings.index(b'\0', n)].decode(): (base + o, s) for o, s, n, _, _ in entries}


class Xci(Nsp):
    """A cartridge image: 'HEAD' at 0x100, root HFS0 offset at 0x130, game NCAs in 'secure'."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.f.seek(0x100)
        assert self.f.read(4) == b'HEAD', '%s is not an XCI' % path
        self.f.seek(0x130)
        root = hfs0_files(self.f, struct.unpack('<Q', self.f.read(8))[0])
        assert 'secure' in root, 'the XCI has no secure partition'
        self.files = hfs0_files(self.f, root['secure'][0])

    def ticket(self):
        return None


class LooseNcaPackage(Nsp):
    """A single .nca used as a one-entry package (needs title.keys if it has a rights id)."""

    def __init__(self, path):
        self.f = open(path, 'rb')
        self.files = {os.path.basename(path): (0, os.path.getsize(path))}

    def ticket(self):
        return None


def open_package(path):
    """-xci / .nsp / a loose .nca."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.xcz':
        raise SystemExit('%s: .xcz (compressed cartridge) is not supported; use a plain .xci' % path)
    if ext == '.nsz':
        raise SystemExit('%s: .nsz is compressed; decompress it to .nsp first (tools/extract/nsz_to_nsp.py)' % path)
    if ext == '.nca':
        return LooseNcaPackage(path)
    with open(path, 'rb') as f:
        f.seek(0x100)
        is_xci = f.read(4) == b'HEAD'
    return Xci(path) if is_xci else Nsp(path)


def nca_header(nsp, name):
    return xts_decrypt(KEYS['header_key'], nsp.read(name, 0, 0xC00), 0)


class Nca:
    """The Program NCA of a package, decrypted section by section."""

    def __init__(self, nsp, content_type=0):
        need_keys()
        self.nsp = nsp
        self.name = None
        # The largest NCA is not always the Program one, so pick by content type from the header.
        for n in sorted((n for n in nsp.files if n.endswith('.nca')), key=lambda n: -nsp.files[n][1]):
            hh = nca_header(nsp, n)
            if hh[0x200:0x204] == b'NCA3' and hh[0x205] == content_type:
                self.name = n
                break
        if self.name is None:
            raise SystemExit('%s: no NCA of content type %d found' % (getattr(nsp, 'path', '?'), content_type))
        h = nca_header(nsp, self.name)
        self.header = h
        self.content_type = h[0x205]
        self.title_id, = struct.unpack('<Q', h[0x210:0x218])
        gen = max(max(h[0x206], h[0x220]) - 1, 0)
        rights = h[0x230:0x240]
        if any(rights):
            tik = nsp.ticket()
            if tik and tik[0x2A0:0x2B0] == rights:
                tkey = tik[0x180:0x190]
            else:
                tkey = TITLE_KEYS.get(rights.hex())
            if not tkey:
                raise SystemExit('no ticket or title key for rights id %s' % rights.hex())
            self.key = AES.new(KEYS['titlekek_%02x' % gen], AES.MODE_ECB).decrypt(tkey)
        else:
            kak = 'key_area_key_%s_%02x' % (
                ('application', 'ocean', 'system')[h[0x207] if h[0x207] < 3 else 0], gen)
            area = AES.new(KEYS[kak], AES.MODE_ECB).decrypt(h[0x300:0x340])
            self.key = area[0x20:0x30]
        self.sections = []
        for i in range(4):
            start, end = struct.unpack('<II', h[0x240 + i * 16:0x248 + i * 16])
            if end:
                fs = h[0x400 + i * 0x200:0x600 + i * 0x200]
                self.sections.append({'index': i, 'offset': start * 0x200, 'size': (end - start) * 0x200,
                                      'fs': fs, 'type': fs[2], 'crypto': fs[4], 'ctr': fs[0x140:0x148][::-1]})

    def section(self, fs_type):
        return next(s for s in self.sections if s['type'] == fs_type)

    def section_index(self, index):
        """The section with NCA section index `index` (Meta NCAs keep their CNMT PFS0 in section 0)."""
        return next((s for s in self.sections if s['index'] == index), None)

    def read(self, sec, offset, size, ctr_val=None):
        if size <= 0:
            return b''
        absolute = sec['offset'] + offset
        aligned = absolute & ~0xF
        data = self.nsp.read(self.name, aligned, (absolute - aligned + size + 15) & ~0xF)
        upper = sec['ctr'] if ctr_val is None else sec['ctr'][:4] + struct.pack('>I', ctr_val)
        counter = int.from_bytes(upper + struct.pack('>Q', aligned >> 4), 'big')
        plain = AES.new(self.key, AES.MODE_CTR, nonce=b'', initial_value=counter).decrypt(data)
        return plain[absolute - aligned:absolute - aligned + size]

    def is_patch(self):
        try:
            return self.section(0)['crypto'] == 4
        except StopIteration:
            return False


def meta_version(nsp):
    """(title id, version) from the Meta NCA's CNMT. Version 262144 == 1.0.4 (262144 = 0x40000)."""
    try:
        meta = Nca(nsp, content_type=1)
    except SystemExit:
        return None, None
    sec = meta.section_index(0)
    if sec is None:
        return meta.title_id, None
    pfs = struct.unpack('<Q', sec['fs'][0x40:0x48])[0]
    head = meta.read(sec, pfs, 16)
    if head[:4] != b'PFS0':
        return meta.title_id, None
    count, strings_size = struct.unpack('<II', head[4:12])
    table = meta.read(sec, pfs + 16, 24 * count + strings_size)
    strings = table[24 * count:]
    data = pfs + 16 + 24 * count + strings_size
    for i in range(count):
        off, size, name_off, _ = struct.unpack('<QQII', table[i * 24:i * 24 + 24])
        name = strings[name_off:strings.index(b'\0', name_off)].decode()
        if name.endswith('.cnmt'):
            blob = meta.read(sec, data + off, size)
            tid, = struct.unpack('<Q', blob[0:8])
            ver, = struct.unpack('<I', blob[8:12])
            return tid, ver
    return meta.title_id, None


class PatchedRomfs:
    """Virtual RomFS section: update (BKTR) over base."""

    def __init__(self, base, update):
        self.base, self.update = base, update
        self.bsec = base.section(0)
        self.usec = update.section(0)
        if self.usec['crypto'] != 4:
            raise SystemExit(
                'the file given as the update is not an update of the game (its program NCA %s, title %016x, has no '
                'patch RomFS). Give the base game ([010051F0207B2000]) first and the update '
                '([010051F0207B2800], version v262144 = 1.0.4) second.' % (update.name, update.title_id))
        fs = self.usec['fs']
        assert fs[0x8:0xC] == b'IVFC'
        self.level6 = struct.unpack('<Q', fs[0x8 + 0x10 + 5 * 0x18:0x8 + 0x18 + 5 * 0x18])[0]
        r_off, r_size, r_magic = struct.unpack('<QQ4s', fs[0x100:0x114])
        s_off, s_size, s_magic = struct.unpack('<QQ4s', fs[0x120:0x134])
        assert r_magic == b'BKTR' and s_magic == b'BKTR'
        reloc = update.read(self.usec, r_off, r_size)
        subs = update.read(self.usec, s_off, s_size)
        self.total = struct.unpack('<Q', reloc[8:16])[0]
        self.rel = []
        for b in range(struct.unpack('<I', reloc[4:8])[0]):
            bucket = reloc[0x4000 * (b + 1):0x4000 * (b + 2)]
            for e in range(struct.unpack('<I', bucket[4:8])[0]):
                self.rel.append(struct.unpack('<QQI', bucket[0x10 + e * 0x14:0x24 + e * 0x14]))
        self.rel_keys = [r[0] for r in self.rel]
        self.sub = []
        for b in range(struct.unpack('<I', subs[4:8])[0]):
            bucket = subs[0x4000 * (b + 1):0x4000 * (b + 2)]
            for e in range(struct.unpack('<I', bucket[4:8])[0]):
                off, _, ctr = struct.unpack('<QII', bucket[0x10 + e * 0x10:0x20 + e * 0x10])
                self.sub.append((off, ctr))
        self.sub.append((r_off, None))  # the tables themselves use the header counter
        self.sub_keys = [s[0] for s in self.sub]
        print('virtual RomFS: %.2f GB, %d relocation entries, %d subsections'
              % (self.total / 2 ** 30, len(self.rel), len(self.sub)))

    def _read_patch(self, offset, size):
        out = []
        while size > 0:
            i = bisect.bisect_right(self.sub_keys, offset) - 1
            end = self.sub_keys[i + 1] if i + 1 < len(self.sub_keys) else offset + size
            n = min(size, end - offset)
            out.append(self.update.read(self.usec, offset, n, self.sub[i][1]))
            offset += n
            size -= n
        return b''.join(out)

    def read(self, offset, size):
        out = []
        while size > 0:
            i = bisect.bisect_right(self.rel_keys, offset) - 1
            virt, phys, patch = self.rel[i]
            end = self.rel_keys[i + 1] if i + 1 < len(self.rel) else self.total
            n = min(size, end - offset)
            if patch:
                out.append(self._read_patch(phys + offset - virt, n))
            else:
                out.append(self.base.read(self.bsec, phys + offset - virt, n))
            offset += n
            size -= n
        return b''.join(out)


class PlainRomfs:
    """The base game's own RomFS section (no update applied)."""

    def __init__(self, base):
        self.base, self.bsec = base, base.section(0)
        fs = self.bsec['fs']
        assert fs[0x8:0xC] == b'IVFC'
        self.level6 = struct.unpack('<Q', fs[0x8 + 0x10 + 5 * 0x18:0x8 + 0x18 + 5 * 0x18])[0]

    def read(self, offset, size):
        return self.base.read(self.bsec, offset, size)


def walk(romfs, base):
    """Yield (path, data offset, size) for every file of the RomFS image at `base`."""
    hdr = struct.unpack('<10Q', romfs.read(base, 0x50))
    assert hdr[0] == 0x50, 'RomFS header not found: wrong keys, or wrong base/update pair'
    dir_off, dir_size, file_off, file_size, data_off = hdr[3], hdr[4], hdr[7], hdr[8], hdr[9]
    dirs = romfs.read(base + dir_off, dir_size)
    files = romfs.read(base + file_off, file_size)
    stack = [(0, '')]
    while stack:
        d, path = stack.pop()
        _, sibling, child, first_file, _, name_len = struct.unpack('<6I', dirs[d:d + 24])
        name = dirs[d + 24:d + 24 + name_len].decode('utf8')
        here = path + '/' + name if name else path
        if sibling != 0xFFFFFFFF:
            stack.append((sibling, path))
        if child != 0xFFFFFFFF:
            stack.append((child, here))
        f = first_file
        while f != 0xFFFFFFFF:
            _, next_file, off, size, _, name_len = struct.unpack('<IIQQII', files[f:f + 32])
            fname = files[f + 32:f + 32 + name_len].decode('utf8')
            yield here + '/' + fname, base + data_off + off, size
            f = next_file


def extract_exefs(nca, out_dir):
    """The PartitionFs section (fs type 1) of a Program NCA is the ExeFS."""
    sec = nca.section(1)
    pfs = struct.unpack('<Q', sec['fs'][0x40:0x48])[0]
    head = nca.read(sec, pfs, 16)
    assert head[:4] == b'PFS0', 'no ExeFS in %s' % nca.name
    count, strings_size = struct.unpack('<II', head[4:12])
    table = nca.read(sec, pfs + 16, 24 * count + strings_size)
    strings = table[24 * count:]
    data = pfs + 16 + 24 * count + strings_size
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for i in range(count):
        off, size, name_off, _ = struct.unpack('<QQII', table[i * 24:i * 24 + 24])
        name = strings[name_off:strings.index(b'\0', name_off)].decode()
        dst = os.path.join(out_dir, name)
        with open(dst, 'wb') as f:
            pos = 0
            while pos < size:
                n = min(CHUNK, size - pos)
                f.write(nca.read(sec, data + off + pos, n))
                pos += n
        written.append((name, size))
        print('  exefs %10d  %s' % (size, name))
    return written


def extract(base, update, out_dir, list_only=False, resume=True):
    """Write the RomFS of `base` with `update` applied into out_dir. Resume skips files already complete."""
    romfs = PatchedRomfs(base, update) if update is not None else PlainRomfs(base)
    entries = sorted(walk(romfs, romfs.level6))
    total = sum(e[2] for e in entries)
    print('%d files, %.2f GB' % (len(entries), total / 2 ** 30))
    if list_only:
        for path, _, size in entries:
            print('  %14d  %s' % (size, path))
        return entries
    import time
    t0 = time.time()
    done = skipped = 0
    for path, offset, size in entries:
        target = os.path.join(out_dir, *path.strip('/').split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if resume and os.path.isfile(target) and os.path.getsize(target) == size:
            done += size
            skipped += 1
            continue
        part = target + '.part'
        with open(part, 'wb') as f:
            pos = 0
            while pos < size:
                n = min(CHUNK, size - pos)
                f.write(romfs.read(offset + pos, n))
                pos += n
                done += n
                rate = done / 2 ** 20 / max(time.time() - t0, 0.01)
                print('\r%5.1f%%  %6.1f MB/s   ' % (100.0 * done / max(total, 1), rate), end='', flush=True)
        os.replace(part, target)
    print('\n%s in %.0f s (%d files, %d skipped as already complete)'
          % (out_dir, time.time() - t0, len(entries), skipped))
    return entries


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 3:
        sys.exit(__doc__)
    print('keys:', KEYS_PATH)
    base = Nca(open_package(args[0]))
    update = Nca(open_package(args[1]))
    if base.is_patch() and not update.is_patch():
        base, update = update, base
        print('base and update were the other way round: swapped')
    print('base   title %016x  program NCA %s' % (base.title_id, base.name))
    print('update title %016x  program NCA %s' % (update.title_id, update.name))
    extract(base, update, args[2], '--list' in sys.argv)
