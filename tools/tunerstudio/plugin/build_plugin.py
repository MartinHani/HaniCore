"""Build the HaniCore K-Line TunerStudio plugin jar.

    py tools\\tunerstudio\\plugin\\build_plugin.py [--ts "<TunerStudio folder>"]
    py tools\\tunerstudio\\plugin\\build_plugin.py --verify    rebuild, compare with tunerstudio/plugin/

1. tests/unit/test_plugin_auto.py (the engine against the firmware KWP core, and
   its negative control) must pass;
2. TsCompatCheck: every TunerStudio internal the plugin reflects on exists in
   the installed TunerStudioMS.jar; after compiling, EchoTransportTest runs
   the real echo transport on a modelled lossy K-line (2.2.0 fails it);
3. javac --release 8 (TunerStudio 3.3.01 runs its bundled Java 8) against
   TunerStudioPluginAPI.jar and lib/jssc.jar;
4. tools/tunerstudio/plugin/dist/HaniCore_KLine_Transport_<version>.jar:
   the ApplicationPlugin manifest and the compiled classes only, with fixed
   entry order and timestamps, so the same sources and JDK give the same
   bytes; plus <jar>.json recording the source hashes, the JDK and the jars
   it was compiled against. --publish copies both to tunerstudio/plugin/,
   the published binary; --verify rebuilds and compares with it.

Install: TunerStudio > Tools > TunerStudio Plugins > Add or Update a Plugin,
restart TunerStudio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import test_plugin_auto as T  # noqa: E402

SRC = HERE / "src" / "com" / "hanicore" / "tunerstudio"
TST = HERE / "test" / "com" / "hanicore" / "tunerstudio"
DIST = HERE / "dist"
TS_DEFAULT = Path(r"C:\Program Files (x86)\EFIAnalytics\TunerStudioMS")
MAIN = "com.hanicore.tunerstudio.HaniCoreKLinePlugin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", type=Path, default=TS_DEFAULT)
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--publish", action="store_true",
                    help="copy the jar and its record to tunerstudio/plugin/")
    ap.add_argument("--verify", action="store_true",
                    help="rebuild and compare with tunerstudio/plugin/")
    a = ap.parse_args()
    javac, java = T.jdk_tool("javac"), T.jdk_tool("java")
    jar_tool = T.jdk_tool("jar")
    if not javac or not java:
        raise SystemExit("no JDK")
    api = a.ts / "lib" / "TunerStudioPluginAPI.jar"
    jssc = a.ts / "lib" / "jssc.jar"
    tsjar = a.ts / "TunerStudioMS.jar"
    for f in (api, jssc, tsjar):
        if not f.exists():
            raise SystemExit(f"missing {f}")
    if not a.skip_tests and T.main() != 0:
        raise SystemExit("FAIL: engine tests")

    out = ROOT / "build" / "plugin"
    if out.exists():
        shutil.rmtree(out)
    (out / "classes").mkdir(parents=True)
    (out / "check").mkdir()
    sep = ";" if sys.platform == "win32" else ":"

    # 2. TunerStudio internals
    subprocess.run([javac, "--release", "8", "-Xlint:-options", "-d",
                    str(out / "check"), str(TST / "TsCompatCheck.java")], check=True)
    subprocess.run([java, "-cp", sep.join([str(out / "check"), str(tsjar),
                                           str(jssc), str(api)]),
                    "com.hanicore.tunerstudio.TsCompatCheck"], check=True)

    # 3. compile
    version = re.search(r'VERSION = "([^"]+)"',
                        (SRC / "HaniCoreKLinePlugin.java").read_text()).group(1)
    srcs = sorted(str(p) for p in SRC.glob("*.java"))
    subprocess.run([javac, "--release", "8", "-Xlint:-options", "-d",
                    str(out / "classes"), "-cp",
                    sep.join([str(api), str(jssc), str(tsjar)])] + srcs, check=True)

    # 3b. the REAL echo transport on a lossy K-line (a lost request is sent
    #     again, a corrupted echo dropped, a Burn never repeated)
    (out / "test").mkdir()
    cp = sep.join([str(out / "classes"), str(api), str(jssc), str(tsjar)])
    subprocess.run([javac, "--release", "8", "-Xlint:-options", "-d",
                    str(out / "test"), "-cp", cp,
                    str(TST / "EchoTransportTest.java")], check=True)
    if not a.skip_tests:
        subprocess.run([java, "-cp", sep.join([cp, str(out / "test")]),
                        "com.hanicore.tunerstudio.EchoTransportTest"], check=True)

    # 4. jar
    DIST.mkdir(exist_ok=True)
    jar = DIST / f"HaniCore_KLine_Transport_{version}.jar"
    manifest = ("Manifest-Version: 1.0\r\n"
                f"ApplicationPlugin: {MAIN}\r\n"
                "Implementation-Title: HaniCore K-Line Transport\r\n"
                f"Implementation-Version: {version}\r\n\r\n")
    def entry(name):
        zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        return zi
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr(entry("META-INF/MANIFEST.MF"), manifest)
        for c in sorted((out / "classes").rglob("*.class")):
            z.writestr(entry(c.relative_to(out / "classes").as_posix()),
                       c.read_bytes())
    if jar_tool:
        subprocess.run([jar_tool, "tf", str(jar)], check=True,
                       capture_output=True)            # a readable jar
    sha = hashlib.sha256(jar.read_bytes()).hexdigest().upper()
    jdk = subprocess.run([javac, "-version"], capture_output=True, text=True)
    rec = {
        "jar": jar.name, "version": version, "sha256": sha,
        "javac": (jdk.stdout or jdk.stderr).strip(), "release": 8,
        "sources": {p.relative_to(ROOT).as_posix():
                    hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(SRC.glob("*.java"))},
        "compiled_against": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                             for f in (api, jssc, tsjar)},
        "bundles": "HaniCore classes only; TunerStudio and JSSC are not included",
        "build": "py tools/tunerstudio/plugin/build_plugin.py",
    }
    (DIST / (jar.name + ".json")).write_bytes((json.dumps(rec, indent=1) + "\n").encode())
    print(f"PASS: {jar.relative_to(ROOT)}  {sha}")
    pub = ROOT / "tunerstudio" / "plugin"
    if a.verify:
        ref = pub / jar.name
        if not ref.exists():
            raise SystemExit(f"FAIL: no published {ref.relative_to(ROOT)}")
        want = hashlib.sha256(ref.read_bytes()).hexdigest().upper()
        if want == sha:
            print(f"VERIFIED: {ref.relative_to(ROOT)} is byte-identical to this build")
            return 0
        old = json.loads((pub / (jar.name + ".json")).read_text())
        print(f"DIFFERENT: published {want}, rebuilt {sha}")
        print(f"  published with {old.get('javac')}, rebuilt with {rec['javac']}")
        moved = [k for k, v in rec["sources"].items() if old["sources"].get(k) != v]
        print("  sources changed since publishing: %s" % (moved or "none"))
        return 1
    if a.publish:
        pub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jar, pub / jar.name)
        shutil.copy2(DIST / (jar.name + ".json"), pub / (jar.name + ".json"))
        print(f"published to {pub.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
