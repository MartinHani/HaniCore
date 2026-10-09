"""Measure ONE Burn from me711_flash_bus_proof's own rig, with a settable
simulated budget, so the "383 of 2060" result can be attributed rather than
assumed.

    HC_BURN_LIMIT_MS=60000 py burnmeasure.py
    HANICORE_ME711_STEM=HaniCore_ME711_v49_live_burn_nmi_forensics ... (control)
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lib"))
import hcpaths  # noqa: F401,E402  (puts every tools/ and tests/ module on sys.path)
os.chdir(ROOT)

import me711_image                       # noqa: E402
import me711_flash_bus_proof as G        # noqa: E402

img = me711_image.image()
t0 = time.time()
rig, dev, reply, spm = G.burn_run(img, release_steps=0)
print("image    :", me711_image.STEM)
print("limit_ms :", os.environ.get("HC_BURN_LIMIT_MS", "9000"))
print("reply    :", reply)
print("programs :", dev.programs, "of 2060")
print("wall     :", round(time.time() - t0, 1), "s")
