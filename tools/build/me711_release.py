#!/usr/bin/env python3
r"""
me711_release.py - freeze the current build into a release directory, with
every number DERIVED from the artefacts rather than typed.

    py tools\build\me711_release.py <DirectoryName>

WHY IT DERIVES EVERYTHING. Four separate incidents in this project came from
two artefacts that had to agree and nothing that made them agree: six gates
auditing a V19 binary after the build moved to V20; a manifest disagreeing with
its header; an ME7.5 image two commits older than its tools; and - on real
hardware - the frozen V29 binary opened beside a `.ini` whose `ochBlockSize`
had drifted four bytes.

So this tool:

  * copies the CURRENT build's binary, map, payload and manifest, and the
    `.ini` GENERATED FROM THE SAME SOURCES, into one directory;
  * hashes each file it wrote and writes SHA256SUMS from those hashes, not
    from anything it was told;
  * refuses if the binary's own version string does not name the build in its
    own filename;
  * refuses if the shipped `.ini`'s ochBlockSize does not equal the firmware's
    TGT_OCH_SIZE - and then tells you to run the proof that MEASURES it by
    executing the image, because equal numbers in two files is a weaker claim
    than a measured reply;
  * refuses to overwrite a directory that already exists, because a frozen
    package that can be silently regenerated is not frozen.

It does not flash anything and it does not decide that a build is ready.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)

import me711_image as PI            # noqa: E402  names the image ONCE

TDIR = ROOT / "firmware/targets/me711"
INI = ROOT / ("tunerstudio/hanicore_%s.ini"
              % PI.STEM.replace("HaniCore_ME711_", "me711_").lower())
FORENSIC_INI = INI.with_name(INI.stem + "_forensic.ini")
ROLLBACK = ROOT / ("release/Porsche_ME711_V29_PHYSICAL_TEST/"
                   "ROLLBACK_HaniCore_ME711_A1146_mainrelay_v26.bin")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = ROOT / "release" / argv[1]
    if out.exists():
        raise SystemExit("%s already exists. A frozen package that can be "
                         "silently regenerated is not frozen - pick another "
                         "name or delete it deliberately." % out)

    img = PI.image()
    if not img.exists():
        raise SystemExit("no image - run tools/build/build_hanicore_me711.py first")

    tgt = (TDIR / "hctarget.h").read_text(errors="replace")
    ver = re.search(r'#define TGT_VERSIONTXT\s+"([^"]+)"', tgt).group(1)
    och = int(re.search(r"#define\s+TGT_OCH_SIZE\s+(\d+)", tgt).group(1))

    # The identity check the V29 package failed: its binary reported
    # "HaniCore V28 TRIGGER COMM" while its filename said v29, so a real
    # hardware log recorded the wrong build against a real result.
    tag = re.search(r"_v(\d+)", PI.STEM, re.I)
    if not tag or ("V%s" % tag.group(1)) not in ver.upper():
        raise SystemExit("the image is called %s but reports %r - refusing"
                         % (PI.STEM, ver))

    if not INI.exists():
        raise SystemExit("%s has not been generated" % INI.name)
    ini_och = int(re.search(r"^\s*ochBlockSize\s*=\s*(\d+)",
                            INI.read_text(errors="replace"), re.M).group(1))
    if ini_och != och:
        raise SystemExit("the .ini says ochBlockSize %d, the firmware says %d "
                         "- this is the V29 bench failure" % (ini_och, och))

    forensic_och = None
    if FORENSIC_INI.exists():
        forensic_och = int(re.search(r"^\s*ochBlockSize\s*=\s*(\d+)",
                           FORENSIC_INI.read_text(errors="replace"),
                           re.M).group(1))
        # TGT_OCH_READ_SIZE IS AN EXPRESSION NOW, NOT A LITERAL. It is
        # (TGT_OCH_SIZE + 344u) - the ordinary block plus HC_LF_BYTES - because
        # the live-Burn record starts where the block ends and a literal here
        # went stale twice. Accept either spelling and evaluate the derived
        # one, or this check silently stops matching anything.
        read_m = re.search(r"#define\s+TGT_OCH_READ_SIZE\s+(\d+)", tgt)
        tl_m = re.search(r"#define\s+TGT_TL_EXPORT_BYTES\s+(\d+)u?", tgt)
        if read_m is not None:
            want_read = int(read_m.group(1))
        elif re.search(r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                       r"\s*\+\s*(\d+)u?\)", tgt):
            want_read = och + int(re.search(
                r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                r"\s*\+\s*(\d+)u?\)", tgt).group(1))
        elif re.search(r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                       r"\s*\+\s*(\d+)u?\s*\+\s*TGT_TL_EXPORT_BYTES\)",
                       tgt) and tl_m:
            # V92: the read window ends with the tooth-profile export, which
            # only the vehicle logger reads (hc_och_ext_byte). The forensic
            # .ini covers the block and the live-Burn record, i.e. the
            # window WITHOUT that tail.
            want_read = och + int(re.search(
                r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                r"\s*\+\s*(\d+)u?", tgt).group(1))
        elif re.search(r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                       r"\s*\+\s*(\d+)u?\s*\+\s*TGT_TL_EXPORT_BYTES\s*"
                       r"\+\s*TGT_BH_EXPORT_BYTES\)", tgt) and tl_m:
            # V93: the boot history follows the profile; the forensic view
            # is still the block + the live-Burn record.
            want_read = och + int(re.search(
                r"#define\s+TGT_OCH_READ_SIZE\s+\(TGT_OCH_SIZE"
                r"\s*\+\s*(\d+)u?", tgt).group(1))
        else:
            want_read = None
        if want_read is None or forensic_och != want_read:
            raise SystemExit("forensic .ini block does not match "
                             "TGT_OCH_READ_SIZE")

    out.mkdir(parents=True)
    written = []
    for suffix in (".bin", ".hex", ".M66", ".H86", ".json"):
        src = img.with_suffix(suffix)
        if src.exists():
            shutil.copy2(src, out / src.name)
            written.append(out / src.name)
    shutil.copy2(INI, out / INI.name)
    written.append(out / INI.name)
    if FORENSIC_INI.exists():
        shutil.copy2(FORENSIC_INI, out / FORENSIC_INI.name)
        written.append(out / FORENSIC_INI.name)

    # Release-specific extras (README, evidence, the version's own proofs)
    # used to be hard-coded here per frozen release (V49..V52). Those
    # packages are frozen; a new release adds its README and bench card to
    # the package directory by hand after this tool has written it.
    if ROLLBACK.exists():
        shutil.copy2(ROLLBACK, out / ROLLBACK.name)
        written.append(out / ROLLBACK.name)

    lines = ["%s *%s" % (sha(p), p.name) for p in sorted(written,
                                                         key=lambda x: x.name)]
    # LF, EXPLICITLY. Without newline="" Python translates every \n to \r\n on
    # Windows, and `sha256sum -c SHA256SUMS.txt` then reads each filename with
    # a trailing carriage return and reports every file missing - a frozen
    # manifest that cannot verify its own package with the tool an operator
    # reaches for. .gitattributes already carries `release/** -text` to stop
    # git doing the same thing on checkout, for the same reason:
    # V27_TRIGGER_BENCH failed its own SHA256SUMS that way. The hashes were
    # always right; the file listing them was not readable.
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n",
                                        encoding="ascii", newline="\n")

    print("wrote %s" % out)
    for line in lines:
        print("  " + line)
    print("\n  identity   %r" % ver)
    print("  och block  %d, firmware and .ini agree" % och)
    if forensic_och is not None:
        print("  forensic read-only view %d, firmware and companion .ini agree"
              % forensic_och)
    print("\n  NOW PROVE IT, do not take the equality above as the proof:")
    print("    py tests\\tunerstudio\\me711_och_contract_proof.py --image %s --ini %s"
          % ((out / img.name).relative_to(ROOT),
             (out / INI.name).relative_to(ROOT)))
    print("    py tests\\tunerstudio\\ts_ini_ui_contract.py %s"
          % (out / INI.name).relative_to(ROOT))
    print("\n  And write the bench card. A package without one is a binary "
          "nobody can safely flash.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
