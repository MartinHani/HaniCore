#!/usr/bin/env python3
"""Linked-image and boundary gate for V48 Architecture-D live Burn.

This is intentionally a release gate, not a simulator of an AM29 or a C167.
It binds the final source policy to the final M66 and BIN: PEC timing/count
boundaries, enabled-vector suppression, ASIC ownership, engine horizon, and
the actual BSET-IEN/CALLS/BCLR-IEN instruction sequence all fail closed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import c166_disasm as C166

ROOT = Path(__file__).resolve().parents[3]
ME = ROOT / "firmware/targets/me711"
SRC = (ME / "nvm/hcnvm.c").read_text()
TGT = (ME / "hctarget.h").read_text()
ASIC = (ME / "asic/hcasic.c").read_text()
MAIN = (ME / "system/hcmain_me711.c").read_text()
# 2026-10-14: irq_disable_all() (every xxIC = 0 at boot) moved to hcrtmon711.c
RTMON = (ME / "system/hcrtmon711.c").read_text()
TRIG = (ME / "engine/hctrig_me711.c").read_text()
HCTS = (ROOT / "firmware/comms/hcts.c").read_text()
MAP = (ME / "build/hani_me711.M66").read_text()
# THE FROZEN ARTEFACT THIS GATE INTERROGATES, WHEREVER IT ACTUALLY IS.
# bins/hanicore is gitignored, so a fresh clone or a git worktree has
# the release copy and not the build copy - and a gate that cannot find
# its subject silently stops being a gate.  The release directory holds
# the byte-identical frozen binary and its SHA256SUMS.txt.
_V_BIN = ROOT / "bins/hanicore/HaniCore_ME711_v48_live_burn_call_clobber_fix.bin"
if not _V_BIN.exists():
    _V_BIN = ROOT / "release/Porsche_ME711_V48_LIVE_BURN_CALL_CLOBBER_FIX/HaniCore_ME711_v48_live_burn_call_clobber_fix.bin"
if not _V_BIN.exists():
    raise SystemExit("frozen binary HaniCore_ME711_v48_live_burn_call_clobber_fix.bin is not in this checkout")
BIN = _V_BIN.read_bytes()

checks = fails = 0


def check(name: str, ok: bool) -> None:
    global checks, fails
    checks += 1
    fails += not ok
    print(("PASS" if ok else "FAIL"), name)


def macro(name: str) -> int:
    # Accept decimal and hexadecimal with any Keil suffix.  TGT_FCPU_HZ is
    # "40000000uL" and TGT_ASIC_SSCBR is "0x0013u"; a decimal-only parser
    # could read neither and reported both as missing.
    m = re.search(r"^#define\s+%s\s+(0[xX][0-9A-Fa-f]+|[0-9]+)[uU]?[lL]?\b"
                  % name, TGT, re.M)
    if not m:
        raise ValueError("missing numeric macro %s" % name)
    return int(m.group(1), 0)


def sym(name: str) -> int:
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s+LABEL" % name, MAP, re.M)
    if not m:
        raise ValueError("missing linked symbol %s" % name)
    return int(m.group(1), 16)


def protected_calls_bytes() -> bytes:
    """Exact register preservation around the opaque far SRAM call."""
    pushes = b"".join(bytes((0xEC, 0xF0 + r)) for r in range(1, 13))
    pops = b"".join(bytes((0xFC, 0xF0 + r)) for r in range(12, 0, -1))
    return pushes + b"\xDA\x38\x00\x60" + pops


def tooth_horizon_us(rpm: int) -> int:
    """V48's integer model at the instant after a clean 60-2 tooth."""
    if rpm == 0:
        return 0xFFFF
    # T1 ticks: 1.25 MHz / (60 teeth/rev * rpm/60) = 1,250,000/rpm.
    dt = 1_250_000 // rpm
    safe = dt - dt // macro("TGT_LIVE_HORIZON_ACCEL_DIV")
    return safe - safe // 5  # ticks to us x0.8, exactly as the C expression


def main() -> int:
    guard = macro("TGT_LIVE_WORD_GUARD_US")
    word = macro("TGT_LIVE_PEC_WORD_FLOOR_US")
    min_words = (guard // word) + 2
    # THE 499.2 kHz PREMISE IS REFUTED, AND THIS GATE NO LONGER RESTATES IT.
    # V48 justified a 32-us PEC word from an SSC clock of 499.2 kHz.  SSCBR is
    # 0x13 and the configured CPU clock is TGT_FCPU_HZ, so the baud rate is
    # f/(2*(SSCBR+1)) = 1 MHz and a 16-bit word is 16 us, not 32.  V49
    # deliberately keeps V48's admission decision so one physical replay can
    # measure whether it mattered - so what this gate must prove is that the
    # BEHAVIOUR is unchanged and the JUSTIFICATION has been retracted in
    # writing.  The arithmetic below is therefore run on the corrected model.
    fcpu = macro("TGT_FCPU_HZ")
    sscbr = macro("TGT_ASIC_SSCBR")
    exact_word_us = 16_000_000.0 / (fcpu / (2.0 * (sscbr + 1)))

    check("V48's 32-us PEC word floor and 0x13 SSC divider are unchanged in V49",
          word == 32 and sscbr == 0x13)
    # Scoped to the macro's OWN comment block, not the whole file: the header
    # is allowed - and required - to quote the refuted figure while retracting
    # it, and a blanket "499.2 kHz" not in TGT would forbid saying so.
    floor_block = TGT[:TGT.index("#define TGT_LIVE_PEC_WORD_FLOOR_US")]
    floor_block = floor_block[floor_block.rindex("#define TGT_LIVE_WORD_GUARD_US"):]
    check("the refuted 499.2 kHz justification has been retracted in the header",
          "499.2 kHz" not in floor_block and "32.052 us" not in floor_block
          and "is NOT justified by the configured target clock" in floor_block
          and "THE CLOCK IN THIS NOTE WAS WRONG" in TGT)
    check("the corrected SSC model is 1 MHz and 16 us per 16-bit word",
          abs(exact_word_us - 16.0) < 0.01)
    check("no stale 20-us V48 PEC word assumption remains",
          "TGT_LIVE_PEC_WORD_US          20u" not in TGT
          and "TGT_LIVE_PEC_WORD_US          20u" not in SRC)
    check("PEC minimum count is explicitly derived", "TGT_LIVE_PEC_MIN_WORDS" in TGT
          and "min_pec_words = (unsigned int)TGT_LIVE_PEC_MIN_WORDS;" in SRC)
    check("PEC minimum is 36 counts", min_words == 36)
    # The current shift word may already be outside PECCn's remaining count.
    # Thus N counts means only N-1 full word-times are relied upon.
    check("35 counts is unsafe at the earliest terminal boundary",
          (min_words - 2) * exact_word_us < guard)
    # AND SO IS 36, ON THE CORRECTED CLOCK.  35 word-times at 16 us is 560 us
    # against a 1100 us guard, so V48's admission can let a PEC transfer reach
    # its terminal ordinary request INSIDE the protected writer window.  This
    # is an OPEN, DELIBERATELY UNFIXED defect: V49 measures it rather than
    # changing it, because changing it in the same build would change the
    # experiment.  The retained PEC endpoints and the request-loss mask are
    # what the physical replay reads.  If a later build corrects the
    # threshold, this check is the one that must be revisited.
    check("36 counts do NOT clear the writer guard on the corrected clock "
          "- V49 retains the defect on purpose",
          (min_words - 1) * exact_word_us < guard
          and "Retained unchanged in" in TGT)
    check("both PEC0 and PEC4 independently reject one count below minimum",
          "tx_left < min_pec_words || rx_left < min_pec_words" in SRC)
    # V50: the mask is now IE-only. "SSCEIC = 0;" would clear xxIR too,
    # which is the defect the V49 Burn physically proved.
    check("SSC error ordinary vector is always suppressed during busy",
          "SSCEIC &= HCNV_IE_CLR;" in SRC)
    # V51 SUPERSEDES THIS CHECK, and the supersession is the point.
    #
    # It used to require the literal (SSCEN && (SSCCON & 0x0F00)) - V48's fix
    # for the DISABLED case, where 0x461F's bits 8..11 are error ENABLES and
    # V47 had read them as errors.  The reasoning was right and the rule was
    # still wrong: in OPERATING mode those bits are the error STATUS flags
    # SSCTE/RE/PE/BE, C167CR UM V3.1 section 12.7 says software must clear
    # them, and nothing in this firmware does - SSCEIC is left with
    # SSCEIE = 0, so hc_ssc_err_isr() never runs.  The writer's own 116 us
    # mask sets SSCRE, and from then on every window was refused.  V50
    # physically programmed 36 of 2060 words with liveWindowsRejected = 4993.
    #
    # So the admission no longer reads those bits at all.  Asserted BOTH ways,
    # because the absence is the half that matters: the frame-phase test must
    # be present, and the error-flag mask must be gone from the module.
    check("admission asks the SSC FRAME PHASE, never its latched error flags",
          "hc_asic_frame_in_flight() != 0u" in SRC
          and "(sscon & 0x8000u) != 0u && (sscon & 0x1000u) != 0u" in SRC
          and "0x0F00u" not in SRC)
    check("idle SSC suppresses both PEC terminal ordinary vectors",
          "if (!pec_in_flight) { SSCTIC &= HCNV_IE_CLR; SSCRIC &= HCNV_IE_CLR; }"
          in SRC)

    check("NVM claims the word before reporting ready", SRC.index("L_OWNER") < SRC.index("HCNV_ADMIT_READY"))
    start = ASIC[ASIC.index("unsigned char asic_start_transfer"):ASIC.index("/* PEC4 receives")]
    check("actual ASIC exchange launcher rejects NVM ownership before SSC state",
          '#include "hcnvm.h"' in ASIC and start.index("hc_nvm_word_owned()") < start.index("SSCBSY"))
    check("NVM releases ownership after writer return and IC restoration",
          SRC.index("SSCEIC |= (ssce & HCNV_IE_BIT);")
          < SRC.rindex("HCNV_OWNER_NONE"))
    check("ASIC service is scheduled before NVM service each main-loop pass",
          MAIN.index("hc_asic_start_service(tick_ms);") < MAIN.index("hc_nvm_service(tick_ms"))

    check("all active ordinary source ICs are saved/masked/restored",
          all(x in SRC for x in (
              "CC7IC &= HCNV_IE_CLR", "CC8IC &= HCNV_IE_CLR",
              "CC9IC &= HCNV_IE_CLR", "CC15IC &= HCNV_IE_CLR",
              "T8IC &= HCNV_IE_CLR", "S0RIC &= HCNV_IE_CLR",
              "S0EIC &= HCNV_IE_CLR", "SSCEIC &= HCNV_IE_CLR",
              "CC7IC  |= (cc7  & HCNV_IE_BIT)",
              "CC8IC  |= (cc8  & HCNV_IE_BIT)",
              "CC9IC  |= (cc9  & HCNV_IE_BIT)",
              "CC15IC |= (cc15 & HCNV_IE_BIT)",
              "T8IC   |= (t8   & HCNV_IE_BIT)",
              "S0RIC  |= (s0r  & HCNV_IE_BIT)",
              "S0EIC  |= (s0e  & HCNV_IE_BIT)")))
    # The authoritative "never writes xxIR" check is NOT a source grep:
    # it is tests/firmware/persistence/me711_burn_ir_preserve_proof.py, which reads the opcodes
    # of the FINAL LINKED IMAGE and carries the frozen V49 binary as its
    # negative control. Asserting it here as well would be a second,
    # weaker copy of the same claim.
    # WHY THIS IS NOT A PLAIN GREP FOR "xxIC = HC_IC" ANY MORE.
    #
    # It used to be, and V62 walked straight through it. Capture arming became
    # `CC15IC = role_ic(g_role[...])` - the interrupt word is still HC_IC, it
    # is just returned by a helper now - and the old regex, which demanded
    # HC_IC literally after the "=", stopped seeing ALL THREE capture channels.
    #
    # The exhaustive-model check survived that only because it compares an
    # EXACT SET: three members vanished, equality broke, and it failed instead
    # of quietly approving a burn-mask model with no crank or cam in it. An
    # `issubset` would have passed. That is the whole argument for exact-set
    # assertions, and it is the second time this session a source grep has been
    # blinded by an indirection it did not anticipate - see the same note in
    # me711_irq_priority_proof.
    #
    # So resolve the indirection instead of forbidding it: find the helpers
    # that RETURN an HC_IC word, then treat a call to one of them as an enable.
    ic_helpers = set()
    for text in (HCTS, TRIG, MAIN, ASIC):
        for m in re.finditer(
                r"^static\s+unsigned\s+int\s+(\w+)\s*\([^)]*\)\s*\n\{(.*?)\n\}",
                text, re.S | re.M):
            if "HC_IC(" in m.group(2):
                ic_helpers.add(m.group(1))
    # THE CONTROL FOR THE RESOLVER ITSELF. If no helper is found, every
    # indirect enable below silently becomes invisible again - which is exactly
    # the state this gate was in before, and it must not be reachable quietly.
    check("the HC_IC helper resolver actually found the indirection it exists for",
          "role_ic" in ic_helpers)

    def _enabling(rhs: str) -> bool:
        """An assignment that can turn an ordinary vector ON."""
        if "HC_IC" in rhs:
            return True
        return any(re.search(r"\b%s\s*\(" % h, rhs) for h in ic_helpers)

    def _ic_writes(text: str):
        for m in re.finditer(r"\b([A-Z0-9]+IC)\s*=\s*([^;]+);", text):
            yield m.group(1), m.group(2)

    active_ics = set()
    for text in (HCTS, TRIG, MAIN, ASIC):
        for reg, rhs in _ic_writes(text):
            if _enabling(rhs):
                active_ics.add(reg)

    trig_ics = {reg for reg, rhs in _ic_writes(TRIG) if _enabling(rhs)}
    check("trigger active nodes are exactly crank CC15 and cam CC8/CC9",
          trig_ics == {"CC15IC", "CC8IC", "CC9IC"})
    check("ASC transmit remains polled, never an ordinary enabled vector",
          "S0TIC  = 0" in RTMON
          and not any(reg == "S0TIC" and _enabling(rhs)
                      for reg, rhs in list(_ic_writes(MAIN)) + list(_ic_writes(RTMON))))
    check("enabled-IC model is exhaustive for the final source",
          active_ics == {"S0RIC", "CC7IC", "CC15IC", "CC8IC", "CC9IC",
                         "T8IC", "SSCRIC", "SSCTIC"})
    # AND THE MODEL IS WHAT THE BURN WINDOW ACTUALLY MASKS. The check above
    # says the set is the one this gate expects; this one says hcnvm.c saves,
    # clears and restores every member of it, so the two cannot drift apart
    # without one of them failing. SSCRIC/SSCTIC are handled by the PEC
    # in-flight path a few checks up, not by the blanket save/mask/restore.
    for reg in sorted(active_ics - {"SSCRIC", "SSCTIC"}):
        check("burn window saves, masks and restores %s" % reg,
              re.search(r"\b\w+\s*=\s*%s\s*;" % reg, SRC) is not None
              and re.search(r"%s\s*&=\s*HCNV_IE_CLR" % reg, SRC) is not None
              and re.search(r"%s\s*\|=\s*\(\s*\w+\s*&\s*HCNV_IE_BIT\s*\)" % reg,
                            SRC) is not None)
    # NEGATIVE CONTROL: the same three-part test must FAIL for a vector the
    # burn window genuinely does not touch, or it is matching on nothing.
    # CC10 is a real capture node on this board (P2.10, the KVA input) that
    # the HAL deliberately does not route and hcnvm.c therefore never saves.
    check("negative control - the mask test rejects an IC hcnvm.c never saves",
          re.search(r"\bCC10IC\s*&=\s*HCNV_IE_CLR", SRC) is None)

    check("running horizon uses clean tooth, rejects gap/cam/sync uncertainty",
          all(x in SRC for x in ("trg_tooth_dt", "trg_gap_pending != 0u", "trg_cam_error != 0u",
                                 "trg_state < TRG_SYNC_CRANK", "trg_last_dt` is intentionally NOT used")))
    check("horizon rejects equality with the complete writer busy budget",
          "horizon_us <= (unsigned int)TGT_LIVE_WORD_GUARD_US" in SRC)
    expected = {0: True, 600: True, 700: True, 800: False, 1000: False,
                1500: False, 2000: False, 3000: False}
    check("0/600/700/800/1000/1500/2000/3000 RPM horizon boundaries",
          all((tooth_horizon_us(rpm) > guard) == wanted for rpm, wanted in expected.items()))

    p, e = sym("hc_nvm_payload"), sym("hc_nvm_payload_end")
    check("linked SRAM payload extent is within the fixed 1-KiB relocation", 0 < e - p <= 1024)
    writer_start, writer_end = p - 0x800000, e - 0x800000
    C166._cur_seg = 0x8E
    writer_calls = []
    at = writer_start
    while at < writer_end:
        length, text = C166.decode(BIN, at)
        if text.lstrip().startswith(("CALL", "CALLA", "CALLS", "CALLI")):
            writer_calls.append((at, text))
        at += length
    check("linked writer instruction stream contains no C166 call to flash", not writer_calls)
    call = b"\xDA\x38\x00\x60"
    calls = [i for i in range(len(BIN)) if BIN.startswith(call, i)]
    check("final image has exactly two SRAM CALLS sites (writer and benign RAM probe)", len(calls) == 2)
    protected = protected_calls_bytes()
    live_call = next((i for i in calls
                      if BIN[i - 24:i + 4 + 24] == protected), -1)
    check("linked fl_enter saves R1-R12, CALLS SRAM, then restores R12-R1",
          live_call >= 0)

    # Exact linked sequence: IEN on, T7 snapshot, protected CALLS, IEN off.
    start = live_call - 24
    pre = BIN[start - 6:start] if start >= 6 else b""
    check("final machine code sets IEN and snapshots T7 before protected CALLS",
          len(pre) == 6 and pre[:2] == b"\xBF\x88"
          and pre[2] == 0xF2 and pre[4:] == b"\x50\xF0")
    after = live_call + 4 + 24
    check("final machine code clears IEN only after SRAM RETS and register restore",
          live_call >= 0 and BIN[after:after + 2] == b"\xBE\x88")

    # A mutation control proves this gate is sensitive to the physical V47
    # defect: deleting only the R12 save makes the exact bridge check fail.
    mutated = bytearray(BIN)
    mutated[start + 22:start + 24] = b"\xCC\x00"
    check("negative control detects a missing R12 preservation pair",
          mutated[start:start + len(protected)] != protected)

    # The physical signature at cursor 22.  In V47 the writer returned with
    # R12=CB_POS, so post-call stores used 0x38:001A for L_OWNER instead of
    # 0x38:6874.  The linked V48 wrapper preserves the real base and its boot
    # path also clears a retained transient owner after any unrelated reset.
    cursor = 22
    v47_wrong_owner = 0x380000 + cursor + 4
    correct_owner = 0x386870 + 4
    check("22-word failure signature resolves to V47's wrong retained-owner address",
          v47_wrong_owner == 0x38001A and correct_owner == 0x386874
          and v47_wrong_owner != correct_owner)
    check("V48 boot recovers only the transient ownership latch",
          "live_init();" in SRC
          and "SRAMB(NVM_LIVE)[L_OWNER] = (unsigned char)HCNV_OWNER_NONE;" in SRC)

    print("%d/%d checks pass" % (checks - fails, checks))
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
