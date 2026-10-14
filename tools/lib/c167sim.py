#!/usr/bin/env python3
r"""
C167 instruction-level simulator, enough of the ISA to execute HaniCore startup
code out of a real 1 MB flash image and say exactly where it faults.

Built 2026-08-22 so firmware questions get a deterministic answer instead of a
bench flash cycle. Traps modelled: unmapped access, stack overflow/underflow,
SRST, illegal opcode, and unimplemented opcode (reported, never guessed).

EVERY MOV AND MOVB SETS N AND Z. That is the C166 core's behaviour and it was
missing from most of the MOV forms here until 2026-09-03, so a

    MOV   R4,[R0]
    JMPR  cc_NZ,...

pair branched on whatever flags the PREVIOUS instruction had left. It looked
exactly like two different C bugs in hcnvm.c and was chased as such twice.
tests/simulator/sim_flag_test.py is the regression, and ten of its eleven checks fail
against the simulator as it was. Fourth defect of this kind - see
tools/sim_math_test.py for the shift-pair one.

    py tools\lib\c167sim.py <image.bin> <seg:off> [steps] [--trace N]
    py tools\lib\c167sim.py bins\hanicore\x.bin 89:7666 200000 --trace 40

Memory model for this ECU:
  flash   : the image, at segments 0x00-0x0F and aliased at 0x80-0x8F
  IRAM    : 0x00F200-0x00FDFF        SFR: 0x00FE00-0x00FFFF
  ESFR    : 0x00F000-0x00F1FF        ext RAM: 0x380000-0x387FFF
  ASIC    : 0x480000-0x4800FF
"""
from __future__ import annotations
import sys

# THREE KILOBYTES, NOT TWO (2026-10-06). This ECU's CPU is a C167CS-class
# part: the boot block RAM-tests 0xF200..0xFDFA and resets on a mismatch, the
# OEM application keeps variables at 0xF230/0xF238/0xF23C (target OEM firmware
# seg88:160E, 88:F6A4, 89:4FC0) and the sibling ME7.1.1 A2L T44HEH0 declares
# SY_C167CS = 1. The model stopped at the C167CR's 0xF600 until HaniCore moved
# its user stack to 0xF400, which then read back as unmapped.
IRAM_LO, IRAM_HI = 0x00F200, 0x00FDFF
SFR_LO, SFR_HI = 0x00FE00, 0x00FFFF
ESFR_LO, ESFR_HI = 0x00F000, 0x00F1FF
XRAM_LO, XRAM_HI = 0x380000, 0x387FFF
ASIC_LO, ASIC_HI = 0x480000, 0x4800FF
# The 05.12 bootblock RAM-tests logical 0xE000-0xE7FE and that test PASSES on the
# real ECU, so writable memory is mapped there. Model it as RAM.
LRAM_LO, LRAM_HI = 0x00E000, 0x00EFFF


class Trap(Exception):
    pass


# ============================================================ interrupts ====
#
# The C167 trap numbers on THIS silicon are measured, not taken from the
# standard table - the standard table is wrong here (it puts T8INT at vector
# 0x0FC; the hardware puts it at 0x0F8). Keep this in step with the TGT_TRAP_*
# defines in hctarget.h.
#
#   0x15  CC5INT   MEASURED 2026-08-23 (capQseen tracked umQseen exactly)
#   0x3E  T8INT    MEASURED 2026-08-23 (hcFirstVec == hcLastVec, tick 1009/s)
#   0x27  S0RINT   the standard table's ASC0 receive. NOT assumed: the firmware
#                  probes it at boot and publishes what really fired as
#                  s0rTrap, so the bench settles it either way.
#   others: inferred from CC0INT = 0x10 + n, which CC5 confirms. They will
#   confirm themselves the same way - a wrong number simply never fires.
IC_TRAP = {
    0xFF78: 0x10,   # CC0IC
    0xFF7A: 0x11,   # CC1IC
    0xFF7C: 0x12,   # CC2IC
    0xFF7E: 0x13,   # CC3IC
    0xFF82: 0x15,   # CC5IC   MEASURED
    0xFF84: 0x16,   # CC6IC   bench crank generator
    0xF160: 0x30,   # CC16IC  V97 knock window MF (P8.0) - the OEM ME7.1.1's
                    #         own vector slot 0x30 (0x0200C0) JMPS to its
                    #         knock-window ISR 0x894C1C (docs/ARCHITECTURE.md)
    0xF18C: 0x37,   # CC23IC  injector EV4, P8.7 - the trap numbers here do
    0xF192: 0x3C,   # CC28IC  injector EV3, P7.4   NOT follow CAPCOM1's
    0xF194: 0x44,   # CC29IC  injector EV2, P7.5   0x10 + n. They come from the
    0xF196: 0x45,   # CC30IC  injector EV1, P7.6   M744 source and are
                    #         corroborated by our own stock image's live
                    #         vector table - see hctarget.h.
    0xFF86: 0x17,   # CC7IC   the serial drain tick, when ASC0's own interrupt
                    #         cannot be identified
    0xFF88: 0x18,   # CC8IC
    0xFF8A: 0x19,   # CC9IC
    0xFF96: 0x1F,   # CC15IC
    # The SSC nodes. PROVEN from the OEM ME7.1.1 second-level vector table: slot
    # 0x2E points at 0x8234E0, the OEM's own SSC receive ISR, so on this part
    # SSC TX/RX/ERR are 0x2D/0x2E/0x2F - NOT the 0x29/0x2A/0x2B of the generic
    # C167CR table. (0x2E is listed twice here: T0IC below carries the ME7.5
    # board's number. Only one of the two is ever enabled in a given image.)
    0xFF72: 0x2D,   # SSCTIC  transmit / PEC0 block end
    0xFF74: 0x2E,   # SSCRIC  receive  / PEC4 block end
    0xFF76: 0x2F,   # SSCEIC  error
    0xFF9C: 0x2E,   # T0IC
    0xF172: 0x39,   # ME711 CC25 deadline compare
    0xF174: 0x3A,   # CC26IC  ME711 planner - a SOFTWARE-set request (2026-10-06)
    0xF176: 0x3B,   # CC27IC  ME711 S5500 exchange - SOFTWARE-set by the tick (2026-10-13)
    0xF19C: 0x47,   # S0TBIC  ASC0 transmit buffer empty (ME711 reply job, 2026-10-06)
    0xF17A: 0x3D,   # T7IC
    0xF17C: 0x3E,   # T8IC    MEASURED
    0xFF6E: 0x27,   # S0RIC   ASC0 receive - the standard table's number, and
                    #         the firmware CHECKS it at boot rather than
                    #         trusting it. A missing entry here presents the
                    #         same way a wrong trap number does on hardware:
                    #         the request latches and the handler never runs.
}

# Under ROMEN=1 the internal mask ROM forwards interrupt N to seg82:N*4, where
# the relocated vector table holds a JMPS to the handler. Modelling it that way
# rather than jumping straight to the handler means the sim executes the very
# same table the hardware does - so a broken table shows up here too.
VECTOR_SEG = 0x82

# Timer file: name -> (counter addr, control addr, run bit)
# The shipped modelling default.  See CPU.__init__ for why a
# latency-measuring gate must override it rather than inherit it.
DEFAULT_STEPS_PER_TICK = 2

TIMERS = {
    "T0": (0xFE50, 0xFF50, 0x0040),
    "T1": (0xFE52, 0xFF50, 0x4000),
    "T7": (0xF050, 0xFF20, 0x0040),
    "T8": (0xF052, 0xFF20, 0x4000),
}
TIMER_OVF_IC = {"T0": 0xFF9C, "T7": 0xF17A, "T8": 0xF17C}

# CAPCOM RELOAD REGISTERS - MODELLED FROM V50 ON, AND THE OMISSION MATTERED.
#
# [DS] C167CR Derivatives User's Manual V3.1 (2000-03), section 15, The
# Capture/Compare Units:
#
#     "When a timer overflows from FFFFH to 0000H it is reloaded with the
#      value stored in its respective reload register TxREL."
#
# Unconditional - the CAPCOM timers have no reload-enable bit. This simulator
# used to set the timer to 0 on overflow and ignore TxREL entirely, which was
# harmless only because every HaniCore build up to V49 reloaded T8 in software
# from inside hc_tick_isr(). V50 stops doing that and relies on the hardware
# reload, so an unfixed simulator would model V50's 1 ms tick as a 52.4 ms one
# and every timing gate would report a phantom regression.
#
# tests/simulator/sim_capcom_reload_test.py is this behaviour's own regression, and it
# fails against the pre-V50 model.
TIMER_REL = {"T0": 0xFE54, "T1": 0xFE56, "T7": 0xF054, "T8": 0xF056}

# CAPCOM channels a harness can drive an edge on:
#   channel -> (capture register, interrupt control register, timebase)
# Pins are from the Bosch schematic, see docs/ARCHITECTURE.md.
CC_CHAN = {
    0:  (0xFE80, 0xFF78, "T0"),    # P2.0  coil A, ZUE1I
    1:  (0xFE82, 0xFF7A, "T0"),    # P2.1  coil B, ZUE2I
    2:  (0xFE84, 0xFF7C, "T0"),    # P2.2  coil C, ZUE3I
    3:  (0xFE86, 0xFF7E, "T0"),    # P2.3  coil D, ZUE4I
    5:  (0xFE8A, 0xFF82, "T0"),    # P2.5  UMKOM
    6:  (0xFE8C, 0xFF84, "T0"),    # P2.6  bench crank generator
    7:  (0xFE8E, 0xFF86, "T0"),    # P2.7  serial drain tick, compare only
    # CAPCOM2. These run against T7, not T0 - a different timer file, which is
    # exactly why the injector code may never borrow the ignition scheduler's
    # arithmetic.
    25: (0xFE72, 0xF172, "T7"), # CC25, verified against the compiled reg167.h
    16: (0xFE60, 0xF160, "T7"),    # P8.0  V97 knock window MF (compare)
    23: (0xFEAE, 0xF18C, "T7"),    # P8.7  injector EV4
    28: (0xFEB8, 0xF192, "T7"),    # P7.4  injector EV3
    29: (0xFEBA, 0xF194, "T7"),    # P7.5  injector EV2
    30: (0xFEBC, 0xF196, "T7"),    # P7.6  injector EV1
    8:  (0xFE90, 0xFF88, "T0"),    # P2.8  cam,   NWDG
    9:  (0xFE92, 0xFF8A, "T0"),    # P2.9  cam 2, NWDG2
    13: (0xFE9A, 0xFF92, "T0"),    # P2.13 tacho TN (compare mode 1, 2026-10-11)
    15: (0xFE9E, 0xFF96, "T0"),    # P2.15 crank, KWDG
}


class Mem:
    def __init__(self, image: bytes):
        # MUTABLE, because the firmware now writes to it. See _flash_write.
        self.flash = bytearray(image)
        self.iram = bytearray(IRAM_HI - IRAM_LO + 1)
        self.xram = bytearray(XRAM_HI - XRAM_LO + 1)
        self.asic = bytearray(ASIC_HI - ASIC_LO + 1)
        self.lram = bytearray(LRAM_HI - LRAM_LO + 1)
        self.sfr = {}
        self.esfr = {}
        # INPUT PINS THAT READ HIGH WHATEVER THE LATCH HOLDS (2026-10-14):
        # silicon reads the pin of an input, and the K-line RXD (P3.11) idles
        # high through its pull-up. Returning the latch (0) showed the
        # firmware a line held LOW forever. A rig that drives the line clears
        # the bit here (or overrides the read, as the KWP tester does).
        self.pin_hi = {0xFFC4: 0x0800}
        # Firmware may write an IC register with IR already set (notably the
        # live-Burn save/restore path).  Hardware arbitrates that request; an
        # earlier simulator revision only knew about requests raised by its
        # timer helpers, so a software-restored IR could remain set forever.
        self.ic_write_epoch = 0
        self.flash_writes = []

        # ---------------------------------------------- the flash device ----
        #
        # A model of the 29F800BB, because the calibration burn writes to it and
        # a burn that goes wrong does not cost a test - it costs an ECU that
        # will not boot. The command set is AMD's: two unlock cycles at word
        # 0x555 and 0x2AA, then 0x80/0x30 to erase a sector or 0xA0 to program
        # a word.
        #
        # Two things are modelled that a naive "just write it" would not, and
        # both of them are the point:
        #
        #   PROGRAM CAN ONLY CLEAR BITS. A word is ANDed, never assigned. A
        #   burn that forgot to erase first would silently work in a simpler
        #   model and silently corrupt on the bench.
        #
        #   THE DEVICE IS BUSY AFTERWARDS, and while it is busy it answers
        #   reads with status instead of memory. The firmware's poll loops
        #   depend on that, and so does the reason the programmer has to run
        #   out of RAM: fl_fetch_while_busy counts every INSTRUCTION FETCH that
        #   lands on the chip while it is busy, which on real silicon is the
        #   CPU executing status bits. It must stay zero.
        self.fl_state = 0
        self.fl_busy = 0
        self.fl_fetch_while_busy = 0
        self.fl_erases = []
        self.fl_programs = 0
        self.fetching = False

        # ---------------------------------------- the sector erase, V53 ----
        #
        # THE OLD MODEL ERASED A SECTOR INSTANTLY and set fl_busy to six reads.
        # That is fine for a firmware that never erases, which is what V40..V52
        # were, and useless for one that does: it could not exercise a single
        # slice, and it could not produce the state that actually matters,
        # which is a sector caught PART WAY through.
        #
        # What the real part does, and what this now does:
        #
        #   * an embedded erase PRE-PROGRAMS the whole sector to 0x00 before
        #     erasing it, so an erase that is cut short leaves the sector
        #     neither blank nor valid. That is exactly the state an aborted
        #     reclaim has to be recoverable from, so the model produces it;
        #   * while it is running, the device is single-bank and EVERY read
        #     returns status - which is why the eraser has to run from SRAM;
        #   * Erase Suspend (B0) stops it and hands back a readable device for
        #     every sector EXCEPT the one being erased. That is the whole
        #     mechanism that lets the raster and the watchdog survive a
        #     multi-second erase, so it is modelled rather than assumed;
        #   * Erase Resume (30) continues it.
        #
        # fl_erase_left counts POLLS of the erasing sector, not wall time: the
        # firmware's slice is bounded by T7, so how many polls fit in a slice
        # is the simulator's own business, and what a gate needs is that the
        # erase takes MANY slices rather than one.
        self.fl_erase_sector = None      # (lo, hi) file offsets, or None
        self.fl_erase_left = 0
        self.fl_suspended = False
        self.fl_erase_suspends = 0
        self.fl_erase_resumes = 0
        self.fl_erase_completed = 0
        self.fl_erase_polls = 0
        # How much work one sector erase is, in polls of the erasing sector.
        #
        # CHOSEN FROM THE FIRMWARE'S OWN SLICE, NOT PICKED. HCNV_ERASE_SLICE_US
        # is 1000 us and the eraser's poll loop is a handful of instructions,
        # so one slice gets through a few thousand polls. 4000 let the whole
        # erase finish inside ONE slice and the rotation proof duly reported a
        # single suspend - a gate that never sees a second slice is not testing
        # the slicing. 120000 is about thirty slices, which is the right shape
        # against a real ~2 s erase at 1 ms a slice without making the gate
        # take an hour.
        self.fl_erase_work = 120000

    def r8(self, a: int) -> int:
        a &= 0xFFFFFF
        if LRAM_LO <= a <= LRAM_HI:
            return self.lram[a - LRAM_LO]
        if IRAM_LO <= a <= IRAM_HI:
            return self.iram[a - IRAM_LO]
        if ESFR_LO <= a <= ESFR_HI:
            return (self.esfr.get(a & ~1, 0) >> (8 * (a & 1))) & 0xFF
        if SFR_LO <= a <= SFR_HI:
            # ZEROS (0xFF1C) and ONES (0xFF1E) are real C16x SFRs that always
            # read 0x0000 and 0xFFFF. The Keil C166 compiler uses them as its
            # constant sources: "SUB var,ONES" is how it writes var += 1, and
            # "MOV var,ZEROS" is how it writes var = 0. Without them every such
            # variable silently stayed at its old value.
            if a & ~1 == 0xFF1C:
                return 0x00
            if a & ~1 == 0xFF1E:
                return 0xFF
            return ((self.sfr.get(a & ~1, 0) | self.pin_hi.get(a & ~1, 0))
                    >> (8 * (a & 1))) & 0xFF
        if XRAM_LO <= a <= XRAM_HI:
            return self.xram[a - XRAM_LO]
        if ASIC_LO <= a <= ASIC_HI:
            return self.asic[a - ASIC_LO]
        seg = a >> 16
        if seg <= 0x0F or 0x80 <= seg <= 0x8F:
            off = ((seg & 0x0F) << 16) | (a & 0xFFFF)
            if off >= len(self.flash):
                raise Trap("read past end of flash @0x%06X" % a)
            if self.fl_erase_sector is not None:
                lo, hi = self.fl_erase_sector
                if not self.fl_suspended:
                    # RUNNING: single-bank, so the WHOLE device answers with
                    # status. An instruction fetch landing here is the CPU
                    # executing status bits, which is the failure the relocated
                    # eraser exists to avoid.
                    if self.fetching:
                        self.fl_fetch_while_busy += 1
                    self.fl_erase_polls += 1
                    self.fl_erase_left -= 1
                    if self.fl_erase_left <= 0:
                        for i in range(lo, min(hi, len(self.flash))):
                            self.flash[i] = 0xFF
                        self.fl_erase_sector = None
                        self.fl_erase_completed += 1
                        return self.flash[off]      # DQ7 reads back as 1
                    return 0x00                      # DQ7 low: not finished
                if lo <= off < hi:
                    # SUSPENDED: the erasing sector still answers with status.
                    return 0x00
                # SUSPENDED: every other sector reads normally, which is what
                # lets the CPU fetch code and service the raster.
            if self.fl_busy > 0:
                # Busy: the device answers with status, not memory. An
                # instruction fetch landing here is the failure this whole
                # design exists to avoid - the CPU would be executing status
                # bits - so it is counted rather than tolerated.
                if self.fetching:
                    self.fl_fetch_while_busy += 1
                self.fl_busy -= 1
                return 0x00                      # DQ7 low: not finished
            return self.flash[off]
        raise Trap("read from UNMAPPED address 0x%06X" % a)

    def w8(self, a: int, v: int) -> None:
        a &= 0xFFFFFF
        v &= 0xFF
        if LRAM_LO <= a <= LRAM_HI:
            self.lram[a - LRAM_LO] = v
            return
        if IRAM_LO <= a <= IRAM_HI:
            self.iram[a - IRAM_LO] = v
            return
        if ESFR_LO <= a <= ESFR_HI:
            k = a & ~1
            self.esfr[k] = (self.esfr.get(k, 0) & ~(0xFF << (8 * (a & 1)))) | (v << (8 * (a & 1)))
            if k in IC_TRAP:
                self.ic_write_epoch += 1
            return
        if SFR_LO <= a <= SFR_HI:
            k = a & ~1
            self.sfr[k] = (self.sfr.get(k, 0) & ~(0xFF << (8 * (a & 1)))) | (v << (8 * (a & 1)))
            if k in IC_TRAP:
                self.ic_write_epoch += 1
            return
        if XRAM_LO <= a <= XRAM_HI:
            self.xram[a - XRAM_LO] = v
            return
        if ASIC_LO <= a <= ASIC_HI:
            self.asic[a - ASIC_LO] = v
            return
        seg = a >> 16
        if seg <= 0x0F or 0x80 <= seg <= 0x8F:
            # Byte writes are not how this device is driven - every command and
            # every datum is a word - so they are only recorded, as before.
            self.flash_writes.append(a)
            return
        raise Trap("write to UNMAPPED address 0x%06X" % a)

    # ------------------------------------------------------ the flash device
    SECTORS = ([(0x000000, 0x004000), (0x004000, 0x006000),
                (0x006000, 0x008000), (0x008000, 0x010000)]
               + [(b, b + 0x10000) for b in range(0x010000, 0x100000, 0x10000)])

    def _sector_of(self, off):
        for lo, hi in self.SECTORS:
            if lo <= off < hi:
                return lo, hi
        return None

    def _flash_write(self, a, v):
        """One 16-bit cycle into the 29F800BB command state machine."""
        off = ((a >> 16 & 0x0F) << 16) | (a & 0xFFFF)
        cmd = v & 0xFF
        # The device decodes A0..A10 for its unlock addresses, so the byte
        # addresses that matter are 0xAAA and 0x554 within any 4 KB.
        low = off & 0xFFF
        self.flash_writes.append(a)

        # SUSPEND AND RESUME ARE SINGLE UNPREFIXED CYCLES and are only
        # meaningful while an erase is outstanding, so they are decoded before
        # the unlock state machine rather than inside it. Addresses are
        # don't-care for both, exactly as the datasheet says.
        if self.fl_erase_sector is not None:
            if cmd == 0xB0:
                if not self.fl_suspended:
                    self.fl_suspended = True
                    self.fl_erase_suspends += 1
                self.fl_state = 0
                return
            if cmd == 0x30 and self.fl_suspended:
                self.fl_suspended = False
                self.fl_erase_resumes += 1
                self.fl_state = 0
                return

        st = self.fl_state
        self.fl_state = 0

        if st == 0:
            if low == 0xAAA and cmd == 0xAA:
                self.fl_state = 1
            return
        if st == 1:
            if low == 0x554 and cmd == 0x55:
                self.fl_state = 2
            return
        if st == 2:
            if low == 0xAAA and cmd == 0xA0:
                self.fl_state = 10          # program setup
            elif low == 0xAAA and cmd == 0x80:
                self.fl_state = 3           # erase setup
            return
        if st == 3:
            if low == 0xAAA and cmd == 0xAA:
                self.fl_state = 4
            return
        if st == 4:
            if low == 0x554 and cmd == 0x55:
                self.fl_state = 5
            return
        if st == 5:
            if cmd == 0x30:
                sec = self._sector_of(off)
                if sec is None:
                    raise Trap("sector erase outside the device @0x%06X" % a)
                lo, hi = sec
                # PRE-PROGRAM TO 0x00 FIRST, which is what the embedded
                # algorithm really does and what makes an interrupted erase
                # produce a sector that is neither blank nor valid. The 0xFF
                # only appears when the erase COMPLETES, in r8() above.
                for i in range(lo, min(hi, len(self.flash))):
                    self.flash[i] = 0x00
                self.fl_erases.append(lo)
                self.fl_erase_sector = (lo, min(hi, len(self.flash)))
                self.fl_erase_left = self.fl_erase_work
                self.fl_suspended = False
            elif low == 0xAAA and cmd == 0x10:
                raise Trap("CHIP erase requested - this would take the ECU "
                           "with it, and nothing in this firmware may ask")
            return
        if st == 10:
            if off + 1 < len(self.flash):
                # A program can only clear bits. Anything that expects to set
                # one is a burn that forgot to erase.
                self.flash[off] &= v & 0xFF
                self.flash[off + 1] &= (v >> 8) & 0xFF
                self.fl_programs += 1
                self.fl_busy = 4
            return

    def r16(self, a):
        return self.r8(a) | (self.r8(a + 1) << 8)

    def w16(self, a, v):
        # THE RANGE TEST HAS TO MATCH w8's, and the first version of it did
        # not: it asked only whether the SEGMENT was a flash segment, and
        # segment 0 contains the internal RAM, the stack and every SFR. Every
        # 16-bit write in the firmware went into the flash command machine and
        # was discarded. The boot died on a RET with an empty stack, which is
        # about as far from the cause as a symptom can get.
        aa = a & 0xFFFFFF
        special = (LRAM_LO <= aa <= LRAM_HI or IRAM_LO <= aa <= IRAM_HI
                   or ESFR_LO <= aa <= ESFR_HI or SFR_LO <= aa <= SFR_HI
                   or XRAM_LO <= aa <= XRAM_HI or ASIC_LO <= aa <= ASIC_HI)
        if not special:
            seg = aa >> 16
            if seg <= 0x0F or 0x80 <= seg <= 0x8F:
                self._flash_write(aa, v & 0xFFFF)
                return
        self.w8(a, v & 0xFF)
        self.w8(a + 1, (v >> 8) & 0xFF)


class CPU:
    def __init__(self, mem: Mem, seg: int, off: int):
        self.m = mem
        self.csp, self.ip = seg, off
        # state as the 05.12 bootblock leaves it before jumping to the app
        self.m.sfr[0xFE10] = 0xF740      # CP
        self.m.sfr[0xFE12] = 0xF700      # SP
        self.m.sfr[0xFE14] = 0xF614      # STKOV
        self.m.sfr[0xFE16] = 0xF700      # STKUN
        self.m.sfr[0xFF12] = 0xE204      # SYSCON
        for i, v in enumerate((0x0000, 0x0205, 0x00E0, 0x0003)):
            self.m.sfr[0xFE00 + 2 * i] = v
        self.z = self.c = self.n = 0
        self.ext = None
        self.steps = 0
        self.srvwdt = 0
        self.einit_done = True           # bootblock already ran EINIT

        # --- interrupts and timers ---------------------------------------
        # steps_per_tick is how many simulated instructions make one timer
        # tick. What matters for most gates is that T0/T7/T8 all advance from
        # the SAME counter, because on the real ECU they share one prescaler
        # and the whole watchdog table depends on that being true.
        #
        # BUT IT IS ALSO A RATIO, AND THE RATIO IS A HARDWARE FACT.
        # The CAPCOM timers run at TGT_TICKS_PER_MS_X10 = 1.25 MHz and the CPU
        # retires roughly fCPU/4 = 10 MIPS, so the part executes EIGHT
        # instructions per timer tick.  This default of 2 makes simulated time
        # run FOUR TIMES TOO FAST against the instruction stream: every
        # timer-driven interrupt then fires four times as often per instruction
        # as it can on the part, and any firmware whose service interval is
        # gated on hc_tick_ms is measured against the wrong millisecond.
        #
        # Gates that only count instructions or check functional behaviour are
        # unaffected and keep this default.  Gates that measure SERVICE LATENCY
        # must not: me711_heartbeat_gap_proof.Rig raises it to the derived
        # value (see DEFAULT_STEPS_PER_TICK below), which is what makes a
        # simulated millisecond and a reported hardware millisecond the same
        # millisecond.  See the maintainer's design records.
        self.steps_per_tick = DEFAULT_STEPS_PER_TICK
        self.tacc = 0
        self.irq_pending = set()         # IC addresses whose IR we have set
        self.irq_taken = 0               # diagnostics for a test harness
        self.captures_refused = 0    # edges dropped: channel not configured
        self.pec6_moved = 0          # ASC0 bytes PEC6 stored (2026-10-06)
        self.pec6_lost = 0           # ... arriving with PECC6 COUNT at zero
        self.compares_hit = 0        # compare matches raised
        self.cc_toggles = []         # (channel, steps) compare-mode-1 pin toggles
        # irq_log IS CAPPED AT 4000 ENTRIES, so it is a sample and not a
        # census. irq_count is the census: one uncapped counter per trap.
        #
        # This distinction is not academic. sim_irq_test's "injected CC5
        # capture is serviced" check counted occurrences of trap 0x15 by
        # scanning irq_log - after a 3 000 000-step run that had already
        # filled the log with trap 0x17. The CC5 interrupt fired, was
        # delivered and cleared its own request; the log simply had no room
        # left to record it, and the gate had been reporting "0 -> 0" ever
        # since. A gate that is red for a reason unconnected to the firmware
        # gets learned and ignored, which costs the same as one that is
        # falsely green.
        self.irq_log = []
        self.irq_count = {}              # trap -> times delivered, UNCAPPED
        self.ic_write_seen = self.m.ic_write_epoch
        for name, (addr, _c, _r) in TIMERS.items():
            self._tset(addr, 0)

    def cp(self):
        return self.m.sfr.get(0xFE10, 0xFC00)

    # ------------------------------------------------------------ SFR access
    # Direct dictionary access, deliberately bypassing Mem.r16/w16: this runs
    # on every simulated instruction and the harnesses do not override these
    # addresses.
    def _sget(self, a):
        if a < 0xFE00:
            return self.m.esfr.get(a, 0)
        return self.m.sfr.get(a, 0) | self.m.pin_hi.get(a, 0)

    def _sset(self, a, v):
        (self.m.esfr if a < 0xFE00 else self.m.sfr)[a] = v & 0xFFFF

    _tset = _sset

    # ------------------------------------------------------------- timers ---
    def tick_timers(self):
        """Advance every running timer by one tick and flag any overflow."""
        self.tacc += 1
        if self.tacc < self.steps_per_tick:
            return
        self.tacc = 0
        for name, (addr, con, runbit) in TIMERS.items():
            if not (self._sget(con) & runbit):
                continue
            v = (self._sget(addr) + 1) & 0x1FFFF
            if v > 0xFFFF:               # overflowed FFFFH -> 0000H
                # UM section 15: reloaded from TxREL, unconditionally. A
                # TxREL of 0 gives the old "wrap to zero" behaviour, so every
                # pre-V50 build is unaffected by modelling this.
                v = self._sget(TIMER_REL[name])
                ic = TIMER_OVF_IC.get(name)
                if ic is not None:
                    self._sset(ic, self._sget(ic) | 0x80)   # IR
                    self.irq_pending.add(ic)
            self._sset(addr, v)
        self.check_compares()

    def check_compares(self):
        """Raise a request on any CAPCOM channel whose compare value is now.

        Without this a compare-mode channel is inert and the angle scheduler
        can never be proven off hardware - schedArmed would climb and
        schedFired would sit at zero, which is indistinguishable from the
        firmware getting the mode encoding wrong.

        Modes 4-7 are the compare modes; 4 is interrupt-only with several
        matches allowed per timer period, which is what two edges (dwell and
        spark) on one channel inside one period needs.
        """
        for ch, (ccx, ccic, tname) in CC_CHAN.items():
            reg, shift = self.CCM_OF[ch]
            mode = (self._sget(reg) >> shift) & 0x07
            if mode < 4:
                continue                  # not a compare mode
            tname = self.cc_timebase(ch, tname)
            if self._sget(ccx) != self._sget(TIMERS[tname][0]):
                continue
            # COMPARE MODE 1 (CCMOD 101) DRIVES THE PIN (2026-10-11, the
            # tacho on CC13/P2.13): "the corresponding port output latch is
            # toggled" on EVERY match - whether or not the previous request
            # is still standing (C167CR UM, CAPCOM compare modes). Modes 0
            # and 2 leave the pin alone; mode 3 (set on match, clear on
            # overflow) is not used by any image and not modelled. CAPCOM1
            # channel n is P2.n. Each toggle is logged for gates.
            if mode == 5 and ch < 16:
                self._sset(0xFFC0, self._sget(0xFFC0) ^ (1 << ch))
                self.cc_toggles.append((ch, self.steps))
            if self._sget(ccic) & 0x80:
                continue                  # request already standing
            self._sset(ccic, self._sget(ccic) | 0x80)
            self.irq_pending.add(ccic)
            self.compares_hit += 1

    # ------------------------------------------------------------ capture ---
    # Which CCM register and nibble configures each channel, so a capture can
    # be refused when the channel is not actually set up for one. Modelling
    # this is not pedantry: firmware that clears a CCM after configuring it
    # produces no teeth at all on hardware, and a simulator that ignores CCM
    # reports a happy capture and hides the bug.
    CCM_OF = {0: (0xFF52, 0), 1: (0xFF52, 4), 2: (0xFF52, 8), 3: (0xFF52, 12),
              5: (0xFF54, 4), 6: (0xFF54, 8), 7: (0xFF54, 12),
              25: (0xFF26, 4),
              16: (0xFF22, 0),
              23: (0xFF26, 12), 28: (0xFF2A, 0), 29: (0xFF2A, 4),
              30: (0xFF2A, 8),
              8: (0xFF56, 0), 9: (0xFF56, 4), 13: (0xFF58, 4),
              15: (0xFF58, 12)}

    def cc_timebase(self, channel, declared):
        """Which timer this channel is actually running against.

        BIT 3 OF THE CCM NIBBLE IS THE TIMEBASE SELECT, and it applies to
        COMPARES exactly as it applies to captures: 0 picks the unit's base
        timer, 1 picks the other one. CAPCOM1 chooses T0 or T1; CAPCOM2
        chooses T7 or T8.

        MODELLED FROM V68 ON, AND THE OMISSION WOULD HAVE PRESENTED AS A
        FIRMWARE BUG. capture() has resolved this bit since the ME7.1.1
        decoder needed it; check_compares() did not, and read the timebase out
        of CC_CHAN's declaration instead. Every compare this simulator has ever
        served happened to be an ME7.5 coil or the serial drain, both on T0 -
        so the defect was invisible.

        It stops being invisible the moment the ME7.1.1 angle scheduler
        programs a coil compare, because ITS deadlines are T1 values:
        ev_deadline is derived from the crank capture stamp and the crank runs
        against T1 (hctrig_me711.c, TGT_T1CON_RUNNING). A model comparing that
        value against T0 never matches, and "the compare never fires" is
        indistinguishable from the firmware getting the mode encoding wrong -
        which is the ninth time a gap in this simulator would have been read as
        a defect in the ECU. tests/simulator/sim_compare_timebase_test.py is the
        regression and it FAILS against the model as it stood.
        """
        reg, shift = self.CCM_OF[channel]
        alt = (self._sget(reg) >> shift) & 0x08
        if declared in ("T0", "T1"):
            return "T1" if alt else "T0"
        return "T8" if alt else "T7"

    def cc_enabled(self, channel):
        reg, shift = self.CCM_OF[channel]
        mode = (self._sget(reg) >> shift) & 0x07
        return mode in (1, 2, 3)          # capture on rise / fall / both

    def capture(self, channel):
        """Drive an edge on a CAPCOM channel, as the hardware would.

        Latches the channel's timebase into its capture register and raises the
        request. This is how a test harness feeds a crank or cam signal without
        any hardware: the firmware sees exactly what a real edge produces.
        """
        ccx, ccic, tname = CC_CHAN[channel]
        if not self.cc_enabled(channel):
            self.captures_refused += 1
            return                        # channel is not in a capture mode
        # The nibble's high bit selects the unit's other timer. Bosch ME7.1.1
        # uses mode A on CC8/9/15, so the crank and cams latch T1; ME7.5 uses
        # mode 1/2 and remains on T0. Shared with check_compares() since V68 -
        # see cc_timebase() for why having two answers was a latent defect.
        tname = self.cc_timebase(channel, tname)
        self._sset(ccx, self._sget(TIMERS[tname][0]))
        self._sset(ccic, self._sget(ccic) | 0x80)
        self.irq_pending.add(ccic)

    # ---------------------------------------------------------- interrupts --
    def check_irq(self):
        """Deliver the highest-priority pending interrupt, if any is allowed.

        Arbitration is by ILVL, and an interrupt is only taken if its level is
        strictly above the level currently running - which is what makes two
        handlers at the SAME ILVL unable to preempt each other. The firmware
        relies on that for the watchdog answer queue, so the sim has to model
        it rather than just "take the first pending".
        """
        # Synchronize requests written through IC registers by the linked
        # firmware.  Timer/capture helpers add their requests directly; this
        # epoch avoids scanning every IC on every simulated instruction.
        # PEC CHANNEL 6 ON ASC0 RECEIVE (2026-10-06, the ME7.1.1 K-line).
        # S0RIC = IE | ILVL 15 | GLVL 2 routes the receive request to PEC6
        # (C167CR UM 5.x): while the CPU runs below level 15 with IEN set, a
        # received byte is moved from S0RBUF to [DSTP6], DSTP6 increments and
        # COUNT counts down (0xFF = continuous). With COUNT already 0 the
        # request is a normal interrupt - on this ECU the boot block's S0RINT
        # - and the byte is lost. "A byte is waiting" is asked through the
        # harness's own S0RIC/S0RBUF model (Mem.r8 hooks), so every harness
        # that can feed the old drain feeds PEC6 too, unchanged.
        if (self._sget(0xFF6E) & 0x7F) == 0x7E:
            psw = self._sget(0xFF10)
            if (psw & 0x0800) and (psw >> 12) < 15 and (self.m.r8(0xFF6E) & 0x80):
                b = self.m.r8(0xFEB2)
                pecc = self._sget(0xFECC)
                cnt = pecc & 0xFF
                if cnt == 0:
                    self.pec6_lost += 1
                else:
                    d = self.m.r16(0xFCFA)
                    self.m.w8(d, b)
                    self.m.w16(0xFCFA, (d + 1) & 0xFFFF)
                    if cnt != 0xFF:
                        self._sset(0xFECC, (pecc & 0xFF00) | (cnt - 1))
                    self.pec6_moved += 1
        # S0TBIR is raised by the HARNESS's transmitter model (a byte moved
        # into the shift register), straight into the ESFR dictionary, so it
        # never passes through the firmware-write epoch below. Enabled, it is a
        # request (2026-10-06: the ME7.1.1 reply job runs on it).
        if (self.m.esfr.get(0xF19C, 0) & 0xC0) == 0xC0:
            self.irq_pending.add(0xF19C)
        if self.ic_write_seen != self.m.ic_write_epoch:
            for ic in IC_TRAP:
                if self._sget(ic) & 0x80:
                    self.irq_pending.add(ic)
                else:
                    self.irq_pending.discard(ic)
            self.ic_write_seen = self.m.ic_write_epoch
        if not self.irq_pending:
            return
        psw = self._sget(0xFF10)
        if not (psw & 0x0800):                     # IEN
            return
        cur = (psw >> 12) & 0x0F
        best = None
        for ic in tuple(self.irq_pending):
            v = self._sget(ic)
            if (v & 0xC0) != 0xC0:                 # IR and IE both set?
                if not (v & 0x80):
                    self.irq_pending.discard(ic)   # firmware cleared it
                continue
            ilvl = (v >> 2) & 0x0F
            if ilvl <= cur:
                continue
            glvl = v & 0x03
            if best is None or (ilvl, glvl) > (best[1], best[2]):
                best = (ic, ilvl, glvl)
        if best is None:
            return

        ic, ilvl, _glvl = best
        trap = IC_TRAP.get(ic)
        if trap is None:
            return
        self._sset(ic, self._sget(ic) & ~0x80)     # hardware clears IR on entry
        self.irq_pending.discard(ic)

        # The flags live outside the PSW word in this model, so they are packed
        # into the pushed copy - otherwise an ISR would silently corrupt the
        # condition codes of the code it interrupted. The pushed copy is the
        # WHOLE PSW including ILVL (C167CR UM 5.2): RETI must resume a
        # preempted handler at ITS level. Until 2026-10-07 this masked ILVL
        # (0x0FF0), so a handler that had been preempted resumed at level 0 and
        # could be re-entered by its own source on its own register bank (the
        # planner at ILVL 9 under a crank tooth, 5000+ rpm).
        saved = (psw & 0xFFF0) | (self.n) | (self.c << 1) | (self.z << 3)
        self.push(saved)
        self.push(self.csp)
        self.push(self.ip)
        self._sset(0xFF10, (psw & 0x0FFF) | (ilvl << 12))
        self.csp, self.ip = VECTOR_SEG, trap * 4
        self.irq_taken += 1
        self.irq_count[trap] = self.irq_count.get(trap, 0) + 1
        if len(self.irq_log) < 4000:
            self.irq_log.append((self.steps, trap))

    def gr(self, n):
        return self.m.r16(self.cp() + 2 * n)

    def sr(self, n, v):
        self.m.w16(self.cp() + 2 * n, v & 0xFFFF)

    def reg_addr(self, r, esfr=False):
        if r >= 0xF0:
            return self.cp() + 2 * (r & 0x0F)
        return (0xF000 if esfr else 0xFE00) + 2 * r

    def reg_addr_b(self, r, esfr=False):
        """Byte-operand form of reg_addr.

        For a BYTE instruction the short register range 0xF0-0xFF names the
        byte registers RL0..RH7, which are CP + n - NOT the word registers at
        CP + 2*n. Using reg_addr here made "CMPB RL7,#9" read R14 instead, so
        every unsigned-char loop ran forever.
        """
        if r >= 0xF0:
            return self.cp() + (r & 0x0F)
        # SFRs keep the WORD mapping even for byte instructions: the reg number
        # still selects a word-aligned SFR, and the byte form addresses its low
        # byte. Only the GPR range differs. Getting this wrong meant reg 0x8F
        # missed ONES (0xFF1E), so the compiler's "SUBB var,ONES" - which is how
        # it writes an unsigned char var++ - silently did nothing.
        return (0xF000 if esfr else 0xFE00) + 2 * r

    def mem_addr(self, a16):
        if self.ext:
            kind, val, _ = self.ext
            if kind == "S":
                return (val << 16) | (a16 & 0xFFFF)
            if kind == "P":
                return val * 0x4000 + (a16 & 0x3FFF)
        dpp = self.m.sfr.get(0xFE00 + 2 * (a16 >> 14), 0)
        return dpp * 0x4000 + (a16 & 0x3FFF)

    def push(self, v):
        sp = (self.m.sfr[0xFE12] - 2) & 0xFFFF
        if sp < self.m.sfr[0xFE14]:
            raise Trap("STACK OVERFLOW: SP=0x%04X < STKOV=0x%04X" % (sp, self.m.sfr[0xFE14]))
        self.m.sfr[0xFE12] = sp
        self.m.w16(sp, v)

    def pop(self):
        sp = self.m.sfr[0xFE12]
        v = self.m.r16(sp)
        nsp = (sp + 2) & 0xFFFF
        if nsp > self.m.sfr[0xFE16]:
            raise Trap("STACK UNDERFLOW: SP=0x%04X > STKUN=0x%04X" % (nsp, self.m.sfr[0xFE16]))
        self.m.sfr[0xFE12] = nsp
        return v

    def setzn(self, v):
        self.z = 1 if (v & 0xFFFF) == 0 else 0
        self.n = 1 if (v & 0x8000) else 0

    def setznb(self, v):
        """The BYTE form. N comes from bit 7, not bit 15."""
        self.z = 1 if (v & 0xFF) == 0 else 0
        self.n = 1 if (v & 0x80) else 0

    def alu16(self, base, x, y):
        """One 16-bit ALU operation with C166 flag semantics.

        ADDC and SUBC are the reason this exists. They were previously treated
        as plain ADD and SUB, which is wrong twice over:

          * the carry is an INPUT - `x + y + C` and `x - y - C` - so every
            32-bit sum or difference came out wrong in the high word;
          * their Z flag is STICKY. The C166 manual makes Z on ADDC/SUBC mean
            "the result is zero AND Z was already set", which is exactly what
            makes a multi-word compare work: SUB the low word, SUBC the high
            word, then test Z once.

        A 32-bit equality test compiles to precisely that pair, so with the old
        behaviour `if (magic == 0x48433031)` could take the wrong branch in the
        simulator while being perfectly correct on the hardware.

        Returns the raw (unmasked) result; the caller decides whether to store
        it - CMP variants do not.
        """
        if base == 0x00:                       # ADD
            r = x + y
            self.c = 1 if r > 0xFFFF else 0
            self.setzn(r)
        elif base == 0x10:                     # ADDC
            r = x + y + self.c
            zprev = self.z
            self.c = 1 if r > 0xFFFF else 0
            self.setzn(r)
            self.z = 1 if (self.z and zprev) else 0
        elif base in (0x20, 0x40):             # SUB, CMP
            r = x - y
            self.c = 1 if (x & 0xFFFF) < (y & 0xFFFF) else 0
            self.setzn(r)
        elif base == 0x30:                     # SUBC
            r = x - y - self.c
            zprev = self.z
            self.c = 1 if (x & 0xFFFF) < ((y & 0xFFFF) + self.c) else 0
            self.setzn(r)
            self.z = 1 if (self.z and zprev) else 0
        elif base == 0x50:                     # XOR
            r = x ^ y
            self.setzn(r)
        elif base == 0x60:                     # AND
            r = x & y
            self.setzn(r)
        else:                                  # 0x70 OR
            r = x | y
            self.setzn(r)
        return r

    def cond(self, cc):
        # C166 condition codes. 0xE = cc_UGT (C=0 and Z=0), 0xF = cc_ULE.
        return {0x0: True,
                0x1: self.z == 0,                     # cc_NET
                0x2: self.z == 1,                     # cc_Z / cc_EQ
                0x3: self.z == 0,                     # cc_NZ / cc_NE
                0x4: False,                           # cc_V   (V not tracked)
                0x5: True,                            # cc_NV
                0x6: self.n == 1,                     # cc_N
                0x7: self.n == 0,                     # cc_NN
                0x8: self.c == 1,                     # cc_C / cc_ULT
                0x9: self.c == 0,                     # cc_NC / cc_UGE
                0xA: (self.z == 0 and self.n == 0),   # cc_SGT (approx, V=0)
                0xB: (self.z == 1 or self.n == 1),    # cc_SLE
                0xC: self.n == 1,                     # cc_SLT
                0xD: self.n == 0,                     # cc_SGE
                0xE: (self.c == 0 and self.z == 0),   # cc_UGT
                0xF: (self.c == 1 or self.z == 1),    # cc_ULE
                }.get(cc, True)

    def fetch8(self):
        # Flagged so the flash model can tell an instruction fetch from a data
        # read. Executing out of a busy flash is the one failure the whole
        # copy-to-RAM design exists to prevent, and this is what proves it.
        self.m.fetching = True
        v = self.m.r8((self.csp << 16) | self.ip)
        self.m.fetching = False
        self.ip = (self.ip + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch8()
        return lo | (self.fetch8() << 8)

    PSW_ADDR = 0xFF10

    def psw_compose(self):
        """Write the live condition codes into the PSW word.

        The flags are kept as plain attributes for speed, which is fine until
        something addresses them AS BITS - and the C166 compiler does exactly
        that. `bit = someByte` compiles to `CMP` followed by
        `BMOVN dst, Z`, taking the destination bit straight out of PSW.Z.
        Without this the PSW word holds whatever it last happened to contain,
        so every such assignment silently used a stale flag. It cost four
        ignition coils that could be switched on and never off.
        """
        w = self.m.sfr.get(self.PSW_ADDR, 0) & ~0x000F
        w |= self.n | (self.c << 1) | (self.z << 3)
        self.m.sfr[self.PSW_ADDR] = w

    def psw_extract(self):
        """Take the condition codes back out, after a bit write into PSW."""
        w = self.m.sfr.get(self.PSW_ADDR, 0)
        self.n = w & 1
        self.c = (w >> 1) & 1
        self.z = (w >> 3) & 1

    def bitaddr(self, bo, bit):
        esfr = bool(self.ext and self.ext[0] == "R")
        if bo < 0x80:
            addr = (0xF000 if esfr else 0xFD00) + 2 * bo
        elif bo < 0xF0:
            addr = (0xF100 if esfr else 0xFF00) + 2 * (bo - 0x80)
        else:
            return self.cp() + 2 * (bo - 0xF0), bit
        if addr == self.PSW_ADDR:
            self.psw_compose()
        return addr, bit

    def _endext(self):
        if self.ext:
            k, v, c = self.ext
            self.ext = (k, v, c - 1) if c > 1 else None

    def step(self):
        self.steps += 1
        self.tick_timers()
        # Only between instructions, never in the middle of one, and never
        # while an EXTR/EXTP prefix is still in force - that prefix binds to
        # the instruction that follows it and an interrupt taken in between
        # would apply it to the handler's first instruction instead.
        if self.ext is None:
            self.check_irq()
        op = self.fetch8()
        esfr = bool(self.ext and self.ext[0] == "R")

        if op in (0xC6, 0xD6):                           # SCXT reg,#data16 / reg,mem
            # Switch context: push the register's current value, then load it.
            # Keil puts SCXT DPP3,#03H at the head of every interrupt handler
            # that touches an SFR, so without this the simulator cannot execute
            # a single ISR - which is exactly how it failed the first time
            # interrupts were delivered to it.
            rr = self.fetch8()
            if op == 0xC6:
                v = self.fetch16()
            else:
                v = self.m.r16(self.mem_addr(self.fetch16()))
            a = self.reg_addr(rr, esfr)
            self.push(self.m.r16(a))
            self.m.w16(a, v & 0xFFFF)
            self._endext(); return

        if op == 0xFB:                                   # RETI
            self.fetch8()
            self.ip = self.pop()
            self.csp = self.pop()
            psw = self.pop()
            self.n = psw & 1
            self.c = (psw >> 1) & 1
            self.z = (psw >> 3) & 1
            self._sset(0xFF10, psw & 0xFFF0)
            self._endext(); return

        if op in (0xA5, 0xA7, 0xB5, 0xB7):               # DISWDT/SRVWDT/EINIT/SRST
            self.fetch8(); self.fetch8(); self.fetch8()
            if op == 0xA7:
                self.srvwdt += 1
            if op == 0xB5:
                self.einit_done = True
            if op == 0xB7:
                raise Trap("SRST executed (software reset)")
            self._endext(); return
        if op == 0xCC:
            self.fetch8(); self._endext(); return

        if op == 0xD1:                                   # EXTR #n
            b = self.fetch8(); self.ext = ("R", 0, ((b >> 4) & 3) + 1); return
        if op == 0xDC:                                   # EXTP/EXTS Rw,#n
            b = self.fetch8()
            self.ext = ("P" if (b >> 4) & 4 else "S", self.gr(b & 0x0F), ((b >> 4) & 3) + 1)
            return
        if op == 0xD7:                                   # EXTP/EXTS #imm,#n
            b = self.fetch8(); val = self.fetch16()
            self.ext = ("P" if (b >> 4) & 4 else "S", val, ((b >> 4) & 3) + 1); return

        # Bit number lives in the HIGH nibble, so 0x0E/0x0F are bit 0 and are
        # perfectly valid - excluding them made every "bit 0" BCLR/BSET the
        # compiler emits for a boolean return run off into data.
        if (op & 0x0F) in (0x0E, 0x0F):                  # BCLR / BSET
            bit = op >> 4
            addr, b = self.bitaddr(self.fetch8(), bit)
            w = self.m.r16(addr)
            w = (w | (1 << b)) if (op & 0x0F) == 0x0F else (w & ~(1 << b))
            self.m.w16(addr, w)
            if addr == self.PSW_ADDR:
                self.psw_extract()
            self._endext(); return

        if op in (0xAA, 0xBA):                           # JBC / JNBS
            bo = self.fetch8(); rel = self.fetch8(); qb = self.fetch8()
            bit = qb >> 4
            addr, _ = self.bitaddr(bo, bit)
            w = self.m.r16(addr)
            st = (w >> bit) & 1
            take = st if op == 0xAA else (not st)
            if take:
                w = (w & ~(1 << bit)) if op == 0xAA else (w | (1 << bit))
                self.m.w16(addr, w)
                self.ip = (self.ip + ((rel - 256) if rel > 127 else rel) * 2) & 0xFFFF
            self._endext(); return

        if op in (0x8A, 0x9A):                           # JB / JNB
            # operand order is bitoff, rel, (q<<4) -- verified against
            # "9A 89 03 A0" = JNB SYSCON.10 (ROMEN), +6 bytes
            bo = self.fetch8(); rel = self.fetch8(); qb = self.fetch8()
            addr, _ = self.bitaddr(bo, qb >> 4)
            st = (self.m.r16(addr) >> (qb >> 4)) & 1
            if (st if op == 0x8A else (not st)):
                self.ip = (self.ip + ((rel - 256) if rel > 127 else rel) * 2) & 0xFFFF
            self._endext(); return

        if (op & 0x0F) == 0x0D:                          # JMPR cc,rel
            rel = self.fetch8()
            if self.cond(op >> 4):
                self.ip = (self.ip + ((rel - 256) if rel > 127 else rel) * 2) & 0xFFFF
            self._endext(); return
        if op == 0x9C:                                   # JMPI cc, [Rwn]
            # The compiler emits this for a switch: SHL the index by 2, ADD the
            # table base, then JMPI. The table at that base holds 4-byte JMPA
            # instructions, so the new IP is the REGISTER VALUE - we jump INTO
            # the table, not through a pointer stored in it. (Reading a word
            # there would give 0x00EA, the first half of a JMPA, which is not
            # an address.) First seen in the Bosch ASIC state machine.
            b = self.fetch8()
            cc, n = b >> 4, b & 0x0F
            if self.cond(cc):
                self.ip = self.gr(n) & 0xFFFF
            self._endext(); return
        if op == 0xEA:                                   # JMPA
            cc = self.fetch8() >> 4; a = self.fetch16()
            if self.cond(cc):
                self.ip = a
            self._endext(); return
        if op == 0xFA:                                   # JMPS
            s = self.fetch8(); o = self.fetch16(); self.csp, self.ip = s, o
            self._endext(); return
        if op == 0xBB:                                   # CALLR
            rel = self.fetch8(); self.push(self.ip)
            self.ip = (self.ip + ((rel - 256) if rel > 127 else rel) * 2) & 0xFFFF
            self._endext(); return
        if op == 0xDA:                                   # CALLS
            s = self.fetch8(); o = self.fetch16()
            self.push(self.csp); self.push(self.ip); self.csp, self.ip = s, o
            self._endext(); return
        if op == 0xCB:                                   # RET
            self.fetch8(); self.ip = self.pop(); self._endext(); return
        if op == 0xDB:                                   # RETS
            self.fetch8(); self.ip = self.pop(); self.csp = self.pop()
            self._endext(); return

        if op == 0xE6:                                   # MOV reg,#data16
            rr = self.fetch8(); d = self.fetch16()
            self.m.w16(self.reg_addr(rr, esfr), d)
            self.setzn(d); self._endext(); return
        if op == 0xF2:                                   # MOV reg,mem
            rr = self.fetch8(); a = self.fetch16()
            v = self.m.r16(self.mem_addr(a))
            self.m.w16(self.reg_addr(rr, esfr), v); self.setzn(v); self._endext(); return
        if op == 0xF6:                                   # MOV mem,reg
            rr = self.fetch8(); a = self.fetch16()
            v = self.m.r16(self.reg_addr(rr, esfr))
            self.m.w16(self.mem_addr(a), v)
            self.setzn(v); self._endext(); return
        if op == 0xE0:                                   # MOV Rw,#data4
            b = self.fetch8(); self.sr(b & 0x0F, b >> 4)
            self.setzn(b >> 4); self._endext(); return
        if op == 0xF0:                                   # MOV Rw,Rw
            b = self.fetch8(); v = self.gr(b & 0x0F)
            self.sr(b >> 4, v); self.setzn(v); self._endext(); return
        if op == 0x88:                                   # MOV [-Rw],Rw
            b = self.fetch8(); rw = b & 0x0F
            a = (self.gr(rw) - 2) & 0xFFFF; self.sr(rw, a)
            v = self.gr(b >> 4)
            self.m.w16(self.mem_addr(a), v); self.setzn(v)
            self._endext(); return
        if op in (0xE8, 0xE9):                           # MOV/MOVB [Rwn],[Rwm+]
            # MEMORY TO MEMORY, source post-incremented. This used to be
            # modelled as "MOV [Rw],#data3", an instruction the C166 does not
            # have: it wrote the register NUMBER to the address in Rwm and
            # never advanced, so a Keil struct copy (V94 hckline_init, the
            # first image to contain one) stamped 0x0006 over its target.
            # EVIDENCE: Keil C166 V7.53 listing of firmware/comms/hckline.c,
            #   04C2 E864   MOV [R6],[R4+]
            # - operand byte n:m, n (high nibble) the destination pointer,
            # m (low) the source, incremented by the operand size.
            b = self.fetch8(); n, m = b >> 4, b & 0x0F
            src = self.gr(m)
            if op == 0xE8:
                v = self.m.r16(self.mem_addr(src))
                self.m.w16(self.mem_addr(self.gr(n)), v)
                self.sr(m, (src + 2) & 0xFFFF)
                self.setzn(v)
            else:
                v = self.m.r8(self.mem_addr(src))
                self.m.w8(self.mem_addr(self.gr(n)), v)
                self.sr(m, (src + 1) & 0xFFFF)
                self.setznb(v)
            self._endext(); return
        if op in (0x84, 0x94, 0xA4, 0xB4):
            # MOV/MOVB [Rwn],mem (84/A4) and MOV/MOVB mem,[Rwn] (94/B4):
            # memory to memory, 4 bytes "op 0n MM MM" (n in the LOW nibble).
            # Unmodelled until V97: the first image with one (hcwb_pair_step
            # storing into a static) trapped here and the gates reported "no
            # valid envelope" - an instrument defect, not firmware.
            # EVIDENCE: Keil C166 V7.53 CODE listing of firmware/sensors/hcwb.c,
            #   0A10 94030000 R   MOV b_in,[R3]
            b = self.fetch8(); n = b & 0x0F; a = self.fetch16()
            if op in (0x84, 0xA4):
                src, dst = self.mem_addr(a), self.mem_addr(self.gr(n))
            else:
                src, dst = self.mem_addr(self.gr(n)), self.mem_addr(a)
            if op in (0x84, 0x94):
                v = self.m.r16(src); self.m.w16(dst, v); self.setzn(v)
            else:
                v = self.m.r8(src); self.m.w8(dst, v); self.setznb(v)
            self._endext(); return
        if op == 0xA8:                                   # MOV Rw,[Rw]
            b = self.fetch8()
            v = self.m.r16(self.mem_addr(self.gr(b & 0x0F)))
            self.sr(b >> 4, v); self.setzn(v); self._endext(); return
        if op == 0xB8:                                   # MOV [Rw],Rw
            b = self.fetch8(); v = self.gr(b >> 4)
            self.m.w16(self.mem_addr(self.gr(b & 0x0F)), v)
            self.setzn(v); self._endext(); return
        if op == 0x98:                                   # MOV Rw,[Rw+]
            b = self.fetch8(); rw = b & 0x0F; a = self.gr(rw)
            v = self.m.r16(self.mem_addr(a))
            self.sr(b >> 4, v)
            self.sr(rw, (a + 2) & 0xFFFF); self.setzn(v); self._endext(); return
        if op == 0xEC:                                   # PUSH
            rr = self.fetch8(); v = self.m.r16(self.reg_addr(rr, esfr))
            self.push(v); self.setzn(v); self._endext(); return
        if op == 0xFC:                                   # POP
            rr = self.fetch8(); v = self.pop()
            self.m.w16(self.reg_addr(rr, esfr), v)
            self.setzn(v); self._endext(); return

        # MUL / DIV via the MD register pair: MDL 0xFE0E, MDH 0xFE0C
        if op in (0x0B, 0x1B):                           # MUL / MULU Rw,Rw
            b = self.fetch8()
            x, y = self.gr(b >> 4), self.gr(b & 0x0F)
            if op == 0x0B:
                if x & 0x8000: x -= 0x10000
                if y & 0x8000: y -= 0x10000
            r = (x * y) & 0xFFFFFFFF
            self.m.w16(0xFE0E, r & 0xFFFF)
            self.m.w16(0xFE0C, (r >> 16) & 0xFFFF)
            self.setzn(r & 0xFFFF)
            self._endext(); return
        if op == 0x2B:                                   # PRIOR Rwn, Rwm
            # Normalisation helper: count how far the source has to shift left
            # before its MSB is set. Keil's ?C_ULDIV uses it to normalise the
            # divisor, so any 32/32 division reaches this - it appeared the
            # moment the rpm calculation started dividing by a 32-bit
            # revolution time.
            b = self.fetch8()
            src = self.gr(b & 0x0F)
            tmp, count = src, 0
            if src:
                while not (tmp & 0x8000) and count < 15:
                    tmp = (tmp << 1) & 0xFFFF
                    count += 1
            self.sr(b >> 4, count)
            # Z reports a zero SOURCE, not a zero result; N and C clear.
            self.z = 1 if src == 0 else 0
            self.n = 0
            self.c = 0
            self._endext(); return
        if op in (0x4B, 0x5B, 0x6B, 0x7B):               # DIV / DIVU / DIVL / DIVLU
            b = self.fetch8()
            d = self.gr(b & 0x0F)
            mdl = self.m.r16(0xFE0E)
            mdh = self.m.r16(0xFE0C)
            if op in (0x6B, 0x7B):
                num = (mdh << 16) | mdl
            else:
                num = mdl
            if op in (0x4B, 0x6B):                       # signed forms
                if d & 0x8000:
                    d -= 0x10000
                if op == 0x4B and (num & 0x8000):
                    num -= 0x10000
                elif op == 0x6B and (num & 0x80000000):
                    num -= 0x100000000
            if d == 0:
                raise Trap("divide by zero at %02X:%04X" % (self.csp, self.ip))
            q = int(num / d) if (num < 0) != (d < 0) else num // d
            r = num - q * d
            self.m.w16(0xFE0E, q & 0xFFFF)
            self.m.w16(0xFE0C, r & 0xFFFF)
            self.setzn(q & 0xFFFF)
            self._endext(); return

        if op in (0x91, 0x81):                           # CPL / NEG Rw
            b = self.fetch8(); rw = b >> 4; x = self.gr(rw)
            y = (~x) & 0xFFFF if op == 0x91 else (-x) & 0xFFFF
            if op == 0x81:
                # NEG IS A SUBTRACT FROM ZERO, so it produces a BORROW, and
                # Keil's 32-bit negate depends on it:
                #
                #     NEG   R10          ; C = borrow out of the low word
                #     ADDC  R11,#00H     ; ... which is carried into the high
                #     NEG   R11
                #
                # Take 0x00000001: NEG leaves 0xFFFF with a borrow, ADDC makes
                # the high word 1, NEG makes it 0xFFFF - and only then is the
                # answer 0xFFFFFFFF. Leaving C untouched here made every
                # negative 32-bit quantity come back wrong, which is to say all
                # of ?C_SLDIV, which is to say every `(long)gain * error / 100`
                # in the firmware. It cost a day chasing a PI controller that
                # was, on the real part, entirely correct.
                #
                # CPL is left alone deliberately: this convention is proved from
                # the sequence above, and there is no such proof for CPL.
                self.c = 1 if (x & 0xFFFF) else 0
            self.setzn(y); self.sr(rw, y); self._endext(); return
        if op in (0xB1, 0xA1):                           # CPLB / NEGB Rb
            b = self.fetch8(); a = self.cp() + (b >> 4); x = self.m.r8(a)
            y = (~x) & 0xFF if op == 0xB1 else (-x) & 0xFF
            if op == 0xA1:
                self.c = 1 if (x & 0xFF) else 0          # see NEG above
            self.z = 1 if y == 0 else 0
            self.m.w8(a, y); self._endext(); return
        if op in (0x86, 0x96, 0xA6, 0xB6):               # CMPI1/2 CMPD1/2 reg,#data16
            rr = self.fetch8(); d = self.fetch16()
            a = self.reg_addr(rr, esfr); x = self.m.r16(a)
            self.c = 1 if (x & 0xFFFF) < (d & 0xFFFF) else 0
            self.setzn(x - d)
            step = {0x86: 1, 0x96: 2, 0xA6: -1, 0xB6: -2}[op]
            self.m.w16(a, (x + step) & 0xFFFF); self._endext(); return
        if op in (0x80, 0x90, 0xA0, 0xB0):               # same, Rw,#data4
            # Operand layout here is #data4 in the HIGH nibble and Rwn in the
            # LOW nibble - the opposite of the ALU short forms (0x08/0x09),
            # which put the register high. Verified against the C166 listing
            # "0368 80F7  CMPI1 R7,#0FH". Getting this backwards made every
            # compiler for-loop run exactly one iteration.
            b = self.fetch8(); rw = b & 0x0F
            src = b >> 4
            x = self.gr(rw)
            self.c = 1 if (x & 0xFFFF) < (src & 0xFFFF) else 0
            self.setzn(x - src)
            step = {0x80: 1, 0x90: 2, 0xA0: -1, 0xB0: -2}[op]
            self.sr(rw, x + step); self._endext(); return

        # ---- byte forms -------------------------------------------------
        if op == 0xE1:                                   # MOVB Rb,#data4
            b = self.fetch8(); self.m.w8(self.cp() + (b & 0x0F), b >> 4)
            self.setznb(b >> 4); self._endext(); return
        if op == 0xF1:                                   # MOVB Rb,Rb
            b = self.fetch8(); v = self.m.r8(self.cp() + (b & 0x0F))
            self.m.w8(self.cp() + (b >> 4), v)
            self.setznb(v); self._endext(); return
        if op == 0xA9:                                   # MOVB Rb,[Rw]
            b = self.fetch8()
            v = self.m.r8(self.mem_addr(self.gr(b & 0x0F)))
            self.m.w8(self.cp() + (b >> 4), v); self.setznb(v); self._endext(); return
        if op == 0xB9:                                   # MOVB [Rw],Rb
            b = self.fetch8(); v = self.m.r8(self.cp() + (b >> 4))
            self.m.w8(self.mem_addr(self.gr(b & 0x0F)), v)
            self.setznb(v); self._endext(); return
        if op == 0x99:                                   # MOVB Rb,[Rw+]
            b = self.fetch8(); rw = b & 0x0F; a = self.gr(rw)
            v = self.m.r8(self.mem_addr(a))
            self.m.w8(self.cp() + (b >> 4), v)
            self.sr(rw, (a + 1) & 0xFFFF); self.setznb(v); self._endext(); return
        if op == 0xF3:                                   # MOVB reg,mem
            rr = self.fetch8(); a = self.fetch16()
            v = self.m.r8(self.mem_addr(a))
            self.m.w8(self.reg_addr_b(rr, esfr), v); self.setznb(v); self._endext(); return
        if op == 0xF7:                                   # MOVB mem,reg
            rr = self.fetch8(); a = self.fetch16()
            v = self.m.r8(self.reg_addr_b(rr, esfr))
            self.m.w8(self.mem_addr(a), v)
            self.setznb(v); self._endext(); return
        if op == 0xE7:                                   # MOVB reg,#data8
            rr = self.fetch8(); d = self.fetch16() & 0xFF
            self.m.w8(self.reg_addr_b(rr, esfr), d)
            self.setznb(d); self._endext(); return
        if op in (0xC4, 0xD4):                           # MOV [Rw+#d16],Rw / reverse
            b = self.fetch8(); d = self.fetch16()
            a = self.mem_addr((self.gr(b & 0x0F) + d) & 0xFFFF)
            if op == 0xC4:
                v = self.gr(b >> 4); self.m.w16(a, v)
            else:
                v = self.m.r16(a); self.sr(b >> 4, v)
            self.setzn(v); self._endext(); return
        if op in (0xE4, 0xF4):                           # MOVB [Rw+#d16],Rb / reverse
            b = self.fetch8(); d = self.fetch16()
            a = self.mem_addr((self.gr(b & 0x0F) + d) & 0xFFFF)
            if op == 0xE4:
                v = self.m.r8(self.cp() + (b >> 4)); self.m.w8(a, v)
            else:
                v = self.m.r8(a); self.m.w8(self.cp() + (b >> 4), v)
            self.setznb(v); self._endext(); return
        if op in (0xC2, 0xD2):                           # MOVBZ / MOVBS reg,mem
            # These are NOT indexed MOVB forms. Decoding them as such fed
            # garbage into every "unsigned char static -> word register" load
            # the compiler emits, e.g. MOVBZ R8,ts_plain_cmd, which silently
            # handed the wrong command byte to a switch.
            rr = self.fetch8(); a16 = self.fetch16()
            v = self.m.r8(self.mem_addr(a16))
            w = (v | 0xFF00) if (op == 0xD2 and (v & 0x80)) else v
            self.m.w16(self.reg_addr(rr, esfr), w & 0xFFFF)
            self.setzn(w); self._endext(); return
        if op in (0xC5, 0xD5):                           # MOVBZ / MOVBS mem,reg
            rr = self.fetch8(); a16 = self.fetch16()
            v = self.m.r8(self.reg_addr_b(rr, esfr))
            w = (v | 0xFF00) if (op == 0xD5 and (v & 0x80)) else v
            self.m.w16(self.mem_addr(a16), w & 0xFFFF)
            self.setzn(w); self._endext(); return
        if op in (0x03, 0x23, 0x43, 0x63, 0x73, 0x53):   # ALU byte reg,mem
            rr = self.fetch8(); a16 = self.fetch16()
            ra = self.reg_addr_b(rr, esfr); ma = self.mem_addr(a16)
            x = self.m.r8(ra); src = self.m.r8(ma)
            y = {0x03: x + src, 0x23: x - src, 0x43: x - src,
                 0x63: x & src, 0x73: x | src, 0x53: x ^ src}[op]
            if op in (0x23, 0x43):
                self.c = 1 if (x & 0xFF) < (src & 0xFF) else 0
            self.z = 1 if (y & 0xFF) == 0 else 0
            self.n = 1 if (y & 0x80) else 0
            if op != 0x43:
                self.m.w8(ra, y & 0xFF)
            self._endext(); return
        if op in (0x05, 0x25, 0x45, 0x65, 0x75, 0x55):   # ALU byte mem,reg
            rr = self.fetch8(); a16 = self.fetch16()
            ra = self.reg_addr_b(rr, esfr); ma = self.mem_addr(a16)
            x = self.m.r8(ma); src = self.m.r8(ra)
            y = {0x05: x + src, 0x25: x - src, 0x45: x - src,
                 0x65: x & src, 0x75: x | src, 0x55: x ^ src}[op]
            if op in (0x25, 0x45):
                self.c = 1 if (x & 0xFF) < (src & 0xFF) else 0
            self.z = 1 if (y & 0xFF) == 0 else 0
            self.n = 1 if (y & 0x80) else 0
            if op != 0x45:
                self.m.w8(ma, y & 0xFF)
            self._endext(); return
        if op in (0x07, 0x27, 0x47, 0x67, 0x77, 0x57):   # ALU byte reg,#data8
            rr = self.fetch8(); d = self.fetch16() & 0xFF
            a = self.reg_addr_b(rr, esfr); x = self.m.r8(a)
            y = {0x07: x + d, 0x27: x - d, 0x47: x - d,
                 0x67: x & d, 0x77: x | d, 0x57: x ^ d}[op]
            if op in (0x27, 0x47):
                self.c = 1 if (x & 0xFF) < (d & 0xFF) else 0
            self.z = 1 if (y & 0xFF) == 0 else 0
            self.n = 1 if (y & 0x80) else 0
            if op != 0x47:
                self.m.w8(a, y & 0xFF)
            self._endext(); return
        if op in (0x09, 0x29, 0x49, 0x69, 0x79, 0x59, 0x19, 0x39):  # ALU byte Rb,#data3|[Rwi]
            b = self.fetch8(); rb = b >> 4; lo = b & 0x0F
            src = self.m.r8(self.mem_addr(self.gr(lo & 3))) if (lo & 8) else (lo & 7)
            a = self.cp() + rb; x = self.m.r8(a)
            y = {0x09: x + src, 0x19: x + src, 0x29: x - src, 0x39: x - src,
                 0x49: x - src, 0x69: x & src, 0x79: x | src, 0x59: x ^ src}[op]
            if op in (0x29, 0x39, 0x49):
                self.c = 1 if (x & 0xFF) < (src & 0xFF) else 0
            self.z = 1 if (y & 0xFF) == 0 else 0
            self.n = 1 if (y & 0x80) else 0
            if op != 0x49:
                self.m.w8(a, y & 0xFF)
            self._endext(); return
        if op in (0x01, 0x21, 0x41, 0x61, 0x71, 0x51, 0x11, 0x31):  # ALU byte Rb,Rb
            b = self.fetch8()
            a = self.cp() + (b >> 4); x = self.m.r8(a); src = self.m.r8(self.cp() + (b & 0x0F))
            y = {0x01: x + src, 0x11: x + src, 0x21: x - src, 0x31: x - src,
                 0x41: x - src, 0x61: x & src, 0x71: x | src, 0x51: x ^ src}[op]
            if op in (0x21, 0x31, 0x41):
                self.c = 1 if (x & 0xFF) < (src & 0xFF) else 0
            self.z = 1 if (y & 0xFF) == 0 else 0
            self.n = 1 if (y & 0x80) else 0
            if op != 0x41:
                self.m.w8(a, y & 0xFF)
            self._endext(); return
        if op in (0xC0, 0xC1, 0xD0, 0xD1 - 0xD1):        # MOVBZ / MOVBS
            pass
        if op in (0xC0, 0xD0):                           # MOVBZ / MOVBS Rw,Rb
            # operand order is (word reg = LOW nibble, byte reg = HIGH nibble).
            # Verified against "C0 85 ; SHL R5,#8" which the compiler emits for
            # ((unsigned int)hi << 8) - it must load R5, not R8.
            b = self.fetch8()
            v = self.m.r8(self.cp() + (b >> 4))
            if op == 0xD0 and (v & 0x80):
                v |= 0xFF00
            self.sr(b & 0x0F, v); self._endext(); return
        # Shift and rotate. The C166 lays these out as PAIRS: the even opcode
        # takes its count from a REGISTER, the next one from a #data4 nibble.
        #     0C/1C ROL   2C/3C ROR   4C/5C SHL   6C/7C SHR   AC/BC ASHR
        # Treating 4C and 6C as immediate forms meant they fell through to
        # "no shift at all", so every normalisation step silently did nothing
        # and Keil's ?C_ULDIV returned garbage for any divisor above 16 bits -
        # which is exactly a crank revolution measured in timer ticks.
        if op in (0x0C, 0x1C, 0x2C, 0x3C, 0x4C, 0x5C,
                  0x6C, 0x7C, 0xAC, 0xBC):
            b = self.fetch8()
            if op & 0x10:                                # #data4 form
                rw, cnt = b & 0x0F, b >> 4
            else:                                        # register form
                rw, cnt = b >> 4, self.gr(b & 0x0F) & 0x0F
            x = self.gr(rw)
            kind = op & 0xEF                             # pair -> operation
            carry = 0
            if kind == 0x4C:                             # SHL
                if cnt:
                    carry = (x >> (16 - cnt)) & 1
                y = (x << cnt) & 0xFFFF
            elif kind == 0x6C:                           # SHR
                if cnt:
                    carry = (x >> (cnt - 1)) & 1
                y = (x >> cnt) & 0xFFFF
            elif kind == 0xAC:                           # ASHR, sign preserved
                if cnt:
                    carry = (x >> (cnt - 1)) & 1
                sx = x - 0x10000 if (x & 0x8000) else x
                y = (sx >> cnt) & 0xFFFF
            elif kind == 0x0C:                           # ROL
                cnt &= 0x0F
                y = ((x << cnt) | (x >> (16 - cnt))) & 0xFFFF if cnt else x
                carry = y & 1 if cnt else 0
            else:                                        # 0x2C ROR
                cnt &= 0x0F
                y = ((x >> cnt) | (x << (16 - cnt))) & 0xFFFF if cnt else x
                carry = (y >> 15) & 1 if cnt else 0
            self.setzn(y)
            self.c = carry
            self.sr(rw, y)
            self._endext(); return
        # bit-to-bit ops: op QQ ZZ (q<<4)|z   -- Q is the source bit, Z the dest.
        # The C166 compiler uses BMOV to carry bit 0 across a 32-bit right shift,
        # so crc32() does not work without these.
        if op in (0x2A, 0x3A, 0x4A, 0x5A, 0x6A, 0x7A):
            boq = self.fetch8(); boz = self.fetch8(); qz = self.fetch8()
            q = qz >> 4
            z = qz & 0x0F
            aq, _ = self.bitaddr(boq, q)
            az, _ = self.bitaddr(boz, z)
            sq = (self.m.r16(aq) >> q) & 1
            sz = (self.m.r16(az) >> z) & 1
            if op == 0x4A:      res = sq              # BMOV
            elif op == 0x3A:    res = sq ^ 1          # BMOVN
            elif op == 0x2A:    res = sz & sq         # BAND
            elif op == 0x6A:    res = sz | sq         # BOR
            elif op == 0x5A:    res = sz ^ sq         # BXOR
            else:                                     # BCMP: flags only
                self.z = 1 if sz == sq else 0
                self._endext(); return
            w = self.m.r16(az)
            w = (w | (1 << z)) if res else (w & ~(1 << z))
            self.m.w16(az, w)
            if az == self.PSW_ADDR:
                self.psw_extract()
            self.z = 1 if res == 0 else 0
            self._endext(); return

        if op in (0x0A, 0x1A):                           # BFLDL / BFLDH
            # The two encodings order their immediates differently:
            # BFLDL op1,#mask,#data = 0A QQ mask data, but
            # BFLDH op1,#mask,#data = 1A QQ data mask (Keil C166 V7.53:
            # _bfld_(P2,0xF0,0x30) -> 0AE0F030, _bfld_(P2,0x0F00,0x0500)
            # -> 1AE0050F). Until 2026-10-08 BFLDH was read as mask, data:
            # the ILVL-13 critical section entered from ILVL 11 ran at 15.
            rr = self.fetch8(); mask = self.fetch8(); data = self.fetch8()
            if op == 0x1A:
                mask, data = data, mask
            a = self.reg_addr(rr, esfr); w = self.m.r16(a)
            if op == 0x0A:
                w = (w & ~mask) | (data & mask)
            else:
                w = (w & ~(mask << 8)) | ((data << 8) & (mask << 8))
            self.m.w16(a, w & 0xFFFF); self._endext(); return
        if op == 0xCA:                                   # CALLA cc,addr
            cc = self.fetch8() >> 4; a = self.fetch16()
            if self.cond(cc):
                self.push(self.ip); self.ip = a
            self._endext(); return

        # ALU with a memory operand: x2 = reg <- op(reg, mem), x4 = mem <- op(mem, reg)
        if op in (0x02, 0x12, 0x22, 0x32, 0x42, 0x52, 0x62, 0x72,
                  0x04, 0x14, 0x24, 0x34, 0x44, 0x54, 0x64, 0x74):
            rr = self.fetch8(); a16 = self.fetch16()
            ma = self.mem_addr(a16); ra = self.reg_addr(rr, esfr)
            to_mem = (op & 0x0F) == 0x04
            dst, src = (ma, ra) if to_mem else (ra, ma)
            x = self.m.r16(dst); y = self.m.r16(src)
            base = op & 0xF0
            res = self.alu16(base, x, y)
            if base != 0x40:
                self.m.w16(dst, res & 0xFFFF)
            self._endext(); return

        if op in (0x06, 0x16, 0x26, 0x36, 0x46, 0x66, 0x76, 0x56):  # ALU reg,#data16
            rr = self.fetch8(); d = self.fetch16()
            a = self.reg_addr(rr, esfr); x = self.m.r16(a)
            y = self.alu16(op & 0xF0, x, d)
            if op != 0x46:
                self.m.w16(a, y & 0xFFFF)
            self._endext(); return

        if op in (0x08, 0x18, 0x28, 0x38, 0x48, 0x68, 0x78, 0x58):  # ALU Rw,#data3|[Rwi]
            b = self.fetch8(); rw = b >> 4; lo = b & 0x0F
            src = self.m.r16(self.mem_addr(self.gr(lo & 3))) if (lo & 8) else (lo & 7)
            x = self.gr(rw)
            y = self.alu16(op & 0xF0, x, src)
            if op != 0x48:
                self.sr(rw, y)
            self._endext(); return

        if op in (0x00, 0x10, 0x20, 0x30, 0x40, 0x60, 0x70, 0x50):  # ALU Rw,Rw
            b = self.fetch8(); x = self.gr(b >> 4); src = self.gr(b & 0x0F)
            y = self.alu16(op & 0xF0, x, src)
            if op != 0x40:
                self.sr(b >> 4, y)
            self._endext(); return

        raise Trap("UNIMPLEMENTED opcode 0x%02X at %02X:%04X"
                   % (op, self.csp, (self.ip - 1) & 0xFFFF))


def run(path, seg, off, steps, trace_n=0):
    m = Mem(open(path, "rb").read())
    cpu = CPU(m, seg, off)
    hist = []
    try:
        while cpu.steps < steps:
            hist.append((cpu.csp, cpu.ip))
            if trace_n and cpu.steps < trace_n:
                print("  %02X:%04X  SP=%04X CP=%04X R0=%04X R1=%04X"
                      % (cpu.csp, cpu.ip, m.sfr.get(0xFE12, 0), m.sfr.get(0xFE10, 0),
                         cpu.gr(0), cpu.gr(1)))
            cpu.step()
    except Trap as e:
        print("\nTRAP after %d steps, PC now %02X:%04X" % (cpu.steps, cpu.csp, cpu.ip))
        print("  %s" % e)
        print("  last 12 PCs: " + " ".join("%02X:%04X" % p for p in hist[-12:]))
        return cpu, str(e)
    print("\nran %d steps, NO TRAP (SRVWDT x%d), final PC %02X:%04X"
          % (cpu.steps, cpu.srvwdt, cpu.csp, cpu.ip))
    return cpu, None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(0)
    s, o = (int(x, 16) for x in sys.argv[2].split(":"))
    n = int(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 200000
    t = int(sys.argv[sys.argv.index("--trace") + 1]) if "--trace" in sys.argv else 0
    run(sys.argv[1], s, o, n, t)
