#!/usr/bin/env python3
r"""
me711_rebin_ve_load_axis.py - move a VE table onto a DIFFERENT load axis
without inventing a tune. Read-only unless --out is given; never touches an
ECU.

    py tools\calibration\me711_rebin_ve_load_axis.py --page <page.bin> \
        --ini tunerstudio\history\hanicore_me711_v99_dev.ini \
        [--axis 0,10,20,30,40,55,70,100,130,160,200,250,300,400,500,1000] \
        [--out <dir>]

WHY THIS EXISTS.

The AWT ran about 2x rich at idle for the whole car session and fouled all
four plugs. The fuel model itself is right: with `loadSource` alpha-N the VE
table IS the load model, and `airMass = veValue x 5.352` is one cylinder's
displacement charge at standard density, confirmed to four figures in every
row of every session. What was wrong is the AXIS the table is read on.

The Burned car page carries a VE Table Generator axis running 15..160 %
throttle. Measured idle throttle is 3.5..5.4 %, i.e. BELOW the lowest row, so
every idle and light-load sample clamps to row 0 and `veValue` sits at 50.0 %
- the ECU computes half of a full displacement charge where the engine takes
roughly 23 % of it. The top five rows (120..200 %) are unreachable, because
on a throttle axis there is no such thing as 120 % throttle.

So the axis is re-binned to one that spans what the engine actually does, and
the EXISTING VE SURFACE IS CARRIED ONTO IT BY INTERPOLATION - this tool does
not invent a VE number anywhere. Each rpm column is resampled independently:

  * a new load bin inside the old axis    -> linear interpolation between the
                                             two old rows that bracket it;
  * a new bin below the old axis's first  -> the old first row, HELD, and
                                             reported, because nothing was
                                             ever measured down there (the old
                                             axis started above idle: that is
                                             the whole defect);
  * a new bin above the old axis's last   -> the old last row, held.

Held cells are listed in the report. They are where a real idle VE has to be
measured on the car once lambda publishes - which is the other half of the
same finding (B3: closed loop never engaged, so nothing could correct this).

The default axis is the one the AWT PRESET already carries
(tools/config_source/hanicore_presets.py, "dense below 10 % where idle and
part load live"): 0, 1, 2, 3, 4, 5.5, 7, 10, 13, 16, 20, 25, 30, 40, 50,
100 %. It is not a new invention either.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_migrate_calibration as M

# the AWT preset's own axis, in 0.1 % throttle
PRESET_AXIS = [0, 10, 20, 30, 40, 55, 70, 100, 130, 160,
               200, 250, 300, 400, 500, 1000]


def read_field(page, c, name, i=0):
    k = c[name]
    return M._get(page, k.off + i * k.width, k.width, M.TYPES[k.typ][1])


def write_field(page, c, name, i, v):
    k = c[name]
    M._put(page, k.off + i * k.width, k.width, v)


def interp_row(load, old_ax, col):
    """One rpm column at one new load bin. -> (value, 'held'|'interp')"""
    if load <= old_ax[0]:
        return col[0], "held-low"
    if load >= old_ax[-1]:
        return col[-1], "held-high"
    for j in range(1, len(old_ax)):
        if load <= old_ax[j]:
            lo, hi = old_ax[j - 1], old_ax[j]
            if hi == lo:
                return col[j], "interp"
            f = (load - lo) / float(hi - lo)
            return int(round(col[j - 1] + (col[j] - col[j - 1]) * f)), "interp"
    return col[-1], "held-high"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True, help="the 4096-byte page")
    ap.add_argument("--ini", required=True)
    ap.add_argument("--axis", default=None,
                    help="16 new load bins in 0.1 %% (default: the AWT preset's)")
    ap.add_argument("--out", default=None, help="write the migrated page here")
    a = ap.parse_args()

    page = bytearray(Path(a.page).read_bytes())
    c = M.parse_ini(Path(a.ini).read_text(encoding="utf-8", errors="replace"))
    for need in ("veTable", "fuelLoadAx", "fuelRpmAx", "loadSource"):
        if need not in c:
            print("FAIL: %s is not in that .ini" % need)
            return 1

    n = 16
    ve = c["veTable"]
    nrow = ve.count // n
    if nrow != n:
        print("FAIL: veTable is %d cells, not %dx%d" % (ve.count, n, n))
        return 1

    ls = c["loadSource"]
    lo_b, hi_b = ls.bits
    src = (read_field(page, c, "loadSource") >> lo_b) & ((1 << (hi_b - lo_b + 1)) - 1)

    old_ax = [read_field(page, c, "fuelLoadAx", i) for i in range(n)]
    rpm_ax = [read_field(page, c, "fuelRpmAx", i) for i in range(n)]
    old = [[read_field(page, c, "veTable", r * n + k) for k in range(n)]
           for r in range(nrow)]
    new_ax = ([int(x) for x in a.axis.split(",")] if a.axis else list(PRESET_AXIS))
    if len(new_ax) != n:
        print("FAIL: --axis needs exactly %d bins" % n)
        return 1

    sc_ax = c["fuelLoadAx"].scale
    sc_ve = ve.scale

    print("load source       : %d (%s)" % (src, ls.labels[src]))
    print("rpm axis          : %s" % ", ".join(str(v) for v in rpm_ax))
    print()
    print("OLD load axis (%%): %s" % ", ".join("%.1f" % (v * sc_ax) for v in old_ax))
    print("NEW load axis (%%): %s" % ", ".join("%.1f" % (v * sc_ax) for v in new_ax))
    dead = [round(v * sc_ax, 1) for v in old_ax if v * sc_ax > 100.0]
    if dead and src in (1, 2):
        print("  dropped as unreachable on a THROTTLE axis: %s" % dead)
    if old_ax[0] * sc_ax > 6.0:
        print("  old axis started at %.1f %%, above the measured idle "
              "throttle of 3.5..5.4 %%" % (old_ax[0] * sc_ax))

    # resample each rpm column independently
    new = [[0] * n for _ in range(nrow)]
    held = []
    for k in range(n):                      # rpm column
        col = [old[r][k] for r in range(nrow)]
        for r in range(nrow):               # new load row
            v, how = interp_row(new_ax[r], old_ax, col)
            new[r][k] = v
            if how != "interp":
                held.append((r, k, how))

    def show(title, ax, tab):
        print()
        print(title)
        print("      load%% |" + "".join("%6d" % v for v in rpm_ax))
        for r in range(nrow):
            print("    %7.1f |" % (ax[r] * sc_ax)
                  + "".join("%6.1f" % (tab[r][k] * sc_ve) for k in range(n)))

    show("OLD VE table (%, [load][rpm]):", old_ax, old)
    show("NEW VE table (%, [load][rpm]) - interpolated, nothing invented:",
         new_ax, new)

    print()
    nlow = sum(1 for _, _, h in held if h == "held-low")
    nhigh = sum(1 for _, _, h in held if h == "held-high")
    print("cells carried by interpolation : %d" % (nrow * n - len(held)))
    print("cells HELD from the old row 0  : %d  (new bins below the old axis -"
          " measure these on the car)" % nlow)
    print("cells HELD from the old last   : %d" % nhigh)
    rows_low = sorted({r for r, _, h in held if h == "held-low"})
    if rows_low:
        print("  rows held low: %s"
              % ", ".join("%.1f %%" % (new_ax[r] * sc_ax) for r in rows_low))

    if a.out:
        for i, v in enumerate(new_ax):
            write_field(page, c, "fuelLoadAx", i, v)
        for r in range(nrow):
            for k in range(n):
                write_field(page, c, "veTable", r * n + k, new[r][k])
        d = Path(a.out)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "page_rebinned.bin"
        p.write_bytes(bytes(page))
        print()
        print("wrote %s (%d bytes)" % (p, len(page)))
        print("NOT BURNED, NOT FLASHED - review it, then restore it "
              "deliberately.")
    else:
        print()
        print("read-only: pass --out <dir> to write the migrated page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
