#!/usr/bin/env python3
"""Precompiles the game's Maxwell shaders to SPIR-V and packs them, the way ACNHRecomp's setup does
(tools/setup_acnh.py, "shaders"): the runtime then opens <data root>/spirv.pak instead of translating at boot.

usage: tools/precompile_shaders.py [game dir] [--jobs N] [--force] [--skip-translate]
       (default: private/tld; run tools/extract_shaders.py first)

  1. private/third_party/ryubing   Ryujinx's shader translator (MIT). From Codeberg: the GitHub copy was taken down,
                                   this is the same revision ACNHRecomp pins (RYUBING).
  2. private/build/spirv_harness   tools/maxwell/spirv_harness built with the .NET 10 SDK (its patches applied to
                                   copies of the two upstream files, see translator/Ryujinx.Graphics.Shader.csproj).
  3. <game>/spirv/*.spv            spirv_harness --batch over <game>/shaders_extracted (code + control per block).
     + results.tsv                 The runtime reads results.tsv for the storage buffers and uniform extents of each
                                   shader; without it those bindings are not bound (nvn_shaders.cpp).
  4. <game>/spirv.pak              tools/pack_spirv.py: the one file the runtime opens (SPK1 + index + payload).

Each step is skipped when its output is there (--force redoes it, --skip-translate only fetches and builds).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RYUBING = "a82350bb77"  # the same revision ACNHRecomp builds its translator from
URL = f"https://codeberg.org/Software_arch/Ryubing/archive/{RYUBING}.tar.gz"


def fail(msg):
    print(msg, flush=True)
    sys.exit(1)


def fetch(url, dest):
    """Downloads a .tar.gz and extracts it into dest, its single top folder removed."""
    os.makedirs(dest, exist_ok=True)
    tmp = dest + ".download"
    print(f"downloading {url}", flush=True)
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    with tarfile.open(tmp) as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue  # the archive's top folder itself
            m.name = parts[1]
            t.extract(m, dest)
    os.remove(tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", nargs="?", default=os.path.join(ROOT, "private", "tld"))
    ap.add_argument("--jobs", type=int, default=max(1, os.cpu_count() or 1))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-translate", action="store_true")
    a = ap.parse_args()
    G = os.path.abspath(a.game)

    # ---- dotnet --------------------------------------------------------------------------------------------------
    dotnet = shutil.which("dotnet")
    if not dotnet:
        fail("dotnet not found: the shader translator is .NET (SDK 10; https://dotnet.microsoft.com/download)")
    sdks = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True).stdout
    if not any(l.startswith("10.") for l in sdks.splitlines()):
        fail(f"the .NET SDK 10 is needed for the shader translator, found:\n{sdks.strip()}")

    # ---- 1. the translator's source ------------------------------------------------------------------------------
    ryu = os.path.join(ROOT, "private", "third_party", "ryubing")
    if a.force and os.path.isdir(ryu):
        shutil.rmtree(ryu)
    if not os.path.exists(os.path.join(ryu, "src", "Ryujinx.sln")):
        fetch(URL, ryu)
    print(f"translator source: {ryu} (Ryubing {RYUBING})")

    # ---- 2. spirv_harness ---------------------------------------------------------------------------------------
    harness = os.path.join(ROOT, "private", "build", "spirv_harness", "bin", "Release", "net10.0", "spirv_harness.dll")
    if a.force or not os.path.exists(harness):
        env = dict(os.environ)
        env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        proj = os.path.join(ROOT, "tools", "maxwell", "spirv_harness", "SpirvHarness.csproj")
        log = os.path.join(ROOT, "private", "build", "harness.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        print("building spirv_harness (a few minutes, once)", flush=True)
        with open(log, "w") as f:
            rc = subprocess.call([dotnet, "build", proj, "-c", "Release", "-m:2"], stdout=f, stderr=subprocess.STDOUT,
                                 env=env)
        if rc or not os.path.exists(harness):
            with open(log, errors="replace") as f:
                print("".join(f.readlines()[-30:]))
            fail(f"the shader translator did not build (log: {log})")
    print(f"harness: {harness}")
    if a.skip_translate:
        return

    # ---- 3. the blocks to SPIR-V ---------------------------------------------------------------------------------
    src = os.path.join(G, "shaders_extracted")
    out = os.path.join(G, "spirv")
    if not os.path.isdir(src):
        fail(f"no {src}: run tools/extract_shaders.py {os.path.relpath(G, ROOT)} first")
    summary = os.path.join(out, "summary.txt")
    if a.force or not os.path.exists(summary):
        os.makedirs(out, exist_ok=True)
        val = [["--spirv-val", shutil.which("spirv-val")]] if shutil.which("spirv-val") else [["--no-val"]]
        log = os.path.join(ROOT, "private", "build", "spirv.log")
        print(f"translating {src} -> {out} ({a.jobs} jobs)", flush=True)
        with open(log, "w") as f:
            rc = subprocess.call([dotnet, harness, "--batch", src, "--out", out, "--jobs", str(a.jobs)] + val[0],
                                 stdout=f, stderr=subprocess.STDOUT)
        if rc:
            with open(log, errors="replace") as f:
                print("".join(f.readlines()[-30:]))
            fail(f"the translation failed (log: {log})")
    with open(summary, errors="replace") as f:
        print("  " + (f.readline().strip() or "no summary"))
    n = len([f for f in os.listdir(out) if f.endswith(".spv")])
    if not n:
        fail(f"no .spv in {out}: nothing was translated (see private/build/spirv.log)")
    if not os.path.exists(os.path.join(out, "results.tsv")):
        print("  warning: no results.tsv: storage and uniform bindings of the translated shaders stay unbound")

    # ---- 4. spirv.pak -------------------------------------------------------------------------------------------
    pak = os.path.join(G, "spirv.pak")
    if a.force or not os.path.exists(pak) or os.path.getmtime(pak) < os.path.getmtime(os.path.join(out, "results.tsv")
                                                                                        if os.path.exists(
                                                                                            os.path.join(out, "results.tsv"))
                                                                                        else summary):
        subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "pack_spirv.py"), out, pak])
    print(f"done: {n} shaders, {pak}")


if __name__ == "__main__":
    main()
