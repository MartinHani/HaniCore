"""The shared runner behind tools/test_*_host.py: find a host C compiler,
build an SFR-free core against its tests/host/ test with -std=c89 -Wall
-Wextra -Werror, run it. A missing compiler is a SKIP (exit 0)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402
# The portable firmware directories: an SFR-free core and its siblings.
SHARED = HCP.PORTABLE_DIRS
HOST_TESTS = ROOT / "tests" / "host"
TMP = ROOT / "build" / "host"      # gitignored build output

# Well-known local toolchains, tried after PATH.
EXTRA = [r"C:\msys64\mingw64\bin\gcc.exe"]
STRICT = ("-Wall", "-Wextra", "-Werror")


def compiler() -> str | None:
    for candidate in (os.environ.get("CC"), "clang", "gcc", "cc"):
        if candidate and shutil.which(candidate):
            return candidate
    for candidate in EXTRA:
        if Path(candidate).exists():
            return candidate
    return None


def env_for(cc: str) -> dict:
    """A mingw gcc invoked by full path still needs its own bin/ on PATH to
    load libwinpthread/libgcc DLLs at both compile and run time."""
    env = dict(os.environ)
    if ("/" in cc) or ("\\" in cc):
        env["PATH"] = str(Path(cc).parent) + os.pathsep + env.get("PATH", "")
    return env


def build(cc: str, env: dict, sources, include, exe: Path,
          flags=STRICT) -> None:
    dirs = include if isinstance(include, (list, tuple)) else [include]
    Path(exe).parent.mkdir(parents=True, exist_ok=True)   # fresh clone: no build/
    subprocess.run([cc, "-std=c89", *flags,
                    *[a for d in dirs for a in ("-I", str(d))],
                    *map(str, sources), "-o", str(exe)], check=True, env=env)


def run(name: str, sources, include=SHARED):
    """Build and run; returns (cc, env) for a caller's own controls, or None
    when there is no compiler (already reported as SKIP)."""
    cc = compiler()
    if cc is None:
        print("SKIP: no C host compiler found (tried CC, clang, gcc, cc, msys64)")
        return None
    TMP.mkdir(parents=True, exist_ok=True)
    env = env_for(cc)
    exe = TMP / ("hc_%s_host.exe" % name)
    build(cc, env, sources, include, exe)
    subprocess.run([str(exe)], check=True, env=env)
    print("PASS: %s host tests" % name)
    return cc, env
