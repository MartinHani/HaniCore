"""The 2026-11-04 CAN core additions (firmware/comms/hccan.c) on gcc:
ABS emulation frames (Bremse_1 / Bremse_3) decoded with opendbc vw_pq.dbc,
Allrad_1 encoded with the DBC and decoded by the core, the two wideband
formats built here from their published layouts (rusEFI wideband_can.h
StandardData, little-endian; AEM X-series, big-endian + valid/fault bits),
the Haldex offset controller's properties, and OBD-II mode 01 against SAE
J1979 formulas written here. Mutation controls must fail; Keil MEDIUM must
not pull a ?C_ helper (shared with test_hccan_host's check).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import host_c_test as H
import test_hccan_host as T1

SOURCE = H.HCP.find("hccan.c")
TEST = H.HOST_TESTS / "test_hccan2.c"

CONTROLS = [
    ("brake_bit10", "brake light on bit 10",
     "    d[1] = (unsigned char)(brake ? 0x08u : 0u);               /* bit 11 */",
     "    d[1] = (unsigned char)(brake ? 0x04u : 0u);"),
    ("aem_little", "AEM lambda read little-endian",
     "    raw = (unsigned int)(((unsigned int)d[0] << 8) | (unsigned int)d[1]);",
     "    raw = (unsigned int)(((unsigned int)d[1] << 8) | (unsigned int)d[0]);"),
    ("rusefi_no_valid", "rusEFI valid byte ignored",
     "    if (d[0] < HCCAN_WB_VERSION || d[0] > HCCAN_WB_VERSION || !(d[1] & 1u)) {",
     "    if (d[0] < HCCAN_WB_VERSION || d[0] > HCCAN_WB_VERSION) {"),
    ("hx_ff_inverted", "Haldex feed-forward from the wrong end",
     "                            + DIV32U((unsigned long)(full_x10 - no_x10) * want_x10, 1000u));",
     "                            + DIV32U((unsigned long)(full_x10 - no_x10) * (1000u - want_x10), 1000u));"),
    ("obd_rpm_x2", "OBD rpm x2 instead of x4",
     "        v = (o->rpm > 16383u) ? 65535u : (unsigned int)(o->rpm * 4u);",
     "        v = (o->rpm > 16383u) ? 65535u : (unsigned int)(o->rpm * 2u);"),
]


class Core:
    def __init__(self, exe, env):
        self.p = subprocess.Popen([str(exe)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=env)

    def q(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return self.p.stdout.readline().strip()

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def close(self):
        self.p.stdin.close()
        self.p.wait()


def obd(c, pid, **kw):
    v = dict(rpm=0, vss=0xFFFF, clt=10000, iat=10000, map=1000, baro=1000, tps=0,
             adv=0, load=0, lam=0, vbat=12000, run=0, mil=0, ndtc=0)
    v.update(kw)
    r = c.q("obd %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d" % (
        pid, v["rpm"], v["vss"], v["clt"], v["iat"], v["map"], v["baro"], v["tps"],
        v["adv"], v["load"], v["lam"], v["vbat"], v["run"], v["mil"], v["ndtc"]))
    n, _, hx = r.partition(" ")
    return bytes.fromhex(hx) if int(n) else b""


def checks(exe, env, dbc) -> list[str]:
    fails = []

    def ok(cnd, what):
        if not cnd:
            fails.append(what)

    c = Core(exe, env)
    # --- ABS emulation: decode the core's frames with the DBC
    for vss, brake in ((0, 0), (523, 1), (2504, 0)):
        d = bytes.fromhex(c.q("b1 %d %d 7" % (vss, brake)))
        ok(abs(T1.sig(dbc, 416, "BR1_Rad_kmh", d) - vss / 10.0) < 0.02,
           "Bremse_1 speed %d -> %.2f" % (vss, T1.sig(dbc, 416, "BR1_Rad_kmh", d)))
        ok(T1.sig(dbc, 416, "BR1_Lichtschalt", d) == brake, "Bremse_1 brake %d" % brake)
        ok(T1.sig(dbc, 416, "BR1_Zaehler", d) == 7, "Bremse_1 counter")
    w = (1003, 1001, 987, 991)
    d = bytes.fromhex(c.q("b3 %d %d %d %d" % w))
    for name, want in zip(("Radgeschw__VL_4_1", "Radgeschw__VR_4_1",
                           "Radgeschw__HL_4_1", "Radgeschw__HR_4_1"), w):
        ok(abs(T1.sig(dbc, 1184, name, d) - want / 10.0) < 0.02, "Bremse_3 " + name)
    # --- Allrad_1 from the DBC
    for pct in (0.0, 40.0, 100.0):
        hx = T1.encode(dbc, 704, {"Kupplungssteifigkeit_Hinten__Is": pct,
                                   "Notlauf": 1, "Kupplung_komplett_offen": 0})
        lk, st = map(int, c.q("al " + hx).split())
        ok(abs(lk / 10.0 - pct) <= 0.8, "Allrad_1 lock %.0f %% -> %.1f" % (pct, lk / 10.0))
        ok(st & 0x10, "Allrad_1 limp bit")
    # --- wideband: rusEFI StandardData (LE), AEM (BE)
    def rus(ver, valid, lam):
        raw = round(lam * 10000)
        return bytes([ver, valid, raw & 0xFF, raw >> 8, 0x2C, 0x03, 0, 0]).hex()
    ok(c.q("wbr " + rus(0xA0, 1, 0.873)) == "873", "rusEFI lambda 0.873")
    ok(c.q("wbr " + rus(0xA0, 0, 0.873)) == "0", "rusEFI not valid -> 0")
    ok(c.q("wbr " + rus(0xA1, 1, 0.873)) == "0", "rusEFI newer protocol -> 0")

    def aem(lam, valid, fault):
        raw = round(lam * 10000)
        return bytes([raw >> 8, raw & 0xFF, 0, 0, 140, 0,
                      0x80 if valid else 0, 0x40 if fault else 0]).hex()
    ok(c.q("wba " + aem(1.123, 1, 0)) == "1123", "AEM lambda 1.123")
    ok(c.q("wba " + aem(1.123, 0, 0)) == "0", "AEM not valid -> 0")
    ok(c.q("wba " + aem(1.123, 1, 1)) == "0", "AEM sensor fault -> 0")
    # --- Haldex offset controller
    c.cmd("hxr")
    ok(c.q("hx 0 0 0 20 80 50 20 3 10") == "20", "no Allrad: 0 % wanted = the 0 % offset")
    ok(c.q("hx 1000 0 0 20 80 50 20 3 10") == "80", "no Allrad: 100 % = the 100 % offset")
    ok(c.q("hx 500 0 0 20 80 50 20 3 10") == "50", "no Allrad: 50 % = midway")
    c.cmd("hxr")
    o1 = int(c.q("hx 500 300 1 20 80 50 0 3 10"))
    ok(o1 > 50, "actual below wanted -> more offset (P) (%d)" % o1)
    c.cmd("hxr")
    o2 = int(c.q("hx 500 700 1 20 80 50 0 3 10"))
    ok(o2 < 50, "actual above wanted -> less offset (%d)" % o2)
    c.cmd("hxr")
    ok(c.q("hx 500 520 1 20 80 50 50 3 10") == "50", "inside the deadband: feed-forward only")
    c.cmd("hxr")
    seq = [int(c.q("hx 500 300 1 20 80 0 50 0 100")) for _ in range(20)]
    ok(seq[-1] > seq[0] and all(b >= a for a, b in zip(seq, seq[1:])),
       "I accumulates while the lock is short (%s)" % seq[:4])
    c.cmd("hxr")
    seq = [int(c.q("hx 1000 0 1 20 80 255 255 0 200")) for _ in range(200)]
    ok(seq[-1] <= 600, "offset clamped at 60 km/h (%d)" % seq[-1])
    # --- OBD-II mode 01 (SAE J1979 formulas, written here)
    ok(obd(c, 0x0C, rpm=3456) == (3456 * 4).to_bytes(2, "big"), "PID 0C rpm")
    ok(obd(c, 0x0D, vss=1234) == bytes([123]), "PID 0D speed")
    ok(obd(c, 0x05, clt=10000 + 905) == bytes([90 + 40]), "PID 05 coolant 90.5 C")
    ok(obd(c, 0x0F, iat=10000 - 120) == bytes([28]), "PID 0F intake -12 C")
    ok(obd(c, 0x0B, map=1513) == bytes([151]), "PID 0B MAP")
    ok(obd(c, 0x11, tps=500) == bytes([128]), "PID 11 throttle 50 %")
    ok(obd(c, 0x0E, adv=155) == bytes([int((15.5 + 64) * 2)]), "PID 0E timing 15.5")
    ok(obd(c, 0x0E, adv=-60) == bytes([int((-6 + 64) * 2)]), "PID 0E timing -6.0")
    ok(obd(c, 0x34, lam=1000)[:2] == (32768).to_bytes(2, "big"), "PID 34 lambda 1.000")
    ok(obd(c, 0x34, lam=0) == b"", "PID 34 without lambda: not answered")
    ok(obd(c, 0x42, vbat=13850) == (13850).to_bytes(2, "big"), "PID 42 battery")
    ok(obd(c, 0x01, mil=1, ndtc=3)[0] == 0x83, "PID 01 MIL + 3 codes")
    ok(obd(c, 0x99) == b"", "unknown PID: not answered")
    # supported-PID bitmaps list exactly the PIDs that answer
    def bits(pid0):
        bm = obd(c, pid0)
        return [pid0 + 1 + i for i in range(32) if bm[i // 8] & (0x80 >> (i % 8))]
    sup = bits(0x00) + bits(0x20) + bits(0x40)
    answered = [p for p in range(1, 0x60) if obd(c, p, lam=1000) != b""]
    ok(sorted(sup) == sorted(answered), "bitmaps == answering PIDs (%s vs %s)"
       % (sorted(set(sup) ^ set(answered)), ""))
    c.close()
    return fails


def main() -> int:
    dbc = T1.load_dbc()
    if dbc is None:
        print("SKIP: vw_pq.dbc not found")
        return 0
    cc = H.compiler()
    if cc is None:
        print("SKIP: no C host compiler found")
        return 0
    env = H.env_for(cc)
    H.TMP.mkdir(parents=True, exist_ok=True)
    exe = H.TMP / "hc_hccan2_host.exe"
    H.build(cc, env, [SOURCE, TEST], H.SHARED, exe)
    fails = checks(exe, env, dbc)
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    print("PASS: ABS emulation frames (DBC), Allrad_1, rusEFI + AEM wideband, "
          "Haldex offset controller, OBD-II mode 01 (J1979) + PID bitmaps")
    bad = 0
    src = SOURCE.read_text()
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hccan2_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        mexe = H.TMP / ("hc_hccan2_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, mexe, flags=("-w",))
        mf = checks(mexe, env, dbc)
        if not mf:
            print("FAIL: control %s - %s - passed the checks" % (name, what))
            bad += 1
        else:
            print("PASS: control %s - %s - fails (%s)" % (name, what, mf[0]))
    if not T1.keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
