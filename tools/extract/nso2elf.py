"""NSO0 -> ELF64 (AArch64) so a disassembler or a lifter can read the game's own code.

    python nso2elf.py <main.nso> <main.elf>

Unpacks the three LZ4 segments, checks each against its SHA-256, reads MOD0's dynamic table
for .dynsym/.dynstr, and writes an ET_DYN image with .text/.rodata/.dynsym/.dynstr/.data/
.dynamic/.bss/.shstrtab. Sections are laid out so none nest inside another: Ghidra misreads
.dynsym/.dynstr when they sit inside .rodata.
"""
import hashlib
import struct
import sys

try:
    import lz4.block
except ImportError:
    sys.exit('lz4 is required: pip install lz4')

OFF = 0x1000  # file offset of guest address 0


def unpack_nso(data):
    """-> (segments [(vaddr, bytes)], bss_size, build_id)."""
    if data[:4] != b'NSO0':
        raise SystemExit('not an NSO0 (magic %r)' % data[:4])
    flags, = struct.unpack('<I', data[12:16])
    segs = []
    for i, (ho, cso) in enumerate(((0x10, 0x60), (0x20, 0x64), (0x30, 0x68))):
        foff, moff, size = struct.unpack('<III', data[ho:ho + 12])
        csz, = struct.unpack('<I', data[cso:cso + 4])
        raw = data[foff:foff + csz]
        if flags & (1 << i):
            raw = lz4.block.decompress(raw, uncompressed_size=size)
        if len(raw) != size:
            raise SystemExit('segment %d: got %d bytes, header says %d' % (i, len(raw), size))
        ok = hashlib.sha256(raw).digest() == data[0xA0 + i * 0x20:0xC0 + i * 0x20]
        print('  seg%d vaddr %08x size %9d sha256 %s' % (i, moff, size, 'OK' if ok else 'MISMATCH'))
        segs.append((moff, raw))
    bss, = struct.unpack('<I', data[0x3c:0x40])
    return segs, bss, data[0x40:0x54]


def dynamic_info(mem, text):
    """-> dict of MOD0 dynamic tags (6 = dynsym, 5 = dynstr, 10 = strsz, 4 = hash)."""
    mod0, = struct.unpack('<I', text[4:8])
    if mem[mod0:mod0 + 4] != b'MOD0':
        raise SystemExit('MOD0 not found at %#x (needed for .dynsym/.dynstr)' % mod0)
    dyn_off, _, _ = struct.unpack('<iii', mem[mod0 + 4:mod0 + 16])
    dyn = mod0 + dyn_off
    tags, n = {}, 0
    while True:
        t, v = struct.unpack('<qQ', mem[dyn + n * 16:dyn + n * 16 + 16])
        n += 1
        if t == 0:
            break
        tags.setdefault(t, v)
    return dyn, tags, n * 16


def convert(src, dst):
    data = open(src, 'rb').read()
    segs, bss, build_id = unpack_nso(data)
    print('  build id', build_id.hex())
    (tv, text), (rv, ro), (dv, data_seg) = segs
    mem = bytearray(dv + len(data_seg))
    for v, r in segs:
        mem[v:v + len(r)] = r

    dyn, tags, dynsz = dynamic_info(mem, text)
    symtab, strtab, strsz = tags[6], tags[5], tags[10]
    nsym = struct.unpack('<I', mem[tags[4] + 4:tags[4] + 8])[0] if 4 in tags else (strtab - symtab) // 24
    print('  dynamic %#x  dynsym %#x (%d syms)  dynstr %#x' % (dyn, symtab, nsym, strtab))
    if not (rv <= symtab and symtab + nsym * 24 <= strtab):
        raise SystemExit('unexpected .dynsym/.dynstr placement; refusing to guess a layout')

    names = b'\0'
    secs = []

    def section(name, typ, flags, addr, off, size, link=0, info=0, align=1, ent=0):
        nonlocal names
        ni = len(names)
        names += name.encode() + b'\0'
        secs.append(struct.pack('<IIQQQQIIQQ', ni, typ, flags, addr, off, size, link, info, align, ent))

    section('', 0, 0, 0, 0, 0)  # SHT_NULL
    section('.text', 1, 6, tv, OFF + tv, len(text), align=16)
    section('.rodata', 1, 2, rv, OFF + rv, symtab - rv, align=16)
    section('.dynsym', 11, 2, symtab, OFF + symtab, nsym * 24, link=4, info=1, align=8, ent=24)
    section('.dynstr', 3, 2, strtab, OFF + strtab, strsz)
    r1 = strtab + strsz
    section('.rodata.1', 1, 2, r1, OFF + r1, rv + len(ro) - r1, align=1)
    section('.data', 1, 3, dv, OFF + dv, dyn - dv, align=16)
    section('.dynamic', 6, 3, dyn, OFF + dyn, dynsz, link=4, align=8, ent=16)
    d1 = dyn + dynsz
    section('.data.1', 1, 3, d1, OFF + d1, dv + len(data_seg) - d1, align=1)
    section('.bss', 8, 3, bss_end(dv, data_seg, bss)[0], OFF + dv + len(data_seg),
            bss_end(dv, data_seg, bss)[1] - bss_end(dv, data_seg, bss)[0], align=16)
    shstr_idx = len(secs)
    shstr_off = OFF + len(mem)
    section('.shstrtab', 3, 0, 0, shstr_off, 0)
    secs[-1] = secs[-1][:32] + struct.pack('<Q', len(names)) + secs[-1][40:]

    shoff = (shstr_off + len(names) + 7) & ~7

    def phdr(t, fl, v, fsz, msz, al):
        return struct.pack('<IIQQQQQQ', t, fl, OFF + v, v, v, fsz, msz, al)

    ph = phdr(1, 5, tv, len(text), len(text), 0x1000)
    ph += phdr(1, 4, rv, len(ro), len(ro), 0x1000)
    ph += phdr(1, 6, dv, len(data_seg), max(len(data_seg), bss_end(dv, data_seg, bss)[1] - dv), 0x1000)
    ph += phdr(2, 6, dyn, dynsz, dynsz, 8)
    eh = b'\x7fELF\x02\x01\x01' + bytes(9) + struct.pack(
        '<HHIQQQIHHHHHH', 3, 183, 1, 0, 0x40, shoff, 0, 0x40, 0x38, 4, 0x40, len(secs), shstr_idx)

    out = bytearray(eh + ph)
    out += bytes(OFF - len(out))
    out += mem
    out += names
    out += bytes(shoff - len(out))
    out += b''.join(secs)
    open(dst, 'wb').write(out)
    print('  wrote %s (%d bytes)' % (dst, len(out)))
    return len(out)


def bss_end(dv, data_seg, bss):
    """(start, end) of the zero-filled area that follows the data segment."""
    start = dv + len(data_seg)
    return start, max(start, bss)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    convert(sys.argv[1], sys.argv[2])
