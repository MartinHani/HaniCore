#!/usr/bin/env python3
"""Final-source and linked-machine gate for V49 live-Burn forensics."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c166_disasm as C166  # noqa: E402
import c167sim as C167  # noqa: E402
import me711_image as IMG  # noqa: E402

ME = ROOT / "firmware/targets/me711"
TGT = (ME / "hctarget.h").read_text()
NVM = (ME / "nvm/hcnvm.c").read_text()
LF = (ME / "diagnostics/hcliveforensics.c").read_text()
LFH = (ME / "diagnostics/hcliveforensics.h").read_text()
NMI = (ME / "system/hcnmi_v49.a66").read_text()
HCTS = (ROOT / "firmware/comms/hcts.c").read_text()
MAP = (ME / "build/hani_me711.M66").read_text()
BIN_PATH = IMG.image()
BIN = BIN_PATH.read_bytes()
# THE .ini IS NAMED FROM THE IMAGE UNDER TEST, ONCE. These were the V49 files,
# hardcoded, so from V50 onward this gate audited a stale pair while claiming to
# audit the current build - which is the exact defect me711_image.py exists to
# prevent and which the project rules record as having cost four incidents.
_STEM = IMG.STEM.replace("HaniCore_ME711_", "me711_").lower()
NORMAL_INI = ROOT / f"tunerstudio/hanicore_{_STEM}.ini"
FORENSIC_INI = ROOT / f"tunerstudio/hanicore_{_STEM}_forensic.ini"

checks = fails = 0


def check(name: str, ok: bool) -> None:
    global checks, fails
    checks += 1
    fails += not ok
    print(("PASS" if ok else "FAIL"), name)


def num(name: str, text: str = TGT) -> int:
    m = re.search(r"^#define\s+%s\s+(0x[0-9A-Fa-f]+|\d+)u?L?\b" % name,
                  text, re.M)
    if not m:
        raise ValueError(name)
    return int(m.group(1), 0)


def sym(name: str) -> int:
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s+LABEL" % re.escape(name),
                  MAP, re.M)
    if not m:
        raise ValueError(name)
    return int(m.group(1), 16)


def section(name: str) -> tuple[int, int]:
    m = re.search(r"^([0-9A-F]{6})H\s+([0-9A-F]{6})H\s+([0-9A-F]{6})H"
                  r".*\s%s$" % re.escape(name), MAP, re.M)
    if not m:
        raise ValueError(name)
    return int(m.group(1), 16), int(m.group(2), 16) + 1


def main() -> int:
    base = num("TGT_RAM_LIVEFORENSICS")
    size = num("TGT_RAM_LIVEFORENSICS_LIMIT")
    check("retained record is exactly 344 bytes at 38:6900",
          base == 0x6900 and size == 344 and "#define HC_LF_WORDS       172u" in LFH)
    check("retained record cannot overlap NVM or HAL census",
          num("TGT_RAM_NVM") + num("TGT_RAM_NVM_LIMIT") <= base
          and base + size <= num("TGT_RAM_HALCENSUS"))
    check("lifecycle distinguishes armed, partial NMI, complete NMI, recovery and durable success",
          all(x in LFH for x in ("LF_F_ARMED", "LF_F_NMI_STARTED",
                                 "LF_F_NMI_COMPLETE", "LF_F_RECOVERED",
                                 "LF_F_DURABLE", "LF_F_FROZEN",
                                 "LF_F_BOOT_SEALED")))
    check("boot freezes evidence before NVM recovery",
          (ME / "system/hcmain_me711.c").read_text().index("hc_lf_boot_early(reset_raw,")
          < (ME / "system/hcmain_me711.c").read_text().index("hc_nvm_boot()"))
    check("first Burn records explicit cumulative-counter baselines",
          all(x in NVM for x in ("L_WINDOWS_OK", "L_WRITER_ENT",
                                 "L_WRITER_OK", "L_WRITER_FAIL", "hc_lf_arm")))
    main_c = (ME / "system/hcmain_me711.c").read_text()
    check("normal telemetry exposes the active forensic header",
          all(x in main_c for x in ("put16(604, HC_LF_WORD(LF_MAGIC0))",
                                    "put16(606, HC_LF_WORD(LF_MAGIC1))",
                                    "put16(484, HC_LF_WORD(LF_FLAGS))",
                                    "HC_LF_WORD(LF_VERSION) == 0x0049u",
                                    "HC_LF_WORD(LF_LENGTH) == HC_LF_BYTES")))

    # THE SIZE IS DERIVED, NOT PINNED. 680 was a literal, and V53 grew the
    # block to 696 for the reclaim channels - which made this gate report a
    # deliberate, documented change as a contract violation. What actually
    # matters is that the firmware and the .ini agree and that the read-only
    # view still bounds it, so that is what is asked.
    # AND SO IS THE READ WINDOW. It was pinned at 1024, which is 680 + 344 -
    # the block as it stood at V48 plus HC_LF_BYTES - and stayed 1024 while
    # the block grew to 696 and then 722, so the last 21 words of the record
    # were off the end of the window. The question is not "is it 1024"; it is
    # "does it cover the ordinary block AND the whole record".
    _och = num("TGT_OCH_SIZE")
    _read = _och + 344
    check(f"the read view ({_read} bytes) covers the {_och}-byte block AND all "
          f"344 bytes of the record",
          "TGT_OCH_SIZE + 344u" in TGT
          and "TGT_OCH_READ_SIZE - off" in HCTS
          and "HCTS_TARGET_OCH_EXT_READ" in HCTS)
    check(f"normal and forensic INIs request {_och} and {_read} bytes respectively",
          f"ochBlockSize   = {_och}" in NORMAL_INI.read_text()
          and f"ochBlockSize   = {_read}" in FORENSIC_INI.read_text())

    p, e = sym("hc_nvm_payload"), sym("hc_nvm_payload_end")
    # THE SLOT LENGTH COMES FROM hctarget.h, NOT FROM THIS FILE. It was the
    # literal 1024 until V53 widened TGT_RAM_FLASHRT_LIMIT to the whole 2048-byte
    # reservation the writer and the eraser share, so this gate was asserting a
    # constraint the firmware no longer has - and V54's 988-byte writer passed it
    # with 36 bytes of a margin that does not exist.
    _slot = int(re.search(r"#define\s+TGT_RAM_FLASHRT_LIMIT\s+0x([0-9A-Fa-f]+)",
                          TGT).group(1), 16)
    check("linked SRAM writer remains inside its relocation slot",
          0 < e - p <= _slot)
    print("     LINKED WRITER: %d bytes, %d spare of the %d-byte copy"
          % (e - p, _slot - (e - p), _slot))
    C166._cur_seg = 0x8E
    at = p - 0x800000
    calls = []
    while at < e - 0x800000:
        n, text = C166.decode(BIN, at)
        if text.lstrip().startswith(("CALL", "CALLA", "CALLS", "CALLI")):
            calls.append((at, text))
        at += n
    check("relocated writer contains no call to flash", not calls)
    check("writer command stamp precedes AMD unlock and verification stamp follows final checks",
          NVM.index("lf[LF_COMMAND_T7]") < NVM.index("*unl1 = FL_UNLOCK1")
          and NVM.index("if (a != v || b != v)", NVM.index("HCNV_SETTLE_TICKS"))
          < NVM.index("lf[LF_VERIFY_T7]"))
    # The two instrumentation stamps must sit OUTSIDE the AM29 embedded-algorithm
    # interval and must be cheap: eight nominal T7 ticks is 16 ordinary
    # instructions at the target's conservative four clocks/instruction model.
    #
    # THE ANCHORS ARE REGISTER-AGNOSTIC, AND THAT IS THE FIX. They used to be
    # exact encodings - `F0 6C` is `MOV R6,R12` and `C4 64` is `MOV [R4+..],R6`
    # - so the moment Keil allocated a different register the search returned
    # -1, the counts became the 999 sentinel and the gate reported a firmware
    # defect where there was a register allocation. V54 added two locals to
    # hc_nvm_payload() and `MOV R6,R12` became `MOV R6,R3`. Same class as
    # "a test rig's stack comes from the MAP, never a literal".
    #
    # What is anchored now is what the firmware actually declares: the LF word
    # OFFSETS. LF_COMMAND_SEQ, LF_COMMAND_T7 and LF_VERIFY_T7 are words 24, 26
    # and 27, so their byte displacements are 0x30, 0x34 and 0x36, and the
    # stores are `MOV [Rw+#disp],Rw` = C4 xx <disp16>. The unlock datum 0x00AA
    # is `MOV Rw,#00AAh` = E6 xx AA 00 and the T7 read is `MOV Rw,T7` =
    # F2 xx 50 F0 whatever register they land in.
    payload = BIN[p - 0x800000:e - 0x800000]

    def lf_word(name):
        """The word index out of hcliveforensics.h, never typed here."""
        return int(re.search(r"#define\s+" + name + r"\s+(\d+)u", LFH).group(1))

    LF_COMMAND_SEQ = lf_word("LF_COMMAND_SEQ")
    LF_COMMAND_T7 = lf_word("LF_COMMAND_T7")
    LF_VERIFY_T7 = lf_word("LF_VERIFY_T7")

    def disp_store(disp, start=0, end=None):
        """`MOV [Rw + #disp], Rw`, any registers."""
        pat = (b"\xC4[\x00-\xFF]" + bytes([disp & 0xFF, (disp >> 8) & 0xFF]))
        found = [m.start() for m in
                 re.finditer(pat, payload[start:end if end is not None else len(payload)])]
        return [start + f for f in found]

    unlock_hits = [m.start() for m in
                   re.finditer(rb"\xE6[\xF0-\xFF]\xAA\x00", payload)]
    unlock = unlock_hits[0] if unlock_hits else -1
    seq_hits = disp_store(LF_COMMAND_SEQ * 2, 0, unlock if unlock > 0 else None)
    t7_hits = disp_store(LF_COMMAND_T7 * 2, 0, unlock if unlock > 0 else None)
    stamp0 = seq_hits[-1] if seq_hits else -1
    ver_hits = disp_store(LF_VERIFY_T7 * 2, unlock if unlock > 0 else 0)
    verify_store = ver_hits[0] if ver_hits else -1

    def instruction_count(lo: int, hi: int) -> int:
        count = 0
        while lo < hi:
            n, _ = C166.decode(payload, lo)
            lo += n
            count += 1
        return count

    before_count = (instruction_count(stamp0, unlock)
                    if stamp0 >= 0 and unlock > stamp0 else 999)
    verify_reads = list(re.finditer(rb"\xF2[\xF0-\xFF]\x50\xF0",
                                    payload[unlock:verify_store]))
    verify_start = (unlock + verify_reads[-1].start()) if verify_reads else -1
    after_count = instruction_count(verify_start, verify_store + 4) \
        if verify_start >= 0 and verify_store > verify_start else 999
    # EVERY ANCHOR MUST RESOLVE. An unresolved anchor is the 999 sentinel, which
    # fails loudly - it must never be allowed to read as a pass.
    check("writer stamps add zero flash-busy work and at most eight nominal T7 ticks",
          stamp0 >= 0 and unlock > stamp0 and verify_store > unlock
          and t7_hits and t7_hits[-1] > stamp0 and t7_hits[-1] < unlock
          and before_count <= 8 and after_count <= 8
          and before_count + after_count <= 16
          and "lf[LF_VERIFY_T7]" in NVM,
          )
    print("     STAMPS: command group %d instructions, verify group %d, "
          "bound 16" % (before_count, after_count))

    # THE VERIFIED-COMPLETION TEST IS THE WRITER'S OWN, AND IT IS A TIME PAIR.
    # lf[LF_VERIFY_SEQ] did not fit: adding it took the linked writer to 1032
    # of the fixed 1024-byte relocation, so the surviving test is
    # LF_VERIFY_T7 against LF_COMMAND_T7.  Both halves must be stamped inside
    # hc_nvm_payload() and neither may be written by C, or the comparison
    # inherits exactly the post-CALL dependence it exists to avoid.
    writer_src = NVM[NVM.index("void far hc_nvm_payload(void)"):
                     NVM.index("void far hc_nvm_payload_end")]
    check("both halves of the verified-completion test live inside the writer",
          "lf[LF_COMMAND_T7] = (unsigned int)T7;" in writer_src
          and "lf[LF_VERIFY_T7] = (unsigned int)T7;" in writer_src
          and "HC_LF_WORD(LF_COMMAND_T7) =" not in LF
          and "HC_LF_WORD(LF_VERIFY_T7) =" not in LF)

    # THE OTHER WAY EVIDENCE CAN BE LOST IS NOT A RESET.  The writer stamps
    # its words with no condition on them - it has no room for one - so a
    # SECOND Burn after the record is frozen would scribble on the first
    # event's evidence and break its seal.  fl_enter() saves and restores
    # those words around the CALLS whenever the record is not active.
    enter_src = NVM[NVM.index("static void fl_enter"):NVM.index("THE RAM PROBE")]
    check("a Burn after the record is frozen cannot disturb the writer's words",
          enter_src.index("hc_lf_active()") < enter_src.index("IEN = 0")
          and enter_src.index("lf_g24 = HC_LF_WORD(LF_COMMAND_SEQ)")
          < enter_src.index("CALLS")
          < enter_src.index("HC_LF_WORD(LF_COMMAND_SEQ) = lf_g24"))

    call = BIN.find(b"\xDA\x38\x00\x60")
    pushes = b"".join(bytes((0xEC, 0xF0 + r)) for r in range(1, 13))
    pops = b"".join(bytes((0xFC, 0xF0 + r)) for r in range(12, 0, -1))
    check("V47 ABI defect remains fixed at the physical writer boundary",
          call >= 24 and BIN[call - 24:call] == pushes
          and BIN[call + 4:call + 28] == pops)
    post = BIN[call + 28:call + 180]
    expected_reads = (b"\xF2\xF4\x86\xFF", b"\xF2\xF4\x7C\xF1",
                      b"\xF2\xF4\x72\xFF", b"\xF2\xF4\x74\xFF",
                      b"\xF2\xF4\x76\xFF")
    # V50: the restore is OR CC7IC,R4 (74 F4 86 FF), not the whole-register
    # MOV CC7IC,R4 (F6 ..) that destroyed a pending request. The ORDERING
    # this check exists for is unchanged: every dur_* sample is taken first.
    first_restore = post.find(b"\x74\xF4\x86\xFF")
    check("CC7/T8/SSC request registers are sampled before IE-only restoration",
          first_restore > 0 and all(0 <= post.find(x) < first_restore for x in expected_reads))
    check("no forensic call or external store is inserted before IC restoration",
          b"\xCA" not in post[max(0, post.find(expected_reads[0])):first_restore]
          and b"\xDA" not in post[max(0, post.find(expected_reads[0])):first_restore])

    nmi_lo, nmi_hi = section("?PR?HCNMI_V49")
    nmi_calls = []
    C166._cur_seg = 0x8E
    at = nmi_lo - 0x800000
    while at < nmi_hi - 0x800000:
        n, text = C166.decode(BIN, at)
        if text.lstrip().startswith(("CALL", "CALLA", "CALLS", "CALLI")):
            nmi_calls.append((at, text))
        at += n
    check("NMI handler is straight-line assembly with no C166 call opcode",
          "CALL" not in NMI and not nmi_calls)
    check("NMI writes start before context and completion after RESETDIAG compatibility fields",
          NMI.index("#04E31H") < NMI.index("MOV     R2,TFR")
          < NMI.index("#0240AH") < NMI.index("OR      R2,#00008H")
          < NMI.index("#04E32H"))
    nmi_body = BIN[nmi_lo - 0x800000:nmi_hi - 0x800000]
    done_imm = nmi_body.rfind(b"\xE6\xF2\x32\x4E")
    final_store = nmi_body.rfind(b"\xB8\x21")
    check("linked NMI completion marker is its final retained store",
          done_imm >= 0 and final_store > done_imm
          and b"\xB8\x21" not in nmi_body[final_store + 2:])

    # THE RESET LOG IS BIG-ENDIAN AND THIS CORE IS NOT.  hcconfig.c's
    # rst_u16() reads RAM[off] << 8 | RAM[off + 1], so a native MOV of 0x0002
    # would make rstPreviousTrap read 0x0200 and rstPreviousTrapMs come back
    # byte-swapped - destroying comparison with the V48 PHYSICAL numbers
    # (trap 2 at 37807 ms) that this build exists to extend.  Check the LINKED
    # IMMEDIATE, not a source line.
    check("linked NMI writes the RESETDIAG fields in the reset log's byte order",
          b"\xE6\xF2\x00\x02" in nmi_body            # MOV R2,#0200h
          and b"\xE6\xF2\x02\x00" not in nmi_body    # and never #0002h
          and b"\x1C\x82" in nmi_body)               # ROL R2,#8 for the tick

    v = BIN[0x20008:0x2000C]
    check("second-level trap-2 slot points to linked hc_v02",
          v == bytes((0xFA, (sym("hc_v02") >> 16) & 0xFF,
                       sym("hc_v02") & 0xFF, (sym("hc_v02") >> 8) & 0xFF)))
    stub = BIN[0x79A6:0x79BE]
    check("first-level NMI guard conditionally forwards to second-level trap 2",
          stub[12:16] == b"\xFA\x82\x08\x00" and b"\xB7\x48\xB7\xB7" in stub)

    fcpu = num("TGT_FCPU_HZ")
    br = num("TGT_ASIC_SSCBR")
    bit_rate = fcpu // (2 * (br + 1))
    word_us = 16_000_000 // bit_rate
    guard = num("TGT_LIVE_WORD_GUARD_US")
    old_min = guard // num("TGT_LIVE_PEC_WORD_FLOOR_US") + 2
    check("corrected SSC model is 1 MHz and 16 us per word",
          bit_rate == 1_000_000 and word_us == 16)
    check("V48 36-count premise remains a failing negative control",
          old_min == 36 and (old_min - 1) * word_us < guard
          and "intentionally preserves V48's admission" in TGT)

    # Actual restoration semantics: an IR raised while the saved image has IR
    # clear is visible to V49 immediately before V48 writes the saved word.
    saved, during = 0x004C, 0x00CC
    restored = saved
    check("request-loss discriminator detects the actual V48 IR-erasure case",
          not (saved & 0x80) and bool(during & 0x80) and not (restored & 0x80)
          and "lf_new_ir(save_t8, dur_t8, 0x0002u)" in LF)
    # Negative control for the simulator model used by the end-to-end Burn
    # gates: a request restored by a firmware IC write must arbitrate exactly
    # like a request raised by timer hardware.
    sim_mem = C167.Mem(BIN)
    sim_cpu = C167.CPU(sim_mem, 0x8E, 0x0200)
    sim_mem.sfr[0xFF10] = 0x0800
    sim_mem.w16(0xF17C, 0x00CC)  # T8IC: IR|IE, ILVL=3
    sim_cpu.check_irq()
    check("simulator delivers an IR restored by a firmware IC-register write",
          (sim_cpu.csp, sim_cpu.ip) == (0x82, 0x00F8)
          and sim_cpu.irq_count.get(0x3E, 0) == 1)
    check("T8 and SSC ISR stamps are captured without a C call in either ISR",
          "HC_LF_WORD(LF_TICK_LAST_GAP)" in (ME / "system/hcmain_me711.c").read_text()
          and "HC_LF_WORD(LF_SSC_ISR_T7)" in (ME / "asic/hcasic.c").read_text())
    tick = sym("hc_tick_isr") - 0x800000
    tick_body = BIN[tick:tick + 0xB4]
    tick_essential = tick_body.find(b"\xCA\x00")
    tick_external = tick_body.find(b"\xD7\x00\x38\x00")
    rx = sym("hc_ssc_rx_isr") - 0x800000
    rx_body = BIN[rx:rx + 0x80]
    cs_release = rx_body.find(b"\x4F\xE6")
    rx_external = rx_body.find(b"\xD7\x10\x38\x00")
    check("linked ISR ordering keeps essential tick and CS-release work ahead of logging",
          0 <= tick_essential < tick_external
          and 0 <= cs_release < rx_external)

    # A GAP NEEDS A BASELINE.  hc_lf_arm() zeroes the ASIC launch anchor, so
    # measuring the first launch against it reported a gap of the whole uptime
    # and left that number standing as the maximum - destroying the one field
    # the interpretation table reads as cadence disruption.
    check("no ASIC cadence gap is measured against an anchor that was never set",
          "gap = HC_LF_WORD(LF_ASIC_LAST_LAUNCH_MS);" in LF
          and "if (gap != 0u) {" in LF
          and "HC_LF_WORD(LF_ASIC_LAST_LAUNCH_MS) = 0u;" in LF)

    # Exercise the shipped decoder with a sealed synthetic record.
    spec = importlib.util.spec_from_file_location(
        "v49decode", ROOT / "tools/bench/me711_burn_forensics_capture.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    words = [0] * 172
    words[:4] = [0x4843, 0x4C46, 0x0049, 344]
    words[4] = 0x805D
    words[41] = 0x0002
    words[96], words[97] = 0x4E31, 0x4E32
    calc = 0x49A5
    for i, value in enumerate(words):
        if i != 15:
            calc = mod.rol16(calc) ^ value
    words[15] = calc
    report = mod.decode(b"".join(x.to_bytes(2, "big") for x in words))
    check("decoder validates integrity and identifies a lost T8 request",
          report["record_valid"] and report["integrity_ok"]
          and any("T8 IR" in x for x in report["discriminators"]))

    # Independent known-state check of the shipped OEM-transition decoder.
    # Phase 3 is an echo tick: answer/seed/health/expect are held, phase drops
    # to 2 and the two accumulators advance by 1 / 0xC7.
    words[149] = 56
    words[56] = 0xA100
    words[62] = 7
    words[72] = (2 << 12) | (4 << 8) | 2
    words[160:172] = [5, 100, 2, 7, (3 << 8) | 4, 2, 9, 0x002A,
                      6, 299, 0xA502, 7]
    words[15] = 0
    calc = 0x49A5
    for i, value in enumerate(words):
        if i != 15:
            calc = mod.rol16(calc) ^ value
    words[15] = calc
    clean = mod.decode(b"".join(x.to_bytes(2, "big") for x in words))
    words[62] ^= 1
    words[15] = 0
    calc = 0x49A5
    for i, value in enumerate(words):
        if i != 15:
            calc = mod.rol16(calc) ^ value
    words[15] = calc
    corrupt = mod.decode(b"".join(x.to_bytes(2, "big") for x in words))
    check("decoder accepts a known OEM UMKOM transition and rejects a changed answer",
          clean["umkom_replay"]["matches_oem_transition"]
          and not corrupt["umkom_replay"]["matches_oem_transition"]
          and any("differs from OEM" in x for x in corrupt["discriminators"]))
    words[170] = 0
    words[15] = 0
    calc = 0x49A5
    for i, value in enumerate(words):
        if i != 15:
            calc = mod.rol16(calc) ^ value
    words[15] = calc
    incomplete = mod.decode(b"".join(x.to_bytes(2, "big") for x in words))
    check("decoder cannot mistake a torn UMKOM transition for state corruption",
          incomplete["integrity_ok"]
          and incomplete["umkom_replay"]["available"] is False
          and incomplete["umkom_replay"]["matches_oem_transition"] is None)

    # THE READOUT PATH: FOUR BOUNDED REQUESTS, NONE OF THEM ARBITRARY.
    offsets = [(mod.BASE + rel, min(mod.CHUNK, mod.SIZE - rel))
               for rel in range(0, mod.SIZE, mod.CHUNK)]
    blocking = int(re.search(r"^\s*blockingFactor\s*=\s*(\d+)",
                             NORMAL_INI.read_text(), re.M).group(1))
    check("the forensic extension is read in exactly four bounded requests",
          mod.READS == 4 and len(offsets) == 4
          and all(680 <= o and o + n <= 1024 and n <= blocking
                  for o, n in offsets)
          and sum(n for _o, n in offsets) == 344)
    check("no arbitrary RAM read or write command exists",
          "HCTS_TARGET_OCH_EXT_READ" in HCTS
          and "hc_lf_export_byte" in LF
          and "offset >= HC_LF_BYTES" in LF)

    # THREE ARTEFACTS THAT MUST AGREE, AND NOW SOMETHING THAT MAKES THEM.
    #
    # hcliveforensics.h numbers the words, the forensic .ini gives each an
    # offset, and the decoder gives each a name.  Nothing bound them: adding
    # LF_WRITER_RESULT reached the header and the .ini and silently missed the
    # decoder, which then reported word 157 as "word_157".  That is this
    # project's recorded defect - two artefacts that must agree with nothing
    # that makes them - so ask all three the same question.
    lf_words = {int(m.group(2)): m.group(1) for m in
                re.finditer(r"^#define\s+(LF_[A-Z0-9_]+)\s+(\d+)u\s*$", LFH, re.M)}
    lf_words = {k: v for k, v in lf_words.items()
                if v not in ("LF_ASIC_WORDS",)}
    ini_rows = re.findall(r"^\s+(lf\w+)\s+= scalar, U16,\s+(\d+),",
                          FORENSIC_INI.read_text(), re.M)
    # AND THE BASE IS DERIVED TOO. It was the literal 680, which was
    # TGT_OCH_SIZE at V48; send_och() serves the record from
    # hc_lf_export_byte(off - TGT_OCH_SIZE), so the base moves with the block
    # and the literal stopped being true when V55 grew it to 722. Every lf*
    # channel then named a word twenty-one earlier than the one it printed,
    # and THIS CHECK PASSED THROUGHOUT because it compared the .ini against
    # the same stale literal the generator used. Two artefacts that must agree
    # and a gate that agreed with both of them.
    check(f"the forensic .ini publishes all 172 words from the block's own "
          f"end at {_och}",
          len(ini_rows) == 172
          and all(int(off) == _och + i * 2
                  for i, (_n, off) in enumerate(ini_rows)))
    unnamed = sorted(w for w in lf_words
                     if w < 172 and w not in mod.NAMES
                     and not lf_words[w].endswith("_BASE"))
    check("every word hcliveforensics.h names is also named by the decoder",
          not unnamed)
    if unnamed:
        print("     decoder is missing: %s"
              % ", ".join("%d (%s)" % (w, lf_words[w]) for w in unnamed))

    # The writer-owned verdict, exercised THROUGH the shipped decoder with a
    # positive and a negative control rather than asserted from source text.
    def sealed(pairs):
        w = [0] * 172
        w[:4] = [0x4843, 0x4C46, 0x0049, 344]
        w[4] = 0x8041
        w[96], w[97] = 0x4E31, 0x4E32
        for i, value in pairs:
            w[i] = value
        c = 0x49A5
        for i, value in enumerate(w):
            if i != 15:
                c = mod.rol16(c) ^ value
        w[15] = c
        return mod.decode(b"".join(x.to_bytes(2, "big") for x in w))

    # command at T7 = 0x1000, verified 20 ticks later, C never recorded it
    near = sealed([(24, 44), (26, 0x1000), (27, 0x1014), (25, 0)])
    # command at T7 = 0x1000 with LF_VERIFY_T7 left over from the previous
    # word, a whole main-loop pass earlier
    stale = sealed([(24, 44), (26, 0x1000), (27, 0x0980), (25, 0)])
    check("decoder reads a completed word from the writer's stamps alone",
          near["writer_verified"] and not near["command_open"]
          and any("between RETS and V48's IC restoration" in x
                  for x in near["discriminators"]))
    check("decoder reads an unfinished word from the writer's stamps alone",
          not stale["writer_verified"] and stale["command_open"]
          and stale["writer_verify_delta_t7"] > mod.VERIFY_LIMIT_TICKS)

    print(f"{checks - fails}/{checks} checks pass")
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
