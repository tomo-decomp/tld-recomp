# Tomodachi Life: Living the Dream — native recompilation

A native port of *Tomodachi Life: Living the Dream* (Nintendo Switch) in the shape of the
other ports in this repository (`ACNHRecomp`, `LASRecomp`, `ssbu-recomp`, `SMWRecomp`):
the game's AArch64 code becomes host code, and the console's system and graphics calls are
re-implemented against **SDL3 + Vulkan**.

This project exists because `TomodachiLife-recomp` is Windows-only (it is written against
Win32 and needs MSVC/LLVM-clang 9). Everything here targets **Linux first**, and is written
so the same source builds on Linux, macOS and Windows.

> **This repository contains no game code, assets, keys or firmware.** Everything derived
> from the game is generated on your machine from your own dump, into `private/`, which is
> gitignored. You need your own copy of the game and your own `prod.keys`.

## What is here today

| Piece | State |
|---|---|
| Container reader (XCI, NSP, NCA3, BKTR update patching, RomFS/IVFC) — no hactool | **works**, verified against the real base XCI and update NSP |
| ExeFS extraction (base **and** update) | **works** |
| NSO0 → ELF64 for disassembly/lifting, with SHA-256 checked segments | **works** |
| Runtime skeleton: dump validation, HLE service registry, SDL3 window, Vulkan probe | **builds and runs** |
| AArch64 → C lifter | **done** — `tools/recomp` (179,435 functions, 10.34M instructions) |
| NVN → Vulkan presenter, audio, input mapping, save data | **not written yet** |

Read [docs/PLAN.md](docs/PLAN.md) for the architecture and the roadmap, and
[docs/RECON.md](docs/RECON.md) for the measured facts about this specific game.

## Requirements

- Linux (tested), or macOS / Windows with the same packages.
- Python 3.10+ with `pycryptodome`, `lz4`, `zstandard` (`pip install -r requirements.txt`).
- CMake ≥ 3.20, a C++20 compiler, SDL3 (≥ 3.2) and the Vulkan headers.

On Arch: `sudo pacman -S cmake ninja clang sdl3 vulkan-headers`.
On Debian/Ubuntu: `sudo apt install cmake ninja-build clang libsdl3-dev libvulkan-dev`.

## Use your own dump

Point the tools at your packages (defaults are this repository's `roms/switch` layout):

```sh
python3 tools/tld.py info       # title ids, versions, sections — reads headers only
python3 tools/tld.py exefs      # ExeFS of the update (1.0.4) or of the base game
python3 tools/tld.py update     # the update's ExeFS next to it, for comparison
python3 tools/tld.py elf        # main.nso -> main.elf (AArch64, Ghidra-loadable)
python3 tools/tld.py romfs      # the RomFS with the update applied (multi-GB, resumable)
```

`info` and `exefs` take seconds; `romfs` writes the whole 6.3 GB data set and can be
interrupted and resumed (`--list` shows the file table without writing anything).

Keys are found automatically in `$TLD_PROD_KEYS`, `<repo>/keys/`, `~/.switch/`, and the
yuzu/suyu/Ryujinx-style folders. Nothing is copied or printed.

## Build and check the runtime

```sh
cmake -S . -B build -G Ninja
cmake --build build -j"$(nproc)"
./build/tld_native --check --dump private/dump
```

`--check` validates the dump and prints what it found (it does not need a display, so it
also works over SSH). Without `--check` the runtime opens a window and runs the frame loop.

## Scope, honestly

A full static recompilation of a game this size is a long build: the reference projects
report 1.5–4.5 hours of compilation on a 16–32 GB, 8–24 thread machine, producing 12 GB of
build output plus several GB of shader cache. **This machine has 2 cores, 3 GB of RAM and
85 GB of free disk** — enough to extract, measure and develop here, not enough to lift and
compile the whole game in one sitting. `docs/PLAN.md` explains what that means for the
order of work.

## Credits and licence

Technique and container-parsing approach learned from `ssbu-recomp`, `ACNHRecomp`,
`LASRecomp`, `SMWRecomp` and `TomodachiLife-recomp` in this repository; SDL3 for the
platform layer. GPL-3.0, see [LICENSE](LICENSE).
*Tomodachi Life* is a trademark of Nintendo. Not affiliated with or endorsed by Nintendo.
