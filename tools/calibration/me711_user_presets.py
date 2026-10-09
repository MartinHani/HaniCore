#!/usr/bin/env python3
r"""
me711_user_presets.py - save, list, apply and delete USER presets.

    py tools\calibration\me711_user_presets.py list
    py tools\calibration\me711_user_presets.py save "My AWT" --from-ecu [--port COM3]
    py tools\calibration\me711_user_presets.py save "My AWT" --from-dump readback.bin
    py tools\calibration\me711_user_presets.py show "My AWT"
    py tools\calibration\me711_user_presets.py apply "My AWT" [--port COM3] [--dry-run]
    py tools\calibration\me711_user_presets.py delete "My AWT" --yes

Built-in presets are compiled into the firmware (Controller > Base Tunes in
TunerStudio, applied with APPLY ENGINE PRESET). They are listed here as
BUILT-IN and can be neither replaced nor deleted.

A user preset is a snapshot of a whole calibration page, kept on this PC in
the user preset library: %HANICORE_USER_PRESETS%, default
~/.hanicore/user_presets/, one JSON file per preset. It records the page
layout id; a preset is applied only to firmware with the same layout.

Applying needs the engine stopped. It writes only the bytes that differ,
with TunerStudio's own page writes, then reads the page back and reports
whether the ECU accepts the result as a runnable setup. If the ECU refuses a
write part-way, every byte already written is put back. It never Burns:
check the result in TunerStudio and Burn there, as with a built-in preset.
Per-unit measurements (throttle and pedal endpoints, the throttle bias curve)
are skipped unless --include-measured is given: they belong to one throttle
body and one pedal.

Why on the PC and not in the ECU: the calibration store holds the working
page only, and TunerStudio's own tune files (.msq) already keep any number of
whole tunes. This library adds what a tune file does not: the page layout
check, the built-in names kept apart, and the per-unit measurements left
alone.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "lib"))
import hcpaths as HCP  # noqa: E402

PAGE = 4096
FORMAT = "hanicore-user-preset/1"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,39}$")
# The configuration manager stages every written byte with a bounded undo log
# (2560 bytes: 1 per byte + 5 per run). Stay well inside it.
MAX_STAGE_BYTES = 1800
CHUNK = 16                          # bytes per 'W', as the restore tool writes
MEASURED = ("CAL_TPS1_MIN", "CAL_TPS1_MAX", "CAL_TPS2_MIN", "CAL_TPS2_MAX",
            "CAL_PEDAL1_MIN", "CAL_PEDAL1_MAX", "CAL_PEDAL2_MIN",
            "CAL_PEDAL2_MAX", "CAL_DBW_BIAS_AX", "CAL_DBW_BIAS_VAL")


class PresetError(Exception):
    """A refused operation; the message says why."""


def library_dir() -> Path:
    return Path(os.environ.get("HANICORE_USER_PRESETS",
                               str(Path.home() / ".hanicore" / "user_presets")))


def builtin_names() -> dict[str, str]:
    """Lower-cased display names and keys of the compiled engine presets."""
    import hanicore_presets as HP
    out = {}
    for p in HP.ENGINE_PRESETS:
        out[p.name.lower()] = p.name
        out[p.key.lower()] = p.name
    return out


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def check_name(name: str, builtins: dict[str, str]) -> None:
    if name != name.strip() or not NAME_RE.match(name):
        raise PresetError(
            "invalid name %r: 1-40 characters, starting with a letter or "
            "digit; letters, digits, space and . _ ( ) + - only" % name)
    if name.lower() in builtins or slug(name) in {slug(b) for b in builtins}:
        raise PresetError("%r is the name of the built-in preset %r; choose "
                          "another name" % (name, builtins.get(name.lower(),
                                                               name)))


def layout_id() -> str:
    h = (HCP.ROOT / "firmware/generated/hc_config_generated.h").read_text()
    return "%08X" % int(re.search(r"#define\s+HC_CFG_LAYOUT_ID\s+0x([0-9A-Fa-f]+)",
                                  h).group(1), 16)


def field_span(name: str) -> tuple[int, int]:
    """(offset, bytes) of a page field, from the generated config model."""
    import csv
    path = HCP.ROOT / "build/generated/hc_config_model.csv"
    if path.exists():
        for r in csv.DictReader(path.open()):
            if r["slot"] == name:
                return int(r["offset"]), int(r["bytes"])
    h = (HCP.ROOT / "firmware/generated/hc_config_generated.h").read_text()
    m = re.search(r"#define\s+%s\s+(\d+)u?\b" % re.escape(name), h)
    if not m:
        raise PresetError("unknown page field %s" % name)
    return int(m.group(1)), 2


class Library:
    def __init__(self, root: Path | None = None, builtins=None):
        self.root = Path(root) if root else library_dir()
        self.builtins = builtin_names() if builtins is None else builtins

    def _path(self, name: str) -> Path:
        return self.root / (slug(name) + ".json")

    def user(self) -> list[dict]:
        out = []
        if self.root.is_dir():
            for f in sorted(self.root.glob("*.json")):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if d.get("format") == FORMAT:
                    out.append(d)
        return out

    def find(self, name: str) -> dict:
        for d in self.user():
            if d["name"].lower() == name.lower():
                return d
        if name.lower() in self.builtins:
            raise PresetError("%r is a built-in preset: apply it in TunerStudio "
                              "(Base Tunes > APPLY ENGINE PRESET)" % name)
        raise PresetError("no user preset named %r (see 'list')" % name)

    @staticmethod
    def page(d: dict) -> bytes:
        page = bytes.fromhex(d["page"])
        if len(page) != PAGE or hashlib.sha256(page).hexdigest() != d["sha256"]:
            raise PresetError("user preset %r is damaged (page length or "
                              "checksum); delete it and save it again" % d["name"])
        return page

    def save(self, name: str, page: bytes, layout: str, source: str,
             note: str = "", replace: bool = False, signature: str = "") -> Path:
        check_name(name, self.builtins)
        if len(page) != PAGE:
            raise PresetError("a page is %d bytes, got %d" % (PAGE, len(page)))
        clash = [d for d in self.user() if slug(d["name"]) == slug(name)]
        if clash and not replace:
            raise PresetError("a user preset %r already exists; pass --replace "
                              "to overwrite it" % clash[0]["name"])
        rec = {"format": FORMAT, "name": name, "layout_id": layout,
               "signature": signature, "source": source, "note": note,
               "created_utc": dt.datetime.now(dt.timezone.utc)
               .strftime("%Y-%m-%dT%H:%M:%SZ"),
               "sha256": hashlib.sha256(page).hexdigest(), "page": page.hex()}
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        os.replace(tmp, path)           # never a half-written preset
        return path

    def delete(self, name: str) -> Path:
        if name.lower() in self.builtins:
            raise PresetError("%r is a built-in preset and cannot be deleted"
                              % name)
        d = self.find(name)
        path = self._path(d["name"])
        if not path.exists() or path.parent.resolve() != self.root.resolve():
            raise PresetError("the file for %r is not in the library" % name)
        path.unlink()
        return path


def plan_apply(current: bytes, want: bytes, skip: set[int]) -> list[tuple[int, bytes]]:
    """Runs of differing bytes, at most CHUNK long, skipping `skip` offsets."""
    runs, i = [], 0
    while i < PAGE:
        if current[i] != want[i] and i not in skip:
            j = i
            while (j < PAGE and j - i < CHUNK and current[j] != want[j]
                   and j not in skip):
                j += 1
            runs.append((i, want[i:j]))
            i = j
        else:
            i += 1
    staged = sum(len(b) for _, b in runs) + 5 * len(runs)
    if staged > MAX_STAGE_BYTES:
        raise PresetError(
            "the preset differs from the ECU's page in %d bytes (%d staged); "
            "one transaction holds at most %d. Apply the built-in preset it "
            "was built on first (Base Tunes > APPLY ENGINE PRESET), then apply "
            "this one" % (sum(len(b) for _, b in runs), staged, MAX_STAGE_BYTES))
    return runs


def measured_offsets() -> set[int]:
    out = set()
    for n in MEASURED:
        try:
            o, w = field_span(n)
        except PresetError:
            continue
        out.update(range(o, o + w))
    return out


# ------------------------------------------------------------------ ECU I/O
def _connect(port):
    import me711_commission as MC
    sess = MC.Session("user_preset")
    link, ini, sig, ver = MC.connect(port, None, sess, b"SQVORW")
    return sess, link, ini, sig


def och_value(link, ini, name):
    """One output channel through the .ini, or None if absent/unreadable."""
    import me711_commission as MC
    if name not in ini.scalars:
        return None
    got = MC.Reader(link, ini, [name]).read()
    return None if got is None else got.get(name)


def write_runs(link, runs, before: bytes) -> str | None:
    """Write `runs`; None on success. On a refused write put back every run
    already written (from `before`) and return what happened."""
    done = []
    for off, data in runs:
        body, err, _ = link.request(b"W" + off.to_bytes(2, "big") + data, 4.0)
        if body is None:
            failed = []
            for o, d in reversed(done + [(off, data)]):
                old = before[o:o + len(d)]
                if link.request(b"W" + o.to_bytes(2, "big") + old, 4.0)[0] is None:
                    failed.append(o)
            return ("write at %d refused (%s); %s" % (
                off, err, "the %d earlier writes were put back" % len(done)
                if not failed else "putting back FAILED at %s - reload the "
                "page in TunerStudio before anything else" % failed))
        done.append((off, data))
    return None


def read_ecu_page(port) -> tuple[bytes, str]:
    sess, link, _ini, sig = _connect(port)
    try:
        page = link.page_read(PAGE)
        if page is None:
            raise PresetError("the page read failed (K-line); nothing saved")
        return page, sig
    finally:
        link.tr.close()
        sess.close()


def page_from_dump(path: Path, layout: str) -> bytes:
    import me711_store as ST
    cfg = (HCP.ROOT / "firmware/config/hcconfig.h").read_text()
    version = int(re.search(r"#define\s+HC_CFG_VERSION\s+(\d+)", cfg).group(1))
    best, seen = ST.newest_record(path.read_bytes(), int(layout, 16), version)
    if best is None:
        raise PresetError("no valid calibration record of layout %s in %s"
                          % (layout, path))
    return best[2]


# ---------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Save, list, show, apply and delete user presets "
                    "(whole calibration pages kept on this PC).",
        epilog="Library: %s (set HANICORE_USER_PRESETS to move it)." % library_dir())
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="built-in and user presets")
    s = sub.add_parser("show", help="one user preset's record")
    s.add_argument("name")
    s = sub.add_parser("save", help="store a page as a user preset")
    s.add_argument("name")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-ecu", action="store_true")
    src.add_argument("--from-dump", type=Path)
    src.add_argument("--from-page", type=Path)
    s.add_argument("--port"); s.add_argument("--note", default="")
    s.add_argument("--replace", action="store_true")
    s = sub.add_parser("apply", help="write a user preset into the ECU's "
                                      "working page (engine stopped, no Burn)")
    s.add_argument("name")
    s.add_argument("--port"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--include-measured", action="store_true")
    s = sub.add_parser("delete", help="remove a user preset (needs --yes)")
    s.add_argument("name")
    s.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    lib = Library()
    try:
        if a.cmd == "list":
            print("BUILT-IN (firmware, cannot be changed here):")
            for n in sorted(set(lib.builtins.values())):
                print("  %s" % n)
            print("USER (%s):" % lib.root)
            users = lib.user()
            for d in users:
                tag = "" if d["layout_id"] == layout_id() else \
                    "   [layout %s - not for this firmware]" % d["layout_id"]
                print("  %-40s %s  %s%s" % (d["name"], d["created_utc"],
                                           d["source"], tag))
            if not users:
                print("  (none)")
        elif a.cmd == "show":
            d = lib.find(a.name)
            for k in ("name", "layout_id", "signature", "source", "note",
                      "created_utc", "sha256"):
                print("%-12s %s" % (k, d.get(k, "")))
            lib.page(d)
            print("%-12s intact" % "page")
        elif a.cmd == "save":
            check_name(a.name, lib.builtins)        # before touching the ECU
            if not a.replace and any(slug(d["name"]) == slug(a.name)
                                     for d in lib.user()):
                raise PresetError("a user preset %r already exists; pass "
                                  "--replace to overwrite it" % a.name)
            lay = layout_id()
            if a.from_ecu:
                page, sig = read_ecu_page(a.port)
                if lay not in sig:
                    raise PresetError("the ECU answers %r, this tree's layout is "
                                      "%s; save with the matching tree" % (sig, lay))
                source = "ECU"
            elif a.from_dump:
                page, sig, source = page_from_dump(a.from_dump, lay), "", \
                    "bootmode dump %s" % a.from_dump.name
            else:
                page, sig, source = a.from_page.read_bytes(), "", \
                    "page file %s" % a.from_page.name
            path = lib.save(a.name, page, lay, source, a.note, a.replace, sig)
            print("saved user preset %r -> %s" % (a.name, path))
        elif a.cmd == "delete":
            if not a.yes:
                raise PresetError("deleting is permanent: repeat with --yes")
            path = lib.delete(a.name)
            print("deleted user preset %r (%s)" % (a.name, path.name))
        elif a.cmd == "apply":
            d = lib.find(a.name)
            want = lib.page(d)
            if d["layout_id"] != layout_id():
                raise PresetError("preset layout %s, firmware layout %s: migrate "
                                  "it (tools/calibration/me711_migrate_calibration.py)"
                                  % (d["layout_id"], layout_id()))
            skip = set() if a.include_measured else measured_offsets()
            sess, link, ini, sig = _connect(a.port)
            try:
                if d["layout_id"] not in sig:
                    raise PresetError("the ECU answers %r" % sig)
                rpm = och_value(link, ini, "rpm")
                if rpm is None or rpm != 0:
                    raise PresetError("the engine must be stopped (rpm %s); "
                                      "nothing written" % rpm)
                cur = link.page_read(PAGE)
                if cur is None:
                    raise PresetError("page read failed; nothing written")
                runs = plan_apply(cur, want, skip)
                print("%d bytes in %d writes%s" % (sum(len(b) for _, b in runs),
                      len(runs), " (dry run)" if a.dry_run else ""))
                if a.dry_run or not runs:
                    return 0
                err = write_runs(link, runs, cur)
                if err:
                    raise PresetError(err)
                after = link.page_read(PAGE)
                ok = after is not None and all(
                    after[i] == want[i] for i in range(PAGE) if i not in skip)
                val = och_value(link, ini, "cfgValidation")
                print("read-back %s; the ECU %s. NOT burned: check in "
                      "TunerStudio, then Burn."
                      % ("matches" if ok else "DOES NOT MATCH",
                         "accepts the setup" if val == 0 else
                         "REFUSES the setup (cfgValidation %s - see the "
                         "Diagnostics fault panel)" % val))
                return 0 if ok and val == 0 else 1
            finally:
                link.tr.close()
                sess.close()
    except PresetError as e:
        print("REFUSED: %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
