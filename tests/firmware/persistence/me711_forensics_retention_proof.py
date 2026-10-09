#!/usr/bin/env python3
"""Power-cut model for V49's retained first-event forensic lifecycle.

This deliberately models persistence one 16-bit store at a time.  Its
negative control moves the completion marker ahead of the snapshot and must
be rejected, proving the gate can distinguish a torn record from a complete
one rather than merely checking constants in source.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ME = ROOT / "firmware/targets/me711"
_LF_RAW = (ME / "diagnostics/hcliveforensics.c").read_text()

# READ THE IMPLEMENTATION, NOT THE STUB - AND V63 IS WHY THIS EXISTS.
#
# TGT_BURN_DIAGNOSTICS wrapped this module as
#
#     #if !defined(TGT_BURN_DIAGNOSTICS)
#         void hc_lf_recover(...) { if (...) return; }   <- a two-line STUB
#     #else
#         void hc_lf_recover(...) { ...the real thing... }
#     #endif
#
# and the stub comes FIRST IN THE FILE. This gate reads source TEXT, so
# SRC.index("void hc_lf_recover") found the stub, the slice to
# hc_lf_durable was two lines long, and the LF_RECOVERY lookup inside it
# raised ValueError: substring not found.
#
# THE SWITCH DOES NOT MATTER, WHICH IS THE POINT. A preprocessor branch
# removes CODE FROM THE IMAGE and leaves the TEXT exactly where it was,
# so this gate would crash identically with TGT_BURN_DIAGNOSTICS turned
# back on. tests/run_gates.py skips it while the modules are stubbed, and
# that SKIP was hiding a gate that had STOPPED WORKING rather than one
# whose question no longer applied - which is the more dangerous of the
# two, because it looks the same from the outside.
#
# So take everything from the #else onward when the file is split that
# way, and let assert_no_stub() refuse a body that is obviously a stub:
# a gate reading the wrong half must FAIL LOUDLY, not quietly agree.
if "\n#else" in _LF_RAW and "TGT_BURN_DIAGNOSTICS" in _LF_RAW:
    SRC = _LF_RAW[_LF_RAW.index("\n#else"):]
else:
    SRC = _LF_RAW


def assert_no_stub(body: str, name: str) -> str:
    """A stub body is a couple of lines of `if (args) return;` and no more."""
    if len(body.splitlines()) < 6 or "HC_LF_WORD" not in body:
        raise SystemExit(
            "me711_forensics_retention_proof is reading a STUB of %s rather than "
            "the implementation - the #if/#else split in hcliveforensics.c "
            "has moved again. Fix the slice; do not skip this gate." % name)
    return body
ASM = (ME / "system/hcnmi_v49.a66").read_text()
NVM = (ME / "nvm/hcnvm.c").read_text()
TGT = (ME / "hctarget.h").read_text()

# THE POWER-ON BIT IS READ FROM THE FIRMWARE, NOT TYPED IN HERE.  The first
# version of this model used 0x0002 while hcliveforensics.c tests
# TGT_RESET_PONR - two halves of the same contract written from two different
# memories, which is the defect the project rules record four times.  The physical
# V48 raw value was 0x001C and the genuine power-on value on this bench is
# 0x003C, exactly PONR more.
PONR = int(re.search(r"^#define\s+TGT_RESET_PONR\s+(0x[0-9A-Fa-f]+)",
                     TGT, re.M).group(1), 16)
WARM_RAW = 0x001C          # measured on this ECU, and V48's own reset cause
COLD_RAW = WARM_RAW | PONR # measured first boot of a session

WORDS = 172
VALID, ARMED, STARTED, COMPLETE = 0x8000, 0x0001, 0x0004, 0x0008
RECOVERED, DURABLE, FROZEN, BOOT_SEALED = 0x0010, 0x0020, 0x0040, 0x0080
START_MARK, DONE_MARK = 0x4E31, 0x4E32
checks = fails = 0


def check(name: str, ok: bool) -> None:
    global checks, fails
    checks += 1
    fails += not ok
    print(("PASS" if ok else "FAIL"), name)


def seal(w: list[int]) -> None:
    v = 0x49A5
    for i, x in enumerate(w):
        if i != 15:
            v = ((v << 1) | (v >> 15)) & 0xFFFF
            v ^= x
    w[15] = v


def integrity_ok(w: list[int]) -> bool:
    old = w[15]
    x = w.copy()
    seal(x)
    return old == x[15]


def fresh() -> list[int]:
    w = [0] * WORDS
    w[:4] = [0x4843, 0x4C46, 0x0049, 344]
    w[4] = VALID
    w[12] = 0x4439
    return w


def arm(w: list[int]) -> None:
    for i in range(16, WORDS):
        w[i] = 0
    w[5] = (w[5] + 1) & 0xFFFF
    w[7:12] = [1234, 0, 32, 32, 0]
    w[15] = 0
    w[4] = VALID | ARMED


def boot(w: list[int], raw: int, nvm_interrupted: bool = False,
         boot_id: int = 7) -> None:
    # Mirrors hc_lf_boot_early followed by hc_nvm_boot recovery.
    if w[:4] != [0x4843, 0x4C46, 0x0049, 344] or raw & PONR:
        w[:] = fresh()
    if not w[4] & (ARMED | FROZEN):
        w[14] = boot_id
    if w[4] & FROZEN:
        if w[4] & STARTED and not w[4] & BOOT_SEALED:
            w[6] = raw
            w[4] |= BOOT_SEALED
            seal(w)
        return
    w[6] = raw
    if w[4] & (STARTED | DURABLE | RECOVERED):
        w[4] |= FROZEN
        seal(w)
    if nvm_interrupted and w[4] & ARMED and not w[4] & FROZEN:
        w[13] = 0x0605
        w[4] |= RECOVERED | FROZEN
        seal(w)


def classification(w: list[int]) -> str:
    if w[:4] != [0x4843, 0x4C46, 0x0049, 344] or not integrity_ok(w):
        return "invalid"
    if w[97] == DONE_MARK and w[4] & COMPLETE:
        return "complete-nmi"
    if w[96] == START_MARK:
        return "partial-nmi"
    if w[4] & RECOVERED:
        return "recovered-no-snapshot"
    if w[4] & DURABLE:
        return "durable"
    return "other"


def nmi_stores() -> list[tuple[int, int | str]]:
    # Each tuple is one externally visible 16-bit store in execution order.
    # Context values only need distinct nonzero identities for torn-write tests.
    out: list[tuple[int, int | str]] = [(96, START_MARK), (4, "started")]
    out.extend((i, 0xA000 + i) for i in range(98, 144))
    out.extend([(4, "complete"), (97, DONE_MARK)])
    return out


def apply_store(w: list[int], store: tuple[int, int | str]) -> None:
    i, v = store
    if v == "started":
        w[i] |= STARTED | FROZEN
    elif v == "complete":
        w[i] |= COMPLETE
    else:
        w[i] = int(v)


def main() -> int:
    check("source preserves an already frozen record before writing reset_raw",
          SRC.index("if ((f & LF_F_FROZEN) != 0u)")
          < SRC.index("HC_LF_WORD(LF_RESET_RAW) = raw_reset"))
    recover = assert_no_stub(
        SRC[SRC.index("void hc_lf_recover")
            :SRC.index("void hc_lf_durable")], "hc_lf_recover")
    check("NVM boot recovery cannot rewrite an NMI-frozen record",
          recover.index("LF_F_FROZEN") < recover.index("LF_RECOVERY"))
    w = fresh(); boot(w, COLD_RAW, boot_id=23); arm(w)
    boot(w, WARM_RAW, nvm_interrupted=True, boot_id=24)
    check("originating boot identity survives event recovery", w[14] == 23)
    check("assembly completion marker is the final external snapshot store",
          ASM.rfind("MOV     [R1],R2") > ASM.index("#04E32H")
          and ASM.rfind("MOV     [R1],R2") - ASM.index("#04E32H") < 100)
    check("assembly sets COMPLETE before its final completion marker",
          ASM.index("OR      R2,#00008H") < ASM.index("#04E32H"))

    stores = nmi_stores()
    all_safe = True
    for cut in range(len(stores) + 1):
        w = fresh()
        arm(w)
        for store in stores[:cut]:
            apply_store(w, store)
        boot(w, WARM_RAW, nvm_interrupted=True)
        got = classification(w)
        want = "complete-nmi" if cut == len(stores) else (
            "partial-nmi" if cut >= 1 else "recovered-no-snapshot")
        all_safe &= got == want
    check("every NMI-store reset cut has an unambiguous classification", all_safe)

    # Negative control: publishing DONE immediately after START makes every
    # later cut look complete even though context is absent.  The invariant
    # above must detect at least one such false completion.
    bad = stores.copy()
    bad.remove((97, DONE_MARK))
    bad.insert(1, (97, DONE_MARK))
    false_complete = False
    for cut in range(2, len(bad)):
        w = fresh(); arm(w)
        for store in bad[:cut]:
            apply_store(w, store)
        # Simulate the equally bad ordering in which COMPLETE was also early.
        w[4] |= COMPLETE
        boot(w, WARM_RAW, nvm_interrupted=True)
        false_complete |= classification(w) == "complete-nmi"
    check("negative control exposes an early-marker false completion", false_complete)

    w = fresh(); arm(w); w[4] |= DURABLE | FROZEN; w[13] = 2222; seal(w)
    original = w.copy()
    boot(w, WARM_RAW); boot(w, 0x0004); boot(w, 0x0010)
    check("repeated warm resets preserve a frozen record byte for byte", w == original)

    w = fresh(); arm(w); w[4] |= DURABLE | FROZEN; seal(w)
    boot(w, COLD_RAW)
    check("a true power-on reset starts a fresh qualification epoch",
          w[4] == VALID and w[5] == 0 and w[96] == 0)

    # The V48 physical reset cause is the one this build will most likely
    # see again.  If it were mistaken for a power-on, the evidence would be
    # erased by the very boot that is supposed to freeze it.
    w = fresh(); arm(w); w[4] |= STARTED | FROZEN; w[96] = START_MARK; seal(w)
    frozen = w.copy()
    boot(w, WARM_RAW, nvm_interrupted=True)
    check("the measured V48 reset cause 0x001C freezes rather than reinitialises",
          w[96] == START_MARK and w[4] & BOOT_SEALED and w[6] == WARM_RAW)
    before_seal = w.copy()
    boot(w, WARM_RAW, nvm_interrupted=True)
    check("a second boot after sealing changes nothing", w == before_seal)
    assert frozen[96] == START_MARK

    # A SECOND BURN IS NOT A RESET, AND IT IS THE OTHER WAY EVIDENCE CAN BE
    # LOST.  The relocated writer stamps four words with no condition on
    # them, so fl_enter() saves and restores them whenever the record is not
    # active.  Source order is the only place this can be checked.
    enter = NVM[NVM.index("static void fl_enter"):NVM.index("THE RAM PROBE")]
    check("fl_enter saves the writer-owned words before CALLS and puts them back",
          enter.index("lf_g24 = HC_LF_WORD(LF_COMMAND_SEQ)")
          < enter.index("CALLS")
          < enter.index("HC_LF_WORD(LF_COMMAND_SEQ) = lf_g24")
          and enter.index("hc_lf_active()") < enter.index("IEN = 0"))
    # The writer-owned discriminator is a TIME PAIR, not a second sequence
    # number: lf[LF_VERIFY_SEQ] did not fit inside the fixed 1024-byte
    # relocation. Both halves of the pair must be stamped by the writer, and
    # neither may be written by C, or the comparison inherits exactly the
    # post-CALL dependence it exists to avoid.
    writer = NVM[NVM.index("void far hc_nvm_payload(void)"):
                 NVM.index("void far hc_nvm_payload_end")]
    check("both halves of the verified-completion test are stamped by the writer",
          "lf[LF_COMMAND_T7] = (unsigned int)T7;" in writer
          and "lf[LF_VERIFY_T7] = (unsigned int)T7;" in writer
          and "HC_LF_WORD(LF_COMMAND_T7) =" not in SRC
          and "HC_LF_WORD(LF_VERIFY_T7) =" not in SRC)

    w = fresh(); arm(w); w[4] |= RECOVERED | FROZEN; seal(w)
    w[42] ^= 1
    check("single-word corruption fails the export integrity check",
          classification(w) == "invalid")

    print(f"{checks - fails}/{checks} checks pass")
    return int(bool(fails))


if __name__ == "__main__":
    raise SystemExit(main())
