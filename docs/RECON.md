# Measured facts about this game

Everything below was read from the two packages in this repository's `roms/switch/` with
`tools/tld.py` (pure-Python NCA parsing — no hactool, no emulator). Reproduce it with:

```sh
python3 tools/tld.py info
python3 tools/tld.py exefs && python3 tools/tld.py update && python3 tools/tld.py elf
python3 -m recomp private/tld/exefs/main /tmp/stats --stats
```

## Titles

| | Base (cartridge) | Update |
|---|---|---|
| File | `tomodachi.xci`, 7,985,954,816 bytes | `tomodachi1.0.4.nsp`, 75,611,415 bytes |
| Title ID (CNMT) | `010051F0207B2000` | `010051F0207B2800` |
| Version | `v0` → 1.0.0 | `v262144` → 1.0.4 |
| Program NCA | `daca090007dd485a4e3c05f9f742be8a.nca` | `2cfedbda901f01cd0787dafc1f5dfde8.nca` |
| Section 0 | PFS0 (ExeFS), 38.2 MB, crypto 3 | PFS0 (ExeFS), 38.0 MB, crypto 3 |
| Section 1 | RomFS, **6,328.9 MB**, crypto 3 | RomFS **patch** (BKTR, crypto 4), 33.0 MB |

The update is a **BKTR delta**: 33 MB of patch data over the base RomFS, not a second copy
of the 6.3 GB. `tools/extract/romfs_extract.py` resolves it by walking the relocation table,
so the extracted RomFS is the 1.0.4 data set. `update patches base: yes` in `tld.py info`
confirms the pair.

## Executable code

Both versions carry the same module layout (`main`, `sdk`, `rtld`, `main.npdm`):

| Module | Base 1.0.0 | Update 1.0.4 |
|---|---|---|
| `main` NSO size | 33,801,155 B | 33,566,571 B |
| `main` SHA-256 | `753da2a7…21a2f2` | `54d55267…2080a2` |
| `main` build id | `56bf85bd535413464cb75bb6c2683b6711e0bc0b` | (differs) |
| `main` `.text` | 39,642,784 B (0x25CE6A0) | — |
| `main` `.rodata` / `.data` | 10,794,104 B / 6,890,948 B | — |
| `main` exported symbols | 810 | — |
| `sdk` NSO | 6,198,560 B, `.text` 6,692,848 B | identical size |
| `sdk` exported symbols | 23,034 | — |

`main` is the game; `sdk` is Nintendo's own SDK runtime compiled into the title, which means
part of what other ports have to emulate is present as code and can simply be recompiled.

## What this means for the port

- **The data set is the big number, not the code.** 6.3 GB of RomFS against 38 MB of ExeFS:
  the port has to read the game's archives natively, and the shader translation is the
  expensive graphics job (that is where the reference ports spend their multi-GB caches).
- **Two code versions exist and both must work**, as in `ssbu-recomp` (13.0.4 / 13.0.5): the
  layout is identical, only the bytes differ, so the lifter output per version is a separate
  build directory rather than a separate tool.
- **`sdk` is 23,034 exported functions of Nintendo runtime.** The HLE surface the game
  actually needs is a subset of that, discovered by running and logging missing requests —
  which is what `runtime/src/hle.cpp` is built to report.
