# Plan

## The shape of the port

This is the shape the reference ports in this repository converged on, and it is the shape
this project will follow:

```
your dump                       tools/                       runtime/
  exefs/main   (NSO0)  ──▶  nso2elf.py  ──▶  main.elf
                                                │
                                          tools/recomp
                                                │  one C function per game function
                                                ▼
                                          libtld_game.so
                                                │
  romfs/        (6.3 GB) ──▶  archive readers ──┤
                                                ▼
                        runtime: HLE services (nn::*), NVN → Vulkan, SDL3 audio/input
```

Three separate jobs, deliberately kept apart:

1. **Lift** — mechanical AArch64 → C (`tools/recomp/lifter.py`). Not readable source: one C
   statement per instruction, one C function per game function. It produces 90 files and
   394 MB of C for this game, which is why the build is the long pole.
2. **HLE** — re-implement what the console provided. Grows by running the game and logging
   the requests that came back unimplemented: `runtime/src/hle.cpp` already records them
   (`Hle::missing()`), which is the feedback loop the whole port is built on.
3. **Graphics** — translate NVN command buffers to Vulkan and the game's shaders to SPIR-V.
   This is the largest single piece and the one that decides performance.

## Why Linux first

`TomodachiLife-recomp` is written against Win32 (`VirtualAlloc`, `GetWriteWatch`, Win32
threads, Media Foundation); its own Linux notes say the runtime is kept on the Windows API
and supplied by a compatibility layer. That is a reasonable design, but it makes Linux a
port of a port.

Here the platform layer is **SDL3** (`runtime/src/platform_sdl.cpp`) — one implementation for
Linux, macOS and Windows — and nothing above it touches Win32. Files, threads and memory use
the C++ standard library and POSIX where needed. Vulkan is loaded through SDL at runtime, so
there is no link-time dependency on a system Vulkan loader.

## Order of work

| # | Step | State |
|---|---|---|
| 1 | Container reader: XCI, NSP, NCA3, BKTR update patching, RomFS | **done, verified on this game** |
| 2 | ExeFS for base and update; NSO0 → ELF64 with checksum validation | **done** |
| 3 | Sizing pass over `.text` | **done** (`python3 -m recomp <main> <out> --stats`) |
| 4 | HLE registry with a missing-request log | **done (skeleton)** |
| 5 | SDL3 window + Vulkan probe, `--check` without a display | **done** |
| 6 | Lifter: AArch64 → C (`tools/recomp`), driven by `tools/setup_tld.py` | **done**: 179,435 functions, 10.34M instructions |
| 7 | Archive readers for the RomFS formats this game uses (`tools/inventory.py` names them) | inventory done; readers next |
| 8 | NVN → Vulkan command replay; Maxwell shader → SPIR-V | after 6–7 |
| 9 | Boot to the title screen; then the island | milestone |
| 10 | Audio (SDL3), input mapping, save data | after 9 |

## Hardware reality on this machine

The reference ports document 16–32 GB RAM and 8–24 threads for the build step alone
(`ssbu-recomp`: ~1.5 h for 1,161 files at 4 jobs, 12 GB of build output; `SMWRecomp`: 250k
functions, 1.4 GB of generated C++). **This machine has 2 cores, 3 GB of RAM and 85 GB of
free disk.**

That is enough for steps 1–9's *development and verification* — the extraction, the ELF, the
instruction statistics, the lifter on subsets of `.text`, the HLE service loop — but not for
lifting and compiling the whole game in one session. Step 6 is therefore built to work
**per function range**, so the port can be exercised on a slice of `.text` (a few thousand
functions) long before the multi-hour full build is run on a bigger machine.

## Risks, named

- **Shaders.** A 6.3 GB data set implies a large shader set; translating it is where the
  reference ports spend most of their build time and disk. Expected to be the long pole.
- **Two versions.** 1.0.0 and 1.0.4 have different bytes at identical layout. Supporting
  both means two build directories, not two code bases — but the lifter must be re-run per
  version and the HLE surface verified on both.
- **`sdk` overlap.** The title carries 6.2 MB of Nintendo's own SDK code with 23,034 exports.
  Some of what other ports emulate is present here as code; deciding what to recompile vs.
  re-implement is a per-service judgement, and getting it wrong shows up as subtle
  behavioural differences rather than crashes.
- **Local Play.** The Mii exchange feature is network code. Out of scope until the single
  player game boots.
