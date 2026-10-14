#!/usr/bin/env python3
r"""Gate: the runtime identity, the linked artefact, the manifest and the .ini
must all name the SAME build.

WHY. On the bench, 2026-09-02, the frozen V29 image identified itself as
"HaniCore V28 TRIGGER COMM" - the literal had last been edited for V28 and
nothing bumped it. A real physical result was recorded against the wrong
build. hctarget.h already carries that story; this gate is the check that
makes it impossible to repeat across ALL the artefacts, not just the two the
builder compares.

WHAT IT PROVES

  1  me711_image.STEM names a version    (…_vNN_…)
  2  TGT_VERSIONTXT contains that same VNN
  3  the LINKED BINARY contains TGT_VERSIONTXT verbatim, and contains no
     other "HaniCore V<other number>" string
  4  TGT_RELEASE_ID follows the project's series: 17416 + NN
       V44 = 0x4434 = 17460, V48 = 17464, V49 = 0x4439 = 17465
  5  the release id is actually present in the linked image
  6  the build manifest's `build` and `version_text` agree with 2 and with
     me711_image.EXPECTED_BUILD
  7  the manifest's sha256 is the sha256 of the linked binary on disk
  8  if the .ini exists: its filename matches the stem, and the releaseId it
     documents equals TGT_RELEASE_ID

MUTATION. --mutate proves the gate can fail: it re-runs every check against a
deliberately wrong version/id and expects each to reject it. A gate that
cannot fail is not a gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
import me711_image                                        # noqa: E402

HCTARGET = (ROOT / "firmware/targets/me711/hctarget.h")
RELEASE_ID_BASE = 17416        # V44 = 17460, V48 = 17464, V49 = 17465


def hctarget_define(name):
    txt = HCTARGET.read_text(errors="replace")
    m = re.search(r"^#define\s+" + re.escape(name) + r"\s+(.+?)\s*(?:/\*|$)",
                  txt, re.M)
    if not m:
        raise SystemExit("%s not found in hctarget.h" % name)
    return m.group(1).strip()


def check(results, label, ok, detail=""):
    results.append((label, ok))
    print("  [%s] %-56s %s" % ("PASS" if ok else "FAIL", label, detail))


def run(version_override=None, id_override=None):
    results = []
    stem = me711_image.STEM
    img_path = me711_image.image(check_manifest=False)
    img = img_path.read_bytes()

    m = re.search(r"_v(\d+)_", stem)
    check(results, "stem names a version", bool(m), stem)
    if not m:
        return results
    nn = int(m.group(1))
    if version_override is not None:
        nn = version_override
    vtag = "V%d" % nn

    vtxt = hctarget_define("TGT_VERSIONTXT").strip('"')
    check(results, "TGT_VERSIONTXT carries %s" % vtag,
          vtag in vtxt.split(), vtxt)

    check(results, "linked image contains the version string",
          vtxt.encode() in img, "at 0x%06X" % img.find(vtxt.encode()))

    others = set(re.findall(rb"HaniCore V(\d+)", img))
    stale = {int(o) for o in others} - {nn}
    check(results, "no stale HaniCore V<n> string in the image",
          not stale, "found %s" % sorted(stale) if stale else "only %s" % vtag)

    rid_txt = hctarget_define("TGT_RELEASE_ID")
    rid = int(re.sub(r"[uU]$", "", rid_txt.split()[0]), 0)
    if id_override is not None:
        rid = id_override
    want = RELEASE_ID_BASE + nn
    check(results, "TGT_RELEASE_ID follows the series 17416 + %d" % nn,
          rid == want, "0x%04X = %d (want %d)" % (rid, rid, want))

    check(results, "release id appears in the linked image",
          img.count(rid.to_bytes(2, "little")) > 0,
          "%d occurrence(s)" % img.count(rid.to_bytes(2, "little")))

    man_path = img_path.with_suffix(".json")
    man = json.loads(man_path.read_text())
    check(results, "manifest build == me711_image.EXPECTED_BUILD",
          man["build"] == me711_image.EXPECTED_BUILD,
          "%s vs %s" % (man["build"], me711_image.EXPECTED_BUILD))
    check(results, "manifest build carries %s" % vtag,
          man["build"].upper().startswith(vtag + "_"), man["build"])
    # 2026-10-11: the 'V' text carries the build id (source hash) as well
    bid = man.get("build_id") or ""
    check(results, "manifest version_text == TGT_VERSIONTXT + ' build <id>'",
          re.fullmatch(r"[0-9A-F]{8}", bid) is not None
          and man["version_text"] == vtxt + " build " + bid,
          man["version_text"])
    check(results, "manifest sha256 == sha256 of the linked binary",
          man["sha256"].upper() == hashlib.sha256(img).hexdigest().upper(),
          man["sha256"][:16] + "…")

    ini = ROOT / ("tunerstudio/hanicore_%s.ini" % stem.lower()
                  .replace("hanicore_me711_", "me711_"))
    if not ini.exists():
        ini = ROOT / ("tunerstudio/hanicore_%s.ini"
                      % stem.replace("HaniCore_ME711_", "me711_").lower())
    if ini.exists():
        t = ini.read_text(errors="replace")
        mm = re.search(r"releaseId.*?0x([0-9A-Fa-f]{4})", t)
        check(results, "INI documents the same release id",
              bool(mm) and int(mm.group(1), 16) == rid,
              ini.name + (" -> 0x%s" % mm.group(1) if mm else " (no id found)"))
        check(results, "INI filename carries %s" % vtag,
              ("v%d" % nn) in ini.name.lower(), ini.name)
    else:
        print("  [ -- ] .ini not generated yet: %s" % ini.name)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true",
                    help="prove the gate can fail")
    a = ap.parse_args()

    print("=== ME7.1.1 identity agreement ===")
    print("stem: %s" % me711_image.STEM)
    res = run()
    ok = all(v for _, v in res)
    print("")
    print("%d/%d checks pass" % (sum(1 for _, v in res if v), len(res)))

    if a.mutate:
        print("")
        print("=== MUTATION: version+1 and release id+1 must be REJECTED ===")
        m = re.search(r"_v(\d+)_", me711_image.STEM)
        nn = int(m.group(1))
        bad_v = run(version_override=nn + 1)
        bad_i = run(id_override=RELEASE_ID_BASE + nn + 7)
        vfail = sum(1 for _, v in bad_v if not v)
        ifail = sum(1 for _, v in bad_i if not v)
        print("")
        print("  wrong version rejected by %d check(s)" % vfail)
        print("  wrong release id rejected by %d check(s)" % ifail)
        if vfail == 0 or ifail == 0:
            print("  !! MUTATION NOT DETECTED - this gate cannot fail")
            ok = False

    print("")
    print("me711_identity_proof: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
