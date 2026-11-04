"""Compile the VAG CAN engine-message core (firmware/comms/hccan.c) with gcc,
run tests/host/test_hccan.c, and decode every payload it prints with the
opendbc vw_pq.dbc (.scratch/can-bus/ext/vw_pq.dbc, or the copy under
tests/host/data) - an independent description of the same bits - against the
engine state each scenario set. Mutation controls (a byte-swapped rpm, a
checksum over the wrong bytes, a multiplex that switches every frame, a
coolant offset error) must fail. A Keil MEDIUM compile checks that the core
pulls in no ?C_ runtime helper (it is built into a far module).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402

import host_c_test as H

SOURCE = H.HCP.find("hccan.c")
TEST = H.HOST_TESTS / "test_hccan.c"
KEIL = Path(r"C:\Keil\C166\BIN\C166.EXE")
DBC_CANDIDATES = (H.ROOT / ".scratch" / "can-bus" / "ext" / "vw_pq.dbc",
                  H.HOST_TESTS / "data" / "vw_pq.dbc")

CONTROLS = [
    ("rpm_big_endian", "rpm sent big-endian",
     "    d[2] = (unsigned char)(rpm4 & 0xFFu);                /* nmot_w, 0.25 rpm */\n"
     "    d[3] = (unsigned char)(rpm4 >> 8);",
     "    d[3] = (unsigned char)(rpm4 & 0xFFu);\n    d[2] = (unsigned char)(rpm4 >> 8);"),
    ("checksum_short", "Motor_5 checksum over bytes 0..5",
     "    x = (unsigned char)(d[0] ^ d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6]);",
     "    x = (unsigned char)(d[0] ^ d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5]);"),
    ("m6_checksum_with_byte0", "Motor_6 checksum includes byte 0",
     "    d[0] = (unsigned char)(d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6] ^ d[7]);",
     "    d[0] = (unsigned char)(d[1] ^ d[2] ^ d[3] ^ d[4] ^ d[5] ^ d[6]);"),
    ("mux_every_frame", "Motor_2 multiplex switches every frame",
     "    unsigned char code = (unsigned char)(s->mux2 >> 2), info, b = 0u;",
     "    unsigned char code = (unsigned char)(s->mux2 & 3u), info, b = 0u;"),
    ("temp_offset", "coolant offset 40 C instead of 48 C",
     "    if (dc < 10000u - 480u) {\n        return 0u;                          /* below -48 C                 */\n    }\n"
     "    v = (unsigned int)(dc - (10000u - 480u));          /* (C + 48) x 10   */",
     "    if (dc < 10000u - 400u) {\n        return 0u;\n    }\n"
     "    v = (unsigned int)(dc - (10000u - 400u));"),
]


# ------------------------------------------------------------- the DBC ----
def load_dbc():
    path = next((p for p in DBC_CANDIDATES if p.exists()), None)
    if path is None:
        return None
    msgs, cur = {}, None
    for line in path.read_text(encoding="latin-1").splitlines():
        m = re.match(r"BO_ (\d+) (\w+):", line)
        if m:
            cur = int(m.group(1))
            msgs[cur] = {}
            continue
        m = re.match(r"\s*SG_ (\w+)\s*(M|m\d*)?\s*:\s*(\d+)\|(\d+)@1([+-]) "
                     r"\(([-\d.eE]+),([-\d.eE]+)\)", line)
        if m and cur is not None:
            name, mux, start, length = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            msgs[cur][name] = (start, length, float(m.group(6)), float(m.group(7)), mux)
    return msgs


def raw(data: bytes, start: int, length: int) -> int:
    """Intel (little-endian) unsigned extraction - written from the DBC
    convention, not from hccan.c."""
    v = int.from_bytes(data, "little")
    return (v >> start) & ((1 << length) - 1)


def sig(dbc, mid, name, data):
    start, length, scale, off, _mux = dbc[mid][name]
    return raw(data, start, length) * scale + off


# ------------------------------------------------------------ the checks --
def check_all(lines, dbc) -> list[str]:
    fails = []

    def ok(cond, what):
        if not cond:
            fails.append(what)

    fr = {}
    for ln in lines:
        sc, name, hx = ln.split()
        fr[(sc, name)] = bytes.fromhex(hx)
    M1, M2, M3, M5 = 0x280, 0x288, 0x380, 0x480

    # --- Motor_1
    for sc, rpm, idle, ped in (("A", 850, 1, 0.0), ("B", 4250, 0, 50.0)):
        d = fr[(sc, "M1")]
        ok(abs(sig(dbc, M1, "Motordrehzahl", d) - rpm) < 0.3, "%s M1 rpm" % sc)
        ok(sig(dbc, M1, "Leergasinformation", d) == idle, "%s M1 idle bit" % sc)
        ok(abs(sig(dbc, M1, "Fahrpedalwert_oder_Drosselklapp", d) - ped) < 0.5,
           "%s M1 pedal" % sc)
        ok(sig(dbc, M1, "Fehlerstatus_Brems_Momenteneing", d) == 1, "%s M1 statbr" % sc)
        ok(sig(dbc, M1, "Fehlerstatus_Getriebe_Momentene", d) == 1, "%s M1 statgec" % sc)
    # torque: rl 120 % of the 230 Nm engine x 0.922 = 254.5 Nm = 63.6 % of 400
    tq = sig(dbc, M1, "inneres_Motor_Moment", fr[("B", "M1")])
    ok(abs(tq - 63.6) < 1.0, "B M1 torque %.1f %% (want 63.6)" % tq)
    tq = sig(dbc, M1, "inneres_Motor_Moment", fr[("A", "M1")])
    ok(abs(tq - 9.5) < 1.0, "A M1 torque %.1f %% (want 9.5)" % tq)
    d = fr[("C", "M1")]
    ok(sig(dbc, M1, "Motordrehzahl", d) == 0, "C M1 rpm 0")
    ok(raw(d, 40, 8) == 0xFF and sig(dbc, M1, "Fahrpedalwert_ungenau__Motor_1_", d) == 1,
       "C M1 pedal fault")

    # --- Motor_2: multiplex 4x each, coolant, idle target
    want_info = {0: ("MO2_CAN_Vers", 10), 1: ("MO2_Motor_Code", 34),
                 2: ("MO2_Getr_Code", 15), 3: ("MO2_max_Mo", 400)}
    for sc, clt in (("A", 90.0), ("B", 111.75)):
        for i in range(16):
            d = fr[(sc, "M2_%02d" % i)]
            code = sig(dbc, M2, "MO2_Mp_Code", d)
            ok(code == i // 4, "%s M2 frame %d mux code %d" % (sc, i, code))
            name, val = want_info[i // 4]
            ok(abs(sig(dbc, M2, name, d) - val) < 0.01, "%s M2 %s" % (sc, name))
            ok(abs(sig(dbc, M2, "MO2_Kuehlm_T", d) - clt) < 0.76, "%s M2 coolant" % sc)
            ok(abs(sig(dbc, M2, "MO2_LL_Solldz", d) - 850) < 10, "%s M2 idle target" % sc)
            ok(sig(dbc, M2, "MO2_Sta_No_Bet", d) == 1, "%s M2 normal operation" % sc)
    d = fr[("C", "M2_00")]
    ok(raw(d, 8, 8) == 0xFF and sig(dbc, M2, "MO2_Sta_Kuehlm", d) == 1, "C M2 coolant fault")
    ok(sig(dbc, M2, "MO2_Sta_No_Bet", d) == 0, "C M2 not running")

    # --- Motor_3
    d = fr[("A", "M3")]
    ok(abs(sig(dbc, M3, "MO3_Offsentemp", d) - 30.0) < 0.76, "A M3 intake air")
    ok(raw(d, 39, 1) == 1 and raw(d, 38, 1) == 0, "A M3 start-stop / E-gas bits")
    d = fr[("C", "M3")]
    ok(sig(dbc, M3, "MO3_Sta_Temp", d) == 1 and raw(d, 8, 8) == 0xFF, "C M3 IAT fault")
    ok(raw(d, 38, 1) == 1, "C M3 no E-gas")

    # --- Motor_6: checksum, counter, altitude, torque = Motor_1's
    M6 = 0x488
    for sc in ("A", "B"):
        tq1 = raw(fr[(sc, "M1")], 8, 8)
        for i in range(16):
            d = fr[(sc, "M6_%02d" % i)]
            x = 0
            for b in d[1:]:
                x ^= b
            ok(d[0] == x, "%s M6 frame %d checksum" % (sc, i))
            ok(sig(dbc, M6, "Zaehler_Motor_6", d) == i, "%s M6 frame %d counter" % (sc, i))
            ok(raw(d, 8, 8) == tq1 and raw(d, 16, 8) == tq1, "%s M6 torque = Motor_1" % sc)
            ok(raw(d, 24, 8) == 950 * 128 // 1013, "%s M6 altitude factor" % sc)

    # --- Motor_5: mux, lamps, consumption, starter, checksum
    want5 = {0: ("MO5_max_Moment", 230), 1: ("MO5_Drehzahl", 2000), 2: ("MO5_Motortyp", 4)}
    for sc in ("A", "B", "C"):
        for i in range(16):
            d = fr[(sc, "M5_%02d" % i)]
            x = 0
            for b in d[:7]:
                x ^= b
            ok(d[7] == x, "%s M5 frame %d checksum" % (sc, i))
            code = sig(dbc, M5, "MO5_Mp_Code", d)
            ok(code == i // 4, "%s M5 frame %d mux code" % (sc, i))
            if i // 4 in want5:
                name, val = want5[i // 4]
                ok(abs(sig(dbc, M5, name, d) - val) < 0.01, "%s M5 %s" % (sc, name))
            else:
                ok(raw(d, 0, 6) == 39, "%s M5 KVNPZ/20" % sc)
            total = 2500 * (i + 1)
            ok(sig(dbc, M5, "MO5_Verbrauch", d) == total & 0x7FFF, "%s M5 consumption %d" % (sc, i))
            ok(sig(dbc, M5, "MO5_UeberlVerb", d) == (1 if total > 0x7FFF else 0),
               "%s M5 overflow flag %d" % (sc, i))
    d = fr[("B", "M5_00")]
    ok(sig(dbc, M5, "MO5_E_Gas", d) == 1 and sig(dbc, M5, "MO5_OBD_2", d) == 1
       and sig(dbc, M5, "MO5_Heissl", d) == 1, "B M5 EPC / MIL / hot lamps")
    ok(abs(sig(dbc, M5, "MO5_Luefter", d) - 50.0) < 0.5, "B M5 fan")
    d = fr[("A", "M5_00")]
    ok(sig(dbc, M5, "MO5_E_Gas", d) == 0 and sig(dbc, M5, "MO5_OBD_2", d) == 0, "A M5 lamps off")
    ok(sig(dbc, M5, "MO5_Anlasser", d) == 1 and sig(dbc, M5, "MO5_Start", d) == 0,
       "A M5 starter bits (running)")
    d = fr[("C", "M5_00")]
    ok(sig(dbc, M5, "MO5_Start", d) == 1 and sig(dbc, M5, "MO5_Anlasser", d) == 0,
       "C M5 starter bits (stopped)")
    return fails


def run_exe(exe, env):
    r = subprocess.run([str(exe)], env=env, capture_output=True, text=True)
    return r.stdout.splitlines()


def keil_check() -> bool:
    if not KEIL.exists():
        print("SKIP: Keil C166 not found - helper check not run")
        return True
    out = Path(tempfile.mkdtemp())
    target = H.ROOT / "firmware" / "targets" / "me711"
    r = subprocess.run([str(KEIL), str(SOURCE), "MOD167", "MEDIUM",
                        "RENAMECLASS(NDATA0=XNDATA0)",
                        "OBJECT(%s)" % (out / "hccan.obj"),
                        "PRINT(%s)" % (out / "hccan.lst"),
                        "INCDIR(%s)" % ";".join(map(str, H.HCP.include_dirs("me711"))), "CODE"],
                       cwd=str(target), capture_output=True, text=True)
    lst = (out / "hccan.lst").read_text(errors="replace") if (out / "hccan.lst").exists() else ""
    if "0 WARNING(S),  0 ERROR(S)" not in (r.stdout + lst):
        print("FAIL: Keil C166 did not compile hccan.c cleanly")
        print(r.stdout[-1500:])
        return False
    helpers = sorted(set(re.findall(r"CALLS\s+SEG \((\?C_\w+)\)", lst)))
    if helpers:
        print("FAIL: hccan.c (far) calls Keil runtime helpers: %s" % ", ".join(helpers))
        return False
    print("PASS: Keil C166 MEDIUM, 0 warnings, no ?C_ helper call")
    return True


# ---------------------------------------------------------- RECEIVE ----
def encode(dbc, mid, values: dict) -> str:
    """An 8-byte frame from DBC signal values - written from the DBC, not
    from hccan.c: raw = (value - offset) / scale at start|length, Intel."""
    v = 0
    for name, val in values.items():
        start, length, scale, off, _mux = dbc[mid][name]
        raw = int(round((val - off) / scale)) & ((1 << length) - 1)
        v |= raw << start
    return v.to_bytes(8, "little").hex().upper()


def rx(exe, env, msg, hx) -> dict:
    r = subprocess.run([str(exe), msg, hx], env=env, capture_output=True, text=True)
    return {k: int(v) for k, v in (kv.split("=") for kv in r.stdout.split())}


RX_CASES = [
    # (message, id, DBC values, expected decoder output)
    ("bremse1", 416, {"BR1_Rad_kmh": 87.65, "BR1_Lichtschalt": 1, "BR1_ASR_Anf": 1,
                      "BR1_ASRMo_sl": 40 * 0.39, "BR1_MSR_Mo": 12 * 0.39, "BR1_Zaehler": 9,
                      "BR1_ESPASR_passive": 1},
     {"vss_x10": 876, "brake": 1, "asr_req": 1, "msr_req": 0, "esp_off": 1,
      "asr_slow": 40, "msr": 12, "counter": 9}),
    ("bremse1", 416, {"BR1_Rad_kmh": 250.0}, {"vss_x10": 2500, "brake": 0, "esp_off": 0}),
    ("bremse3", 1184, {"Radgeschw__VL_4_1": 51.2, "Radgeschw__VR_4_1": 52.3,
                       "Radgeschw__HL_4_1": 49.9, "Radgeschw__HR_4_1": 120.45},
     {"fl": 512, "fr": 523, "rl": 499, "rr": 1204}),
    ("getriebe1", 1088, {"GE1_Zielgang": 3, "GE1_Wahl_Pos": 5, "GE1_Soll_Mo": 61 * 0.39,
                         "GE1_EGS_Anf": 1, "GE1_Kuehlung": 2, "GE1_Sta_OBD": 1,
                         "GE1_Klimakompr": 1},
     {"gear": 3, "selector": 5, "tq_req": 61, "tq_valid": 1, "cooling": 2, "mil": 1, "ac_off": 1}),
    ("kombi1", 800, {"Geschwindigkeit__Kombi_1_": 133.7, "Tankinhalt": 42, "Tankwarnung": 1},
     {"vss_x10": 1337, "fuel_l": 42, "fuel_low": 1}),
    ("kombi2", 1056, {"Aussentemperatur_gefiltert": 12.5, "Oeltemperatur_4_1": 97},
     {"amb_dc": (12.5 + 1000) * 10, "oil_dc": (97 + 1000) * 10}),
]


def check_rx(exe, env, dbc) -> list[str]:
    fails = []
    for msg, mid, vals, want in RX_CASES:
        got = rx(exe, env, msg, encode(dbc, mid, vals))
        for k, w in want.items():
            if got.get(k) != int(w):
                fails.append("%s %s: got %s want %s" % (msg, k, got.get(k), int(w)))
    # Airbag_1: a front crash of intensity 5 with the right checksum is a
    # crash; the same frame with a wrong checksum is never one
    d = bytearray(8)
    d[0] = 0x01 | (5 << 5)                  # Front_Crash + Crash_Intensitaet 5
    d[2] = 0x30                             # counter 3 at bits 20..23
    d[3] = d[0] ^ d[1] ^ d[2]               # checksum: XOR of bytes 0..3 = 0
    if rx(exe, env, "airbag1", d.hex().upper()).get("crash") != 1:
        fails.append("airbag1: a valid crash frame is not a crash")
    d[3] ^= 0x01
    if rx(exe, env, "airbag1", d.hex().upper()).get("crash") != 2:
        fails.append("airbag1: a wrong checksum is not refused")
    d = bytearray(8)
    d[0] = 0x01 | (2 << 5)                  # intensity 2: not evaluated as a crash
    d[3] = d[0]
    if rx(exe, env, "airbag1", d.hex().upper()).get("crash") != 0:
        fails.append("airbag1: intensity 2 counted as a crash")
    return fails


def main() -> int:
    dbc = load_dbc()
    if dbc is None:
        print("SKIP: vw_pq.dbc not found (.scratch/can-bus/ext or tests/host/data)")
        return 0
    cc = H.compiler()
    if cc is None:
        print("SKIP: no C host compiler found")
        return 0
    env = H.env_for(cc)
    H.TMP.mkdir(parents=True, exist_ok=True)
    exe = H.TMP / "hc_hccan_host.exe"
    H.build(cc, env, [SOURCE, TEST], H.SHARED, exe)
    fails = check_all(run_exe(exe, env), dbc)
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    print("PASS: hccan Motor_1/2/3/5 decode with vw_pq.dbc to the scenario values")
    rf = check_rx(exe, env, dbc)
    for f in rf:
        print("FAIL:", f)
    if rf:
        return 1
    print("PASS: receive decoders (Bremse_1/3, Getriebe_1, Kombi_1/2, Airbag_1) "
          "read DBC-encoded frames back to the encoded values")
    bad = 0
    src = SOURCE.read_text()
    for name, what, old, new in CONTROLS:
        assert src.count(old) == 1, "mutation point moved - update control " + name
        mutant = Path(tempfile.gettempdir()) / ("hccan_mutant_%s.c" % name)
        mutant.write_text(src.replace(old, new))
        mexe = H.TMP / ("hc_hccan_mutant_%s.exe" % name)
        H.build(cc, env, [mutant, TEST], H.SHARED, mexe, flags=("-w",))
        mf = check_all(run_exe(mexe, env), dbc)
        if not mf:
            print("FAIL: control %s - %s - passed the checks" % (name, what))
            bad += 1
        else:
            print("PASS: control %s - %s - fails (%s)" % (name, what, mf[0]))
    if not keil_check():
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
