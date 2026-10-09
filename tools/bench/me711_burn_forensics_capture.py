#!/usr/bin/env python3
"""Capture twice and decode the bounded 344-byte live-Burn forensic OCH
extension (introduced in V49; was tools/me711_v49_forensic_capture.py).

Live use:
    py tools/bench/me711_burn_forensics_capture.py --port COM3 --out <dir>

Offline use accepts either the raw 344-byte extension or a 1024-byte OCH dump:
    py tools/bench/me711_burn_forensics_capture.py --input capture.bin
"""
from __future__ import annotations

import argparse
import json
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

BASE = 680
SIZE = 344
# FOUR BOUNDED REQUESTS, AND THE NUMBER IS DERIVED.  86 is SIZE // 4, so the
# 344-byte extension is read in exactly four equal requests of 86 bytes, every
# one of them inside the .ini's own blockingFactor of 256 and inside the
# 680..1023 window the firmware will serve.  Nothing here can ask for an
# address outside that window: the offsets are computed from BASE and SIZE.
CHUNK = SIZE // 4
READS = SIZE // CHUNK
assert CHUNK * READS == SIZE and READS == 4 and CHUNK <= 256

NAMES = {
    0: "magic0", 1: "magic1", 2: "version", 3: "length", 4: "flags",
    5: "epoch", 6: "reset_raw", 7: "request_ms", 8: "base_windows",
    9: "base_entries", 10: "base_success", 11: "base_fail",
    12: "release_id", 13: "recovery", 14: "boot_id", 15: "integrity",
    16: "stage_ms", 17: "first_writer_ms", 18: "admit_ms",
    19: "admit_t7", 20: "window_seq", 21: "cursor", 22: "writer_entry",
    23: "writer_return", 24: "command_seq", 25: "verify_seq",
    26: "command_t7", 27: "verify_t7", 28: "return_t7",
    29: "restore_t7", 30: "save_cc7ic", 31: "save_t8ic",
    32: "save_ssctic", 33: "save_sscric", 34: "save_ssceic",
    35: "during_cc7ic", 36: "during_t8ic", 37: "during_ssctic",
    38: "during_sscric", 39: "during_ssceic", 40: "lost_last",
    41: "lost_or", 42: "first_lost_pos", 43: "first_lost_t7",
    44: "entry_sscon", 45: "entry_pecc0", 46: "entry_pecc4",
    47: "entry_port", 48: "entry_t8rel", 49: "entry_t8",
    50: "entry_t0", 51: "entry_cc7", 52: "max_window_t7",
    53: "last_window_t7", 54: "admission", 55: "boundary_mark",
    96: "nmi_started", 97: "nmi_complete", 98: "nmi_tfr", 99: "nmi_t7",
    100: "nmi_wdt", 101: "nmi_wdtcon", 102: "nmi_sp", 103: "nmi_cp",
    104: "nmi_ip", 105: "nmi_csp", 106: "nmi_old_psw", 107: "nmi_psw",
    108: "nmi_p3", 109: "nmi_p6", 110: "nmi_cc7ic", 111: "nmi_t8ic",
    112: "nmi_ssctic", 113: "nmi_sscric", 114: "nmi_ssceic",
    115: "nmi_sscon", 116: "nmi_t8rel", 117: "nmi_t8",
    118: "nmi_t0", 119: "nmi_cc7", 120: "nmi_pecc0", 121: "nmi_pecc4",
    122: "nmi_owner_raw", 123: "nmi_cb_state_raw", 124: "nmi_cb_pos_raw",
    125: "nmi_asic_state", 142: "nmi_tick_ms", 143: "nmi_command_seq",
    144: "asic_last_launch_ms", 145: "asic_last_done_ms",
    146: "asic_max_gap_ms", 147: "asic_last_gap_ms", 148: "asic_seq",
    149: "asic_slot", 150: "first_anomaly", 151: "ssc_isr_t7",
    152: "ssc_isr_count", 153: "ssc_isr_pec", 154: "tick_last_t7",
    155: "tick_last_gap", 156: "tick_max_gap", 157: "writer_result",
    # V50: the discriminator the fix exists to drive to zero. lost_or means a
    # request AROSE while masked (legitimate); ir_dropped means it was gone
    # after the restore, which only the restore can have done.
    158: "ir_dropped", 159: "ir_dropped_pos",
    160: "um_acc_hi_before", 161: "um_acc_lo_before", 162: "um_seed_before",
    163: "um_answer_before", 164: "um_phase_health_before",
    165: "um_expect_before", 166: "um_answers_before", 167: "um_input_word1",
    168: "um_acc_hi_after", 169: "um_acc_lo_after",
    170: "um_after_marker_seed", 171: "um_answer_after",
}

FLAG_NAMES = {
    0x0001: "armed", 0x0002: "staged", 0x0004: "nmi_started",
    0x0008: "nmi_complete", 0x0010: "recovered", 0x0020: "durable",
    0x0040: "frozen", 0x0080: "boot_sealed", 0x8000: "valid",
}

UM_FR = [12, 3, 8, 4, 14, 13, 15, 9, 2, 0, 7, 10, 5, 11, 6, 1]

# THE WRITER-OWNED VERIFY TEST, AND ITS THRESHOLD IS DERIVED, NOT CHOSEN.
#
# hc_nvm_payload() stamps LF_COMMAND_T7 immediately before the AMD unlock and
# LF_VERIFY_T7 only after the poll, the settle and the two confirming reads.
# The longest a legitimate pair can be apart is the firmware's own bound:
# HCNV_POLL_US (1000) + HCNV_SETTLE_US (8) in hcnvm.c, converted by
# hctarget.h's US_TO_TICKS at the 1.248 MHz T7 timebase, plus a handful of
# instructions.  A VERIFY_T7 left over from the PREVIOUS word is a whole
# main-loop pass earlier - about 1.31 ms, or 1630 ticks, on the V40 measured
# 2.7 s / 2060 word figure - and unsigned that reads as nearly a full wrap.
# T7 wraps every 52.5 ms, far longer than one pass, so the two cannot alias.
#
# The raw delta is always published next to this verdict: the margin between
# the 1259-tick bound and a ~1630-tick pass is real but not large, and a
# reader must be able to see when a number lands near it rather than being
# handed a bare boolean.
T7_TICKS_PER_US = 1.248          # hctarget.h US_TO_TICKS, TGT_T78CON 0x4242
HCNV_POLL_US = 1000              # hcnvm.c
HCNV_SETTLE_US = 8               # hcnvm.c
VERIFY_LIMIT_TICKS = int((HCNV_POLL_US + HCNV_SETTLE_US) * T7_TICKS_PER_US) + 8


def um_dispatch(qcode: int) -> int:
    if qcode < 0x131C or qcode > 0x131C + 15 * 0x040E:
        return 16
    d = qcode - 0x131C
    return UM_FR[d // 0x040E] if d % 0x040E == 0 else 16


def evaluate_um(words: list[int], slots: list[dict]) -> dict:
    """Replay the exact hc_umkom/OEM transition retained for the last build."""
    u = words[160:172]
    latest_base = words[149]
    latest = slots[0] if latest_base == 56 else slots[1] if latest_base == 76 else None
    if (latest is None or latest["valid"] not in (0xA100, 0xA200)
            or (u[10] & 0xFF00) != 0xA500):
        return {"available": False, "matches_oem_transition": None,
                "mismatches": []}
    phase, health = (u[4] >> 8) & 0xFF, u[4] & 0xFF
    expect, input_w1 = u[5] & 0xFF, u[7]
    acc_hi, acc_lo, seed, prior_answer = u[0], u[1], u[2] & 0xFF, u[3]
    process = phase in (4, 0)
    if not process:
        expected = {
            "acc_hi": (acc_hi + 1) & 0xFFFF,
            "acc_lo": (acc_lo + 0x00C7) & 0xFFFF,
            "seed": seed, "answer": prior_answer,
            "phase": (phase - 1) & 0xFF, "health": health,
            "expect": expect,
        }
    else:
        qcode = ((acc_hi << 10) + acc_lo
                 if acc_hi <= 0x3F and acc_lo <= 0x3FF else 0xFFFF)
        rx_trust, rx_q = (input_w1 >> 4) & 0x0F, input_w1 & 0x0F
        if phase == 4:
            rx_trust, rx_q = expect, seed
        if rx_trust == expect:
            next_health = max(0, health - 1)
        else:
            next_health, expect = (health + 3) & 0xFF, rx_trust
        if expect == 0:
            qcode, next_expect = 0xFFFF, 3
        else:
            next_expect = expect - 1
        answer = um_dispatch(qcode)
        expected = {
            "acc_hi": (rx_q + 1) & 0xFFFF,
            "acc_lo": (rx_q * 14 + 0x00C7) & 0xFFFF,
            "seed": rx_q, "answer": answer, "phase": 3,
            "health": next_health, "expect": next_expect,
        }
    observed = {"acc_hi": u[8], "acc_lo": u[9], "seed": u[10] & 0xFF,
                "answer": u[11]}
    observed.update({"tx_answer": latest["tx"][0],
                     "phase": latest["um_phase"],
                     "health": latest["um_health"],
                     "expect": latest["um_expect"]})
    mismatches = []
    for key in ("acc_hi", "acc_lo", "seed", "answer", "phase", "health", "expect"):
        if key in observed and observed[key] != expected[key]:
            mismatches.append({"field": key, "expected": expected[key],
                               "observed": observed[key]})
    if "tx_answer" in observed and observed["tx_answer"] != expected["answer"]:
        mismatches.append({"field": "tx_word1", "expected": expected["answer"],
                           "observed": observed["tx_answer"]})
    return {"available": True, "input_word1": input_w1, "before_phase": phase,
            "before_health": health, "before_expect": u[5] & 0xFF,
            "expected": expected, "observed": observed,
            "matches_oem_transition": not mismatches,
            "mismatches": mismatches}


def envelope(payload: bytes) -> bytes:
    return (len(payload).to_bytes(2, "big") + payload
            + zlib.crc32(payload).to_bytes(4, "big"))


def read_chunk(port, offset: int, count: int,
               transcript: list[bytes] | None = None) -> bytes:
    req = envelope(b"O" + offset.to_bytes(2, "big") + count.to_bytes(2, "big"))
    port.reset_input_buffer()
    port.write(req)
    port.flush()
    got = bytearray()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        part = port.read(128)
        if part:
            got.extend(part)
            deadline = time.monotonic() + 0.25
        expected = len(req) + count + 7
        if len(got) >= expected:
            break
    wire = bytes(got)
    if transcript is not None:
        transcript.append(wire)
    raw = wire
    if raw.startswith(req):
        raw = raw[len(req):]
    if len(raw) < count + 7:
        raise RuntimeError(f"short OCH reply at {offset}: {len(raw)} bytes")
    n = int.from_bytes(raw[:2], "big")
    body = raw[2:2 + n]
    crc = int.from_bytes(raw[2 + n:6 + n], "big")
    if n != count + 1 or not body or body[0] != 0:
        raise RuntimeError(f"bad OCH response shape at {offset}")
    if crc != zlib.crc32(body):
        raise RuntimeError(f"bad OCH CRC at {offset}")
    return body[1:]


def capture(port, transcript: list[bytes] | None = None) -> bytes:
    out = bytearray()
    requests = 0
    for rel in range(0, SIZE, CHUNK):
        n = min(CHUNK, SIZE - rel)
        assert BASE <= BASE + rel and BASE + rel + n <= BASE + SIZE
        out.extend(read_chunk(port, BASE + rel, n, transcript))
        requests += 1
    if requests != READS or len(out) != SIZE:
        raise RuntimeError(f"expected {READS} bounded reads of {SIZE} bytes, "
                           f"got {requests} reads of {len(out)}")
    return bytes(out)


def pack_transcript(frames: list[bytes]) -> bytes:
    """Length-prefix raw serial responses so echo/framing remains auditable."""
    return b"".join(len(frame).to_bytes(4, "big") + frame for frame in frames)


def rol16(v: int) -> int:
    return ((v << 1) | (v >> 15)) & 0xFFFF


def decode(data: bytes) -> dict:
    if len(data) == 1024:
        data = data[BASE:BASE + SIZE]
    if len(data) != SIZE:
        raise ValueError(f"need {SIZE} or 1024 bytes, got {len(data)}")
    words = [int.from_bytes(data[i:i + 2], "big") for i in range(0, SIZE, 2)]
    fields = {NAMES.get(i, f"word_{i:03d}"): v for i, v in enumerate(words)}
    calc = 0x49A5
    for i, value in enumerate(words):
        if i != 15:
            calc = rol16(calc) ^ value
    flags = words[4]
    slots = []
    for base in (56, 76):
        phase_health_expect = words[base + 16]
        slots.append({
            "valid": words[base], "sequence": words[base + 1],
            "launch_ms": words[base + 2], "launch_t7": words[base + 3],
            "complete_ms": words[base + 4], "complete_t7": words[base + 5],
            "tx": words[base + 6:base + 9], "rx": words[base + 9:base + 13],
            "checksum_calc": words[base + 13], "checksum_recv": words[base + 14],
            "state_outcome": words[base + 15],
            "um_phase": (phase_health_expect >> 12) & 0xF,
            "um_health": (phase_health_expect >> 8) & 0xF,
            "um_expect": phase_health_expect & 0xFF,
            "run_tx": words[base + 17], "pec_end": words[base + 18],
            "xfer_ms": words[base + 19],
        })
    lost = words[41]
    discriminators = []
    if lost & 0x0002:
        discriminators.append("T8 IR arose before restoration and was erased by V48 restoration")
    if lost & 0x0001:
        discriminators.append("CC7 IR arose before restoration and was erased by V48 restoration")
    if lost & 0x001C:
        discriminators.append("an SSC terminal/error IR arose before restoration")
    # THE WRITER'S OWN VERDICT FIRST, C's ONLY AS CORROBORATION.
    verify_delta = (words[27] - words[26]) & 0xFFFF
    writer_stamped = words[24] != 0 and words[26] != 0
    writer_verified = writer_stamped and verify_delta <= VERIFY_LIMIT_TICKS
    # C's stamp: hc_lf_restore() writes words[25] only after the CALLS has
    # returned AND the IC registers have been put back.
    c_verified = words[24] != 0 and words[24] == words[25]
    command_open = writer_stamped and not writer_verified
    if command_open:
        discriminators.append("latest flash command was issued without a verified return")
        if any(words[i] & 0x0080 for i in (112, 113, 114)):
            discriminators.append("SSC terminal/error IR was pending while that flash command was unverified")
    # A DISAGREEMENT IS NOT NOISE - IT LOCATES THE EVENT.  The writer says the
    # device finished the word; C never got as far as recording it.  The only
    # code between those two points is the RETS, the IEN=0, the five IC reads
    # and V48's whole-register restoration - which is exactly the boundary
    # this build was made to measure.
    if writer_stamped and writer_verified and not c_verified:
        discriminators.append(
            "the word VERIFIED inside the writer but C never recorded it: the "
            "event fell between RETS and V48's IC restoration")
    if words[97] == 0x4E32:
        discriminators.append("complete first-NMI CPU/peripheral snapshot present")
    elif words[96] == 0x4E31:
        discriminators.append("NMI snapshot began but reset interrupted it")
    elif flags & 0x0010:
        discriminators.append("interrupted transaction recovered without reaching the NMI snapshot")
    # TWO EVENTS IN ONE RECORD, AND IT MUST NOT READ AS ONE.  The assembly
    # handler captures on the first NMI it sees, gated only on word 96 being
    # zero - deliberately, because an NMI is the event this build exists to
    # catch and the handler has no room for a second test.  So an NMI that
    # arrives AFTER boot recovery has already frozen the record still writes
    # its snapshot in.  The boot after it re-seals, leaving a record that is
    # internally consistent and describes two different moments.  Say so.
    if (flags & 0x0010) and (flags & 0x0004):
        discriminators.append(
            "RECOVERED and NMI-STARTED are both set: the CPU snapshot belongs "
            "to a LATER NMI than the recovery in words 13/21, and the two must "
            "not be read as one event")
    um = evaluate_um(words, slots)
    if um["matches_oem_transition"] is False:
        discriminators.append("captured UMKOM transition or transmitted answer differs from OEM arithmetic")
    return {
        "record_valid": words[:4] == [0x4843, 0x4C46, 0x0049, 344],
        "integrity_stored": words[15], "integrity_calculated": calc,
        "integrity_ok": words[15] == calc,
        "flags_set": [name for bit, name in FLAG_NAMES.items() if flags & bit],
        "fields": fields, "supervision": slots, "umkom_replay": um,
        "nmi_pc": f"{words[105] & 0xFF:02X}:{words[104]:04X}",
        "nmi_owner": words[122] & 0xFF,
        "nmi_admission": words[122] >> 8,
        "nmi_cb_state": words[123] & 0xFF,
        "nmi_cb_phase": words[123] >> 8,
        "nmi_cb_pos": ((words[124] & 0xFF) << 8) | (words[124] >> 8),
        "writer_command_word": words[24],
        "command_open": command_open,
        "writer_verify_delta_t7": verify_delta,
        "writer_verify_limit_t7": VERIFY_LIMIT_TICKS,
        "writer_verified": writer_verified,
        "c_recorded_verify": c_verified,
        "c_verify_word": words[25],
        "writer_result": words[157],
        "ir_dropped": words[158],
        "ir_dropped_pos": words[159],
        "last_window_t7": words[53],
        "max_window_t7": words[52],
        "reset_trap_note": "rstPreviousTrap/rstPreviousTrapMs are written by "
                           "the NMI handler in the reset log's big-endian "
                           "order; expect trap 2 and a plausible tick",
        "discriminators": discriminators,
    }


def load_input(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) in (SIZE, 1024):
        return data
    try:
        return bytes.fromhex(path.read_text())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("input is neither a raw dump nor hexadecimal text") from exc


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--port")
    src.add_argument("--input", type=Path)
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--out", type=Path, default=Path("v49-forensics"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.input:
        first = load_input(args.input)
        if len(first) == 1024:
            first = first[BASE:BASE + SIZE]
    else:
        try:
            import serial
        except ImportError:
            raise SystemExit("pyserial is required for --port")
        wire1, wire2 = [], []
        with serial.Serial(args.port, args.baud, timeout=0.05,
                           write_timeout=0.5) as port:
            first = capture(port, wire1)
            second = capture(port, wire2)
        (args.out / f"v49_forensics_{stamp}_read1.bin").write_bytes(first)
        (args.out / f"v49_forensics_{stamp}_read2.bin").write_bytes(second)
        (args.out / f"v49_forensics_{stamp}_wire1.bin").write_bytes(
            pack_transcript(wire1))
        (args.out / f"v49_forensics_{stamp}_wire2.bin").write_bytes(
            pack_transcript(wire2))
        if first != second:
            raise SystemExit("two forensic reads differ; preserve both files and STOP")
    report = decode(first)
    report["captured_utc"] = stamp
    out = args.out / f"v49_forensics_{stamp}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")
    return 0 if report["record_valid"] and report["integrity_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
