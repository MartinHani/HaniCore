"""The TunerStudio plugin's connect engine (AutoConnect) against the REAL
firmware KWP core - no TunerStudio, no hardware.

tests/host/hckline_ecu_sim.c links firmware/comms/hckline.c (the object in the image)
behind a modelled UART / 5-baud decoder / rate follower; the Java tests drive
it through HcklineSimLine. The engine is compiled for Java 8, the runtime
TunerStudio 3.3.01 ships (runtime8). SerialPortLine and the plugin glue need
TunerStudio's jars and are compiled by tools/tunerstudio/plugin/build_plugin.py.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import host_c_test as H


SRC = H.ROOT / "tools" / "tunerstudio" / "plugin" / "src" / "com" / "hanicore" / "tunerstudio"
TST = H.ROOT / "tools" / "tunerstudio" / "plugin" / "test" / "com" / "hanicore" / "tunerstudio"
OUT = H.TMP / "plugin_test_classes"
ENGINE = ["Line", "HcProtocol", "AutoConnect", "SilenceWatch", "ReplyWatch", "Backoff", "RetryPolicy"]
TESTS = ["HcklineSimLine", "AdapterLine", "AutoConnectTests"]

JDK = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot\bin")


def jdk_tool(name: str) -> str | None:
    if shutil.which(name):
        return name
    exe = JDK / (name + ".exe")
    return str(exe) if exe.exists() else None


def main() -> int:
    javac, java = jdk_tool("javac"), jdk_tool("java")
    cc = H.compiler()
    if not javac or not java or cc is None:
        print("SKIP: need a JDK and a host C compiler")
        return 0
    env = H.env_for(cc)
    H.TMP.mkdir(exist_ok=True)
    sim = H.TMP / "hckline_ecu_sim.exe"
    H.build(cc, env, [H.HCP.find("hckline.c"), H.HOST_TESTS / "hckline_ecu_sim.c"],
            H.SHARED, sim)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    files = [str(SRC / (n + ".java")) for n in ENGINE] + \
            [str(TST / (n + ".java")) for n in TESTS]
    subprocess.run([javac, "--release", "8", "-Xlint:-options", "-d", str(OUT)]
                   + files, check=True)
    subprocess.run([java, "-Dhc.sim=" + str(sim), "-cp", str(OUT),
                    "com.hanicore.tunerstudio.AutoConnectTests"], check=True,
                   env=env)
    print("PASS: AutoConnect vs hckline.c")
    return control(javac, java, sim, env)


def control(javac, java, sim, env) -> int:
    """NEGATIVE CONTROL: the engine as it was before V97 demanded "HANICORE"
    in the IDENTIFY payload; the firmware sends the TunerStudio signature
    (hckwp_me711.c KW_SIG). That engine must fail this suite."""
    mdir = H.TMP / "plugin_mutant"
    if mdir.exists():
        shutil.rmtree(mdir)
    (mdir / "src").mkdir(parents=True)
    (mdir / "out").mkdir()
    old = "HcProtocol.containsAscii(sig, HcProtocol.IDENTITY)"
    files = []
    for n in ENGINE:
        text = (SRC / (n + ".java")).read_text()
        if n == "AutoConnect":
            assert text.count(old) == 1, "mutation point moved - update the control"
            text = text.replace(old, 'HcProtocol.containsAscii(sig, "HANICORE")')
        (mdir / "src" / (n + ".java")).write_text(text)
        files.append(str(mdir / "src" / (n + ".java")))
    files += [str(TST / (n + ".java")) for n in TESTS]
    subprocess.run([javac, "--release", "8", "-Xlint:-options", "-d",
                    str(mdir / "out")] + files, check=True)
    r = subprocess.run([java, "-Dhc.sim=" + str(sim), "-cp", str(mdir / "out"),
                        "com.hanicore.tunerstudio.AutoConnectTests"],
                       env=env, capture_output=True, text=True)
    if r.returncode == 0:
        print("FAIL: control - the pre-V97 'HANICORE' engine passed")
        return 1
    first = [ln for ln in r.stdout.splitlines() if "FAIL:" in ln][:1]
    print("PASS: control - the pre-V97 'HANICORE' engine fails (%s)"
          % (first[0].strip() if first else "exit %d" % r.returncode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
