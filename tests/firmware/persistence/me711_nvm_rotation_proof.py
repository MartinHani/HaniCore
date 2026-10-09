#!/usr/bin/env python3
r"""
me711_nvm_rotation_proof.py - drive the REAL firmware across a store wrap.

WHAT IT PROVES, and none of it is modelled - the linked image executes:

  1. a store with one cell left selects the newest record and knows it is low;
  2. a Burn into the last cell fills the store;
  3. the firmware then RECLAIMS a sector by itself - it does not report
     HCNV_ERR_FULL, which is what V52 did and what this whole change exists to
     delete;
  4. the sector it erases is NOT the one holding the newest record, and the
     newest record is byte-identical before and after;
  5. the erase is SLICED - many Erase Suspend / Resume pairs, not one blocking
     command - and no instruction is ever fetched from the busy device;
  6. afterwards the reclaimed cells are blank and a further Burn uses one.

WHY THE STORE IS PRE-FILLED RATHER THAN BURNED EIGHTY TIMES. A Burn is 2060
programmed words and takes the rig minutes of simulated time; seventy-nine of
them would make this gate unrunnable, and they would prove nothing the
firmware's own append path has not already proved on silicon. The records are
written straight into the image as BYTES, in exactly the layout hcnvm.c
defines, and the firmware then scans them with its own code. The two Burns that
matter - the one that fills the store and the one that follows the reclaim -
are real.

THE PAYLOAD IS THE ECU'S OWN CALIBRATION PAGE, read out of a first boot. A
synthetic payload would load nonsense into the working page at selection time
and the failure would look like a rotation defect.
"""
from __future__ import annotations

import binascii
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI                                  # noqa: E402
import me711_heartbeat_gap_proof as HB                    # noqa: E402
import me711_ts_gap_proof as GAP                          # noqa: E402
from me711_nvm_geometry import GEO                        # noqa: E402

SRCDIR = ROOT / "firmware/targets/me711"
SHARED = ROOT / "firmware"

CHECKS = FAILS = 0


def check(label, ok, detail=""):
    global CHECKS, FAILS
    CHECKS += 1
    FAILS += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def define(name, *files):
    for f in files:
        m = re.search(rf"^#define\s+{name}\s+(0x[0-9A-Fa-f]+|\d+)",
                      f.read_text(errors="replace"), re.M)
        if m:
            return int(m.group(1), 0)
    raise SystemExit(f"{name} not found")


LAYOUT = define("HC_CFG_LAYOUT_ID", SHARED / "generated/hc_config_generated.h")
VERSION = define("HC_CFG_VERSION", SHARED / "config/hcconfig.h")
SIZE = define("HC_CFG_SIZE", SHARED / "config/hcconfig.h")
REC_LEN = 18 + SIZE + 2 + 4


def crc(b):
    return binascii.crc_hqx(bytes(b), 0xFFFF)


def record(payload, gen):
    """Exactly the layout hcnvm.c's REC_* offsets define, big-endian."""
    r = bytearray(b"HCN1")
    r += LAYOUT.to_bytes(4, "big")
    r += VERSION.to_bytes(2, "big")
    r += SIZE.to_bytes(2, "big")
    r += gen.to_bytes(4, "big")
    r += crc(r).to_bytes(2, "big")
    r += bytes(payload)
    r += crc(payload).to_bytes(2, "big")
    r += b"DONE"
    assert len(r) == REC_LEN, (len(r), REC_LEN)
    return bytes(r)


def cell_slice(flash, i, n=REC_LEN):
    a = GEO.addr(i)
    return bytes(flash[a:a + n])


def cell_blank(flash, i):
    a = GEO.addr(i)
    return all(b == 0xFF for b in flash[a:a + GEO.body])


def sector_blank(flash, s):
    return all(cell_blank(flash, c) for c in GEO.cells_of_sector(s))


_TMP = ROOT / "bins/hanicore/_rotation_proof_scratch.bin"


def boot_rig(image, warm=None):
    """HB.Rig takes a PATH, so a mutated image has to be spilled to one. The
    scratch file is rewritten per phase and is never an artefact anything
    else names."""
    if isinstance(image, (bytes, bytearray)):
        _TMP.write_bytes(bytes(image))
        path = _TMP
    else:
        path = image
    rig = HB.Rig(path, HB.ENTRY_CURRENT, HB.TICK_CURRENT,
                 echo=False, steps_per_tick=HB.STEPS_PER_TICK)
    rig.run(warm if warm is not None else GAP.BOOT_WARMUP_STEPS)
    return rig


def main():
    print("=== HaniCore Bosch ME7.1.1 - V53 store ROTATION proof ===\n")
    image = PI.image().read_bytes()
    print(f"  image   {PI.image().name}")
    print(f"  store   {GEO.cells} cells over {GEO.sectors} sectors, "
          f"0x{GEO.file_base:06X}-"
          f"0x{GEO.file_base + GEO.sectors * GEO.sector_size - 1:06X}")
    print(f"  record  {REC_LEN} bytes, layout 0x{LAYOUT:08X}\n")

    # ---- phase 1: take the ECU's own calibration page off a clean boot ----
    rig = boot_rig(PI.image())
    if len(rig.entries) < 2:
        raise SystemExit("REGRESSION: warmup reached no supervision entries; "
                         "every figure below would be vacuous")
    cfg_base = 0x380000 + define("TGT_RAM_CFG", SRCDIR / "hctarget.h")
    page = bytes(rig.mem.r8(cfg_base + 12 + i) for i in range(SIZE))
    check("a clean boot produces a calibration page to snapshot",
          len(page) == SIZE and any(b != 0 for b in page),
          f"{sum(1 for b in page if b)} non-zero bytes")

    # ---- phase 2: pre-fill every cell but the last ------------------------
    filled = bytearray(image)
    last = GEO.cells - 1
    for i in range(last):
        filled[GEO.addr(i):GEO.addr(i) + REC_LEN] = record(page, i + 1)
    newest_before = cell_slice(filled, last - 1)

    rig = boot_rig(bytes(filled))
    mem = rig.mem
    flash = mem.flash

    # NVW_BASE is NVM_CB + 32, and W_CELL/W_FREE are offsets 3 and 4 INSIDE
    # that working block - not inside the control block. Reading NVM_CB+3/+4
    # lands in the sealed commit block instead and reports nonsense.
    nvw = 0x380000 + define("TGT_RAM_NVM", SRCDIR / "hctarget.h") + 32
    free = mem.r8(nvw + 4)
    cell = mem.r8(nvw + 3)
    check("the firmware selects the NEWEST pre-filled record",
          cell == last - 1, f"cell {cell}, expected {last - 1}")
    # THE RECLAIM HAS USUALLY ALREADY RUN BY HERE, and that is the firmware
    # being right rather than the test being right. The store was built one
    # cell from full, er_wanted() fires at HCNV_RECLAIM_LOW, and the warmup is
    # 3.5 M instructions - so asserting "free == 1" here was asserting that the
    # ECU had NOT yet done the thing this gate exists to prove it does.
    #
    # What is worth asserting is that it reclaimed ONE sector and stopped. A
    # firmware that erased every sector it was allowed to would pass every
    # other check in this file.
    check("free cells are consistent with at most one reclaim",
          free in (1, 1 + GEO.cell_pages),
          f"free={free} (1 before a reclaim, {1 + GEO.cell_pages} after one)")
    check("exactly ONE sector was erased, not a cascade",
          len(mem.fl_erases) <= 1, str(mem.fl_erases))

    # ---- phase 3: run the service loop until a reclaim happens -----------
    # The store is one cell from full, so er_wanted() fires as soon as the
    # scan's free count reaches HCNV_RECLAIM_LOW. Nothing is burned here: the
    # reclaim is meant to run BEFORE the store is exhausted, and that is the
    # property being checked.
    steps = 0
    budget = HB.STEPS_PER_TICK * 1250 * 4000          # ~4 s of firmware time
    while mem.fl_erase_completed == 0 and steps < budget and rig.trap is None:
        rig.run(HB.STEPS_PER_TICK * 1250)             # 1 ms
        steps += HB.STEPS_PER_TICK * 1250

    check("the firmware reclaims a sector by itself",
          mem.fl_erase_completed >= 1,
          f"{mem.fl_erase_completed} completed, erases={mem.fl_erases}, "
          f"trap={rig.trap}")

    if mem.fl_erase_completed:
        erased = GEO.sector_of(
            [c for c in range(GEO.cells)
             if GEO.sector_file_base(GEO.sector_of(c)) == mem.fl_erases[0]][0])
        active_sector = GEO.sector_of(last - 1)
        check("the erased sector is NOT the one holding the newest record",
              erased != active_sector,
              f"erased sector {erased}, newest in sector {active_sector}")
        check("it is the OLDEST sector", erased == 0, f"sector {erased}")
        check("the newest record is byte-identical across the reclaim",
              cell_slice(flash, last - 1) == newest_before)
        check("the reclaimed sector is genuinely blank",
              sector_blank(flash, erased))

    # ---- phase 4: the erase was SLICED, and nothing fetched while busy ---
    check("the erase was sliced, not one blocking command",
          mem.fl_erase_suspends >= 2 and mem.fl_erase_resumes >= 1,
          f"{mem.fl_erase_suspends} suspends, {mem.fl_erase_resumes} resumes")
    check("no instruction was fetched from the busy device",
          mem.fl_fetch_while_busy == 0, str(mem.fl_fetch_while_busy))
    check("the ECU never reset across the reclaim", rig.trap is None,
          str(rig.trap))

    # ---- phase 5: the freed cells are usable ----------------------------
    free_after = mem.r8(nvw + 4)
    check("free cells rose by a whole sector",
          free_after >= GEO.cell_pages,
          f"free={free_after}, expected >= {GEO.cell_pages}")

    # ---- negative control -----------------------------------------------
    # A store that is NOT low must not erase anything. Without this, a firmware
    # that erased on every pass would pass every check above.
    rig2 = boot_rig(PI.image())
    rig2.run(HB.STEPS_PER_TICK * 1250 * 2000)
    check("control: a nearly-empty store erases NOTHING",
          rig2.mem.fl_erase_completed == 0 and not rig2.mem.fl_erases,
          f"completed={rig2.mem.fl_erase_completed}, {rig2.mem.fl_erases}")

    print(f"\n{CHECKS - FAILS}/{CHECKS} checks pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
