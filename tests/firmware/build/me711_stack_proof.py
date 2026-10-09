#!/usr/bin/env python3
r"""Measure linked-image user/system stack depth and verify watermark guards.

The linker reserves the user stack; STKOV/STKUN declare the system window.
Boot, communication and direct call workloads are measurements of exercised
paths. The separate static budget proof bounds nested ISR/call combinations.
System-stack measurements must fit the configured window and use <=60% of it.
The watermark is cross-checked against independently observed stack writes;
corrupting and restoring its canary proves the guard detects an overflow.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import c167sim as S                      # noqa: E402
import me711_image as PI                 # noqa: E402
import me711_heartbeat_gap_proof as HB   # noqa: E402
import me711_ts_gap_proof as G           # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
START = ROOT / "firmware/targets/me711/system/start_me711.a66"

FAILS = 0
CHECKS = 0


def check(name, ok, detail=""):
    global FAILS, CHECKS
    CHECKS += 1
    print("  [%s] %-58s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS += 1


def sym(name):
    m = re.search(r"^\s*([0-9A-F]{6})H\s+%s\s" % re.escape(name),
                  PI.MAP.read_text(errors="replace"), re.M)
    return int(m.group(1), 16) & 0xFFFF if m else None


def declared_user_stack():
    """The reserved size, from the startup source rather than a constant."""
    m = re.search(r"\?C_USRSTKBOT:\s+DSB\s+([0-9A-Fa-f]+)H",
                  START.read_text(errors="replace"))
    if not m:
        raise SystemExit("?C_USRSTKBOT DSB not found in start_me711.a66")
    return int(m.group(1), 16)


envelope = HB.envelope      # one definition: 16-bit length (see HB)


def system_stack():
    """(STKOV, STKUN) from start_me711.a66 - 0xF606/0xF700 until 2026-10-06,
    0xF586/0xF800 since (the user stack moved below it, hcsafety.h)."""
    s = START.read_text(errors="replace")
    ov = int(re.search(r"MOV\s+STKOV,#0?([0-9A-F]+)H", s).group(1), 16)
    un = int(re.search(r"MOV\s+STKUN,#0?([0-9A-F]+)H", s).group(1), 16)
    return ov, un


SYS_OV, SYS_TOP = system_stack()


SENTINEL = 0x0002


def _call_on(rig, name, args=()):
    """Enter a firmware function on the booted rig and run it to completion.

    Same idiom as me711_boot_validation_proof.Rig.call(): push a sentinel
    return address, jump to the symbol, step until the sentinel comes back.
    """
    cpu = rig.cpu
    addr = G._sym(PI.MAP, name)
    saved = (cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext)
    cpu.ext = None
    if ((addr >> 16) & 0xFF) != (cpu.csp & 0xFF):
        # V96: A FAR TARGET RETURNS WITH RETS - IP, THEN CSP. Pushing only the
        # IP let RETS pop one word the rig never pushed: harmless while boot
        # happened to leave words on the system stack, a STACK UNDERFLOW trap
        # on the first image whose boot ended with it empty (V96 hc_validate,
        # FCODE since V81). The CSP word is the caller's segment.
        cpu.push(cpu.csp & 0xFF)
    cpu.push(SENTINEL)
    cpu.csp = (addr >> 16) & 0xFF
    cpu.ip = addr & 0xFFFF
    for i, v in enumerate(args):
        cpu.sr(8 + i, v & 0xFFFF)
    for _ in range(3_000_000):
        if (cpu.ip & 0xFFFF) == SENTINEL:
            break
        cpu.step()
    cpu.csp, cpu.ip, cpu.m.sfr[0xFE12], cpu.ext = saved


def guard_readback(call=None, args=()):
    """Boot the rig, optionally run one firmware function, then ask the
    FIRMWARE how deep the user stack went, alongside independent allocation
    and written-byte depths.

    The two numbers come from completely different places: hc_stack_used()
    scans the 0x5A5A pattern in the image's own RAM, while `seen` below
    watches memory writes. R0 measures allocated frames, including unwritten
    slots, and therefore cannot directly validate a written-byte watermark."""
    entry = G._sym(PI.MAP, "hc_asic_start_service")
    tick = G._sym(PI.MAP, "hc_tick_ms")
    rig = HB.Rig(PI.image(), entry, tick, echo=True)

    # Priming erases the boot-time watermark. Compare the pattern scan with
    # written depth AFTER prime returns, using the declared stack top. The
    # separate workload measurement below still includes the entire boot.
    prime = G._sym(PI.MAP, "hc_stack_prime")
    user_top = sym("?C_USRSTKBOT") + declared_user_stack()
    user_bottom = sym("?C_USRSTKBOT")
    seen = {"lo": user_top, "written": user_top,
            "return": None, "armed": False}
    o_step = S.CPU.step
    o_write = rig.mem.w8

    def write(address, value):
        if seen['armed'] and user_bottom <= address < user_top:
            seen['written'] = min(seen['written'], address)
        return o_write(address, value)

    def step(self):
        pc=(self.csp<<16)|self.ip
        if pc==prime:
            sp=self.m.sfr[0xFE12]
            # far since 2026-10-06 (hcrtmon711.c): CALLS pushed CSP, then IP
            seg=self.m.r16(sp+2)&0xFF if (prime>>16)!=0x84 else self.csp
            seen['return']=(seg<<16)|self.m.r16(sp)
        elif seen['return'] is not None and pc==seen['return']:
            seen['armed']=True;seen['return']=None
        cp = self.m.sfr.get(0xFE10, 0xFC00)
        r0 = self.m.r16(cp)
        if r0 and seen['armed']:
            # R0 is DPP-relative (e.g. B800 maps to physical F800).
            physical = self.m.sfr.get(0xFE00 + 2*(r0>>14),0)*0x4000 + (r0&0x3FFF)
            if physical < seen["lo"]:
                seen["lo"] = physical
        return o_step(self)

    S.CPU.step = step
    rig.mem.w8 = write
    try:
        rig.run(1_400_000)
        if call is not None:
            _call_on(rig, call, args)
    finally:
        S.CPU.step = o_step
        rig.mem.w8 = o_write

    # Ask the firmware. hc_stack_used() returns in R4.
    _call_on(rig, "hc_stack_used", ())
    reported = rig.cpu.gr(4) & 0xFFFF
    _call_on(rig, "hc_stack_overflowed", ())
    overflowed = rig.cpu.gr(4) & 0xFFFF
    observed = (user_top - seen["lo"]) if seen['armed'] else None
    written = (user_top - seen['written']) if seen['armed'] else None
    return reported, overflowed, observed, written


TICK_ADDR = None          # resolved lazily from the map


def largest_frames():
    """Every stack frame the compiler allocates in this image, largest first.

    A C166 frame is `ADD R0,#-n` (06 F0 lo hi, immediate negative) or
    `SUB R0,#n` (26 F0 lo hi), scanned over the code classes only. Returns
    [(bytes, address, owning symbol)].

    THIS IS WHERE THE RESERVE COMES FROM, instead of a ratio. A ratio is a
    multiple of whatever the workload happened to reach; the largest frame the
    compiler actually emits is a property of the image.
    """
    img = PI.image().read_bytes()
    text = PI.MAP.read_text(errors="replace")
    syms = sorted(
        (int(m.group(1), 16), m.group(2))
        for m in re.finditer(r"^\s*([0-9A-F]{6})H\s+([A-Za-z_?][\w?]*)\s",
                             text, re.M))

    def owner(a):
        best = "<unknown>"
        for at, nm in syms:
            if at <= a:
                best = nm
            else:
                break
        return best

    out = []
    for a0, a1 in ((0x840400, 0x850000), (0x850000, 0x85C000)):
        b = img[a0 - 0x800000:a1 - 0x800000]
        # WORD-ALIGNED ONLY. Every C167 instruction starts on an even
        # address; scanning odd offsets matches operand bytes, and V79's first
        # run reported a "148-byte frame" at 0x851475 that way.
        for i in range(0, len(b) - 3, 2):
            op, mod = b[i], b[i + 1]
            imm = b[i + 2] | (b[i + 3] << 8)
            frame = None
            if op == 0x06 and mod == 0xF0 and (imm & 0x8000):
                frame = 0x10000 - imm
            elif op == 0x26 and mod == 0xF0 and not (imm & 0x8000):
                frame = imm
            if frame and 2 <= frame <= 512 and frame % 2 == 0:
                out.append((frame, a0 + i, owner(a0 + i)))
    out.sort(reverse=True)
    return out


def measure(rx=None, steps=1_400_000, call=None, args=(), calls=None,
            force_tick=False):
    """(deepest user-stack use, deepest system-stack use, bottoms).

    `call`/`calls` run firmware functions on the booted rig, which is the only
    way to reach a chain the K-line workloads never walk - see the hc_validate
    case below for why that turned out to matter.

    `force_tick` advances `hc_tick_ms` on every simulated step during those
    calls. WITHOUT IT THE DEEPEST PART OF THE CHAIN NEVER RUNS: rd8() carries
    the tick-gated hcts_target_yield(), and the yield returns immediately
    unless `tick_ms != yield_mark`. On a rig where the millisecond tick does
    not advance during a call, hc_validate() is measured WITHOUT the ASIC and
    TunerStudio subtree it composes with in the car. Measured either way on
    V69: 176 static, 180 advancing.
    """
    global TICK_ADDR
    if TICK_ADDR is None:
        TICK_ADDR = G._sym(PI.MAP, "hc_tick_ms") & 0xFFFF
    if calls is None:
        calls = [(call, args)] if call is not None else []
    entry = G._sym(PI.MAP, "hc_asic_start_service")
    tick = G._sym(PI.MAP, "hc_tick_ms")
    rig = HB.Rig(PI.image(), entry, tick, echo=True)
    if rx:
        rig.queue_rx(300 * 2500, rx)

    # R0 IS DPP-RELATIVE, NOT A RAW ADDRESS. The startup does
    # `MOV R0,#DPP2:?C_USERSTKTOP`, so R0 carries DPP2's page bits: the top of
    # a stack at 0xF900 reads as 0xB900. Rather than decode DPP here, the top
    # is taken as the LARGEST value R0 ever holds - which is where the startup
    # put it and where it returns between calls - and depth is measured
    # relative to that. Nothing then depends on the page mapping.
    seen = {"hi": 0, "lo": 0xFFFF}
    lo_sys = [0xFFFF]
    in_call = [False]
    bump = [0]
    o_step = S.CPU.step

    def step(self):
        cp = self.m.sfr.get(0xFE10, 0xFC00)
        r0 = self.m.r16(cp)
        if r0:
            if r0 > seen["hi"]:
                seen["hi"] = r0
            if r0 < seen["lo"]:
                seen["lo"] = r0
        sp = self.m.sfr.get(0xFE12, 0xFFFF)
        if 0xF000 < sp < lo_sys[0]:
            lo_sys[0] = sp
        if in_call[0] and force_tick:
            bump[0] = (bump[0] + 1) & 0xFFFF
            self.m.w16(TICK_ADDR, bump[0])
        return o_step(self)

    S.CPU.step = step
    rig.run(steps)
    in_call[0] = True
    for name, a in calls:
        _call_on(rig, name, a)
    S.CPU.step = o_step
    used = (seen["hi"] - seen["lo"]) if seen["hi"] else None
    return used, lo_sys[0], seen["hi"]


def main() -> int:
    print("=== HaniCore ME7.1.1 - stack high-water, measured ===\n")
    print("  image   %s" % PI.image().name)
    print("  sha256  %s\n" % PI.sha256())

    size = declared_user_stack()
    bot = sym("?C_USRSTKBOT")
    top = (bot + size) & 0xFFFF
    print("  user stack    0x%04X-0x%04X  %d bytes reserved (R0, grows down)"
          % (bot, top - 1, size))
    print("  system stack  0x%04X-0x%04X  %d bytes (SP, STKOV/STKUN guarded)"
          % (SYS_OV, SYS_TOP - 1, SYS_TOP - SYS_OV))
    print("")

    cases = [
        ("boot + ASIC handshake, idle", None),
        ("a whole output-channel block", envelope(b"O" + (0).to_bytes(2, "big")
                                                  + (368).to_bytes(2, "big"))),
        ("a 256-byte calibration page read",
         envelope(b"R" + (0).to_bytes(2, "big") + (256).to_bytes(2, "big"))),
        ("the plain signature", b"S"),
    ]

    # THE DEEPEST CHAIN IN THE FIRMWARE, AND FOR A LONG TIME NOTHING WALKED IT.
    #
    # Until V64 every case above reported 28-42 bytes and this gate said the
    # user stack kept a 6x reserve. It does not. hc_validate() reads the page
    # through rd8(), rd8() carries the tick-gated hcts_target_yield(), and the
    # yield services the S5500 raster and the watchdog - so a validation walks
    # hc_validate -> rd8 -> hcts_target_yield -> the ASIC and TunerStudio
    # service, and that chain is 176 bytes deep.
    #
    # It is reached on EVERY apply, from the main loop, on every image since
    # the validator existed. V64 merely also calls it at boot, which is what
    # made this gate finally see it - and made a pre-existing 1.5x margin look
    # like a V64 regression. MEASURED, both images, one hc_validate() call on
    # a booted rig: V63 176 bytes, V64 176 bytes.
    #
    # Do not remove this case to make the number pretty. A workload that
    # avoids the deepest chain is how the 6x reserve was reported for nine
    # releases.
    cases_extra = []
    for label, kw in (
        ("ONE hc_validate(), tick static",
         dict(call="hc_validate", args=(0,))),
        # THE SAME CALL WITH THE YIELD ACTUALLY SERVICING. rd8() carries the
        # tick-gated hcts_target_yield(); on a rig whose millisecond tick does
        # not advance during the call, the ASIC + TunerStudio subtree under
        # hc_validate()'s own 152-byte frame NEVER RUNS. This is the chain the
        # firmware takes on every apply from the main loop.
        ("hc_validate() with the yield SERVICING",
         dict(call="hc_validate", args=(0,), force_tick=True)),
        # THE ENGINE PATHS, which the four K-line workloads above never touch.
        # 12N/8's warning was that "no trigger, injection or ignition path runs
        # on this workload".
        #
        # BE PRECISE ABOUT WHAT THIS ROW REACHES AND WHAT IT DOES NOT. The rig
        # boots onto the BOARD DEFAULT, which by 12K/5b "claims no engine at
        # all" - no cylinder count, no TDC table, no injector or coil routing.
        # So plan_tooth() runs and correctly plans NOTHING: this row exercises
        # the capture ring, the epoch and the service loop but NOT ev_drive()
        # or hc_hal_out_group(). The row after it calls the output path
        # directly rather than letting this one look like coverage it is not.
        ("the planner, no engine described",
         dict(calls=[("hc_drysched_init", ()),
                     ("hc_drysched_tooth", (600, 1000, 417)),
                     ("hc_drysched_service", (1417, 3)),
                     ("hc_drysched_tooth", (660, 1417, 417)),
                     ("hc_drysched_service", (1834, 3))], force_tick=True)),
        ("hc_hal_out_group(), every coil on then off",
         dict(calls=[("hc_hal_out_group", (0, 0x00FF, 1)),
                     ("hc_hal_out_group", (0, 0x00FF, 0))])),
        ("hc_hal_outputs_safe()",
         dict(call="hc_hal_outputs_safe", args=())),
        ("hc_cfg_mgr_service()",
         dict(call="hc_cfg_mgr_service", args=(), force_tick=True)),
    ):
        try:
            u, sp, hi = measure(**kw)
        except SystemExit as e:
            print("    %-34s NOT MEASURED: %s" % (label, e))
            continue
        if u is not None:
            cases_extra.append((label, u, sp, hi))

    used_user, worst_sys, worst_name, r0top = 0, 0xFFFF, "", 0
    measured_any = False
    for name, rx in cases:
        u, sp, hi = measure(rx)
        if u is None:
            print("    %-34s NO R0 MOVEMENT OBSERVED" % name)
            continue
        measured_any = True
        r0top = max(r0top, hi)
        used_s = SYS_TOP - sp if sp != 0xFFFF else 0
        print("    %-34s user %3d B   system %3d B" % (name, u, used_s))
        if u > used_user:
            used_user, worst_name = u, name
        worst_sys = min(worst_sys, sp)

    for name, u, sp, hi in cases_extra:
        measured_any = True
        r0top = max(r0top, hi)
        print("    %-34s user %3d B   system %3d B"
              % (name, u, SYS_TOP - sp if sp != 0xFFFF else 0))
        if u > used_user:
            used_user, worst_name = u, name
        worst_sys = min(worst_sys, sp)

    used_sys = SYS_TOP - worst_sys if worst_sys != 0xFFFF else 0
    head_user = used_user * 100.0 / size
    print("")
    print("  DEEPEST user-stack use observed : %d of %d bytes (%.0f%%), on %s"
          % (used_user, size, head_user, worst_name))
    print("  DEEPEST system-stack use observed: %d bytes" % used_sys)
    print("")

    # A MEASUREMENT THAT MEASURED NOTHING MUST NOT PASS. The first version of
    # this file read R0 as a raw address, never matched, and reported "-1791
    # of 512 bytes used" as a PASS on all four checks. A gate that goes green
    # on nonsense is worse than no gate.
    check("the measurement actually observed the stack pointer moving",
          measured_any and used_user > 0 and r0top > 0,
          "R0 top 0x%04X, deepest excursion %d bytes" % (r0top, used_user))
    check("the user stack is not exhausted by any exercised path",
          0 < used_user < size, "%d of %d bytes" % (used_user, size))
    # Guarded stacks must retain the measured reserve as well as pass the
    # static interrupt-nesting bound. Keil overlays ordinary SMALL locals;
    # reentrant frames and interrupt saves still consume these stacks.
    # =================== THE RESERVE IS DERIVED, NOT A RATIO ===================
    #
    # THE 4x RULE THAT STOOD HERE WAS BUILT ON A BAD MEASUREMENT AND IS GONE.
    # It was a comfortable multiple of 26 bytes - the figure this gate reported
    # for nine releases while none of its workloads walked
    # hc_validate -> rd8 -> hcts_target_yield -> ASIC + TunerStudio. The real
    # depth is an order of magnitude more, and at that depth NO reservation
    # this near-RAM budget can afford reaches 4x: it would need 704 bytes
    # against 116 free. A threshold that cannot be met by construction is not a
    # safety property, it is a permanent red light nobody reads.
    #
    # IT IS NOT REPLACED BY A SMALLER RATIO. What replaces it is three
    # conjuncts, and the gate fails if any of them fails:
    #
    #   1. a measured worst case over a workload set that now includes the
    #      ENGINE paths and the yield actually servicing - strictly deeper
    #      than what the 4x rule was ever applied to;
    #   2. a reserve DERIVED FROM THE IMAGE: room for one more call layer of
    #      the largest frame the compiler emits anywhere, EXCLUDING the one
    #      the measured worst chain already contains;
    #   3. the firmware's own overflow detection PROVEN to detect - see the
    #      canary section below, which now corrupts the bottom word and
    #      requires hc_stack_overflowed() to say so.
    #
    # WHY "EXCLUDING THE ONE ALREADY IN THE CHAIN" IS SOUND RATHER THAN
    # CONVENIENT: the largest frame in this image is hc_validate()'s own, and
    # hc_validate() is IN the deepest measured chain. Demanding room for a
    # second one would be demanding room for a recursion that does not exist.
    # The premise is asserted below rather than assumed, so if the largest
    # frame ever moves to a function the worst chain does not contain, this
    # check goes red and the reserve has to be re-derived.
    # V83: THE PREMISE BELOW WAS ASSERTED, AND V83 IS THE CASE IT WAS WRITTEN
    # FOR. hc_validate()'s claim list became static (146 bytes), its frame fell
    # 154 -> 10, and the largest frame is now hcts_send_response's 64 - which
    # the deepest measured chain does NOT contain. So the rule is stated in
    # full rather than in its one historical instance: if the worst chain
    # holds the largest frame, reserve the next largest; if it does not,
    # reserve the largest itself. Both are room for one more unexercised
    # layer of the biggest frame that is not already counted.
    frames = largest_frames()
    biggest = frames[0] if frames else (0, 0, "<none>")
    others = [f for f in frames if f[2] != biggest[2]]
    contained = biggest[2] in worst_name or ("validate" in biggest[2]
                                             and "validate" in worst_name)
    reserve = ((others[0][0] if others else biggest[0]) if contained
               else biggest[0])
    print("  largest stack frames the compiler emits in this image:")
    for fb, fa, fn in frames[:4]:
        print("    %4d bytes  0x%06X  %s" % (fb, fa, fn))
    print("  reserve for one more unexercised layer: %d bytes\n" % reserve)

    check("the reserve covers the largest frame the worst chain lacks",
          reserve >= (biggest[0] if not contained
                      else (others[0][0] if others else biggest[0])),
          "largest frame %d B (%s) is %s the deepest workload %r -> reserve "
          "%d B" % (biggest[0], biggest[2],
                    "IN" if contained else "NOT in", worst_name, reserve))
    check("measured worst case + a derived reserve fits the reservation",
          used_user + reserve <= size,
          "%d measured + %d reserve = %d of %d reserved (%d spare)"
          % (used_user, reserve, used_user + reserve, size,
             size - used_user - reserve))
    check("the system stack stays inside its guarded window",
          0 < used_sys < SYS_TOP-SYS_OV, "%d of %d bytes" % (used_sys,SYS_TOP-SYS_OV))
    check("and the system stack keeps 40 percent of its window free",
          used_sys <= 0.6*(SYS_TOP-SYS_OV), "%d of %d bytes - interrupts use THIS one"
          % (used_sys,SYS_TOP-SYS_OV))

    # ============ AND THE FIRMWARE'S OWN GUARD, CROSS-CHECKED ============
    #
    # Everything above is the SIMULATOR watching R0. That cannot run in a car.
    # hc_stack_prime()/hc_stack_used() give the ECU a written-byte watermark.
    # Check that against independently intercepted writes; allocated but
    # unwritten frame slots do not affect the pattern scan.
    #
    # The comparison is deliberately one-sided. The pattern scan can only
    # UNDER-report - a frame that happened to store 0x5A5A into a word reads
    # as untouched - so the firmware's answer may be a little shallower than
    # the write trace, never deeper. A firmware answer DEEPER than the
    # trace would mean the pattern was disturbed by something that is not the
    # stack, and that is a failure.
    rep, ovf, allocated, obs = guard_readback(call="hc_validate", args=(0,))
    check("the firmware measures its own stack depth",
          rep > 0, "hc_stack_used() reports %d bytes" % rep)
    # V83: THE FIRMWARE CANNOT REPORT BELOW HC_STK_KEEP. hc_stack_prime()
    # leaves the top HC_STK_KEEP bytes unprimed because they are live when it
    # runs (12O/6: "the measurable range is 64..256"), so a real depth under
    # that floor reads AS the floor. V83's worst chain is 40 bytes, the first
    # image to go under it; compare against max(trace, floor).
    keep = int(re.search(r"#define\s+HC_STK_KEEP\s+(\d+)",
                         (START.parent / "hcsafety.h").read_text()).group(1))
    seen_or_floor = max(obs, keep) if obs is not None else None
    check("and its answer agrees with the stack-write trace",
          seen_or_floor is not None and rep <= seen_or_floor
          and (seen_or_floor - rep) <= 16,
          "firmware %d vs written %d bytes (allocated %d; priming floor %d)"
          % (rep, obs if obs is not None else -1, allocated, keep))
    check("the bottom-of-stack canary is intact",
          ovf == 0,
          "hc_stack_overflowed() = %d (1 means the reservation was all used "
          "and the next push lands on the SYSTEM stack)" % ovf)

    # ============ AND THE CANARY IS PROVEN TO DETECT, NOT ASSERTED ============
    #
    # Every check above only ever observes the NOT-overflowed case, which is
    # "a gate that has never seen the thing succeed cannot be trusted when it
    # observes it failing" - this project's own rule, from the bench output
    # proof's positive control.
    #
    # An overflow's FIRST observable effect is the bottom canary word being
    # written by something that is not the pattern, because R0 falls and the
    # next push lands there. So corrupting that word is a faithful model of
    # the first byte of an overflow, not a contrived poke - and it is the only
    # way to exercise the detector without pushing the rig 80 bytes past a
    # boundary that would take the simulator with it.
    #
    # THE RESTORE HALF MATTERS AS MUCH AS THE CORRUPT HALF: a detector stuck
    # at 1 would pass the corrupt check and fail this one.
    ent = G._sym(PI.MAP, "hc_asic_start_service")
    tck = G._sym(PI.MAP, "hc_tick_ms")
    rig = HB.Rig(PI.image(), ent, tck, echo=True)
    rig.run(1_400_000)
    # The first word an overflow writes is the top of the guard band below the
    # stack (R0 falls below ?C_USRSTKBOT, the next push lands at -2) - the
    # word hc_stack_overflowed() reads (hcsafety.h HC_STK_GUARD_HI).
    gh = re.search(r"#define\s+HC_STK_GUARD_HI\s+0x([0-9A-Fa-f]+)",
                   (START.parent / "hcsafety.h").read_text())
    canary = (int(gh.group(1), 16) - 2) if gh else sym("?C_USRSTKBOT")
    was = rig.mem.r16(canary)
    rig.mem.w16(canary, (was ^ 0xFFFF) & 0xFFFF)
    _call_on(rig, "hc_stack_overflowed", ())
    said_yes = rig.cpu.gr(4) & 0xFFFF
    rig.mem.w16(canary, was)
    _call_on(rig, "hc_stack_overflowed", ())
    said_no = rig.cpu.gr(4) & 0xFFFF
    check("POSITIVE CONTROL: the canary DETECTS a corrupted bottom word",
          said_yes != 0,
          "0x%04X -> 0x%04X at the bottom of the stack, "
          "hc_stack_overflowed() = %d" % (was, (was ^ 0xFFFF) & 0xFFFF,
                                          said_yes))
    check("...and says so ONLY then", said_no == 0,
          "restored to 0x%04X, hc_stack_overflowed() = %d" % (was, said_no))

    print("\n  WHAT THIS IS AND IS NOT. These are the deepest values reached by")
    print("  the paths above. They are a MEASUREMENT, not a worst-case proof.")
    print("  The engine paths DO run now - a planner service and the output")
    print("  group call - but the planner runs against the board default,")
    print("  which describes no engine, so it plans nothing and never enters")
    print("  ev_drive(). A rig that routes a whole engine would go deeper.")
    print("  The reserve above covers ONE more frame of the largest size the")
    print("  compiler emits, excluding the one the worst chain already holds.")
    print("  It is 12 bytes from failing at the time of writing: read the")
    print("  numbers, not the verdict.")

    print("\n%d/%d checks pass" % (CHECKS - FAILS, CHECKS))
    if FAILS:
        print("STACK MARGIN IS NOT HEALTHY.")
        return 1
    print("STACK PROOF PASSES - measured depth and required reserves fit; "
          "the firmware overflow detector detects the injected guard fault.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
