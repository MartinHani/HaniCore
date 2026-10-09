#!/usr/bin/env bash
# fetch_references.sh - fetch the EXACT external references the research docs
# cite, into reference/ (gitignored, local only). Nothing here is committed.
#
#   bash tools/research/fetch_references.sh [destdir]
#
# rusEFI : tag 2026-08-14 = commit add480a83b113150f7bacc6245c305e98c794ed1,
#          whose generated Proteus F7 .ini carries the signature
#          "rusEFI master.2026.08.13.proteus_f7.3335871282" (the file the
#          operator examined). The earlier tag 2026-08-13 still carries
#          master.2026.08.11; 2026-08-14..16 all carry master.2026.08.13.
# Speeduino: noisymime/speeduino master 473b4b48a070db547aaedbbf10c75106d58e2f6b
#          (2026-09-30), reference/speeduino.ini + speeduino/*.cpp.
#
# Both are GPL. They are READ for semantics; no GPL source is copied into
# HaniCore (docs/research/RUSEFI_HANICORE_PARITY.md section "Licensing").
set -eu
DEST="${1:-$(cd "$(dirname "$0")/../.." && pwd)/reference}"
mkdir -p "$DEST"
cd "$DEST"

RUSEFI_TAG=2026-08-14
RUSEFI_SHA=add480a83b113150f7bacc6245c305e98c794ed1
SPEEDUINO_SHA=473b4b48a070db547aaedbbf10c75106d58e2f6b

if [ ! -d rusefi_research/.git ]; then
    git clone --filter=blob:none --no-checkout https://github.com/rusefi/rusefi.git rusefi_research
fi
cd rusefi_research
git sparse-checkout init --cone
git sparse-checkout set firmware/controllers firmware/integration firmware/tunerstudio \
    firmware/config firmware/init firmware/console firmware/util unit_tests/tests
git fetch --depth 1 --filter=blob:none origin tag "$RUSEFI_TAG"
git checkout -q "$RUSEFI_SHA"
cd ..

if [ ! -d speeduino_research/.git ]; then
    git clone --filter=blob:none https://github.com/noisymime/speeduino.git speeduino_research
fi
( cd speeduino_research && git fetch -q origin && git checkout -q "$SPEEDUINO_SHA" ) || \
    echo "speeduino: $SPEEDUINO_SHA not reachable - using the default branch head"

# speeduino/Tunes (CC BY-NC 4.0): the public "Stock Audi A4 B5 1.8t" base tune
# used as a cross-check in docs/research/AWT_18T_BASEMAP_RESEARCH.md. Not committed;
# tools/research/build_awt_calibration_candidates.py reads it from here.
SPEEDUINO_TUNES_SHA=99b2a62e402144fa38c911f937b2b6571c8a720a
if [ ! -d speeduino_tunes/.git ]; then
    git clone --filter=blob:none https://github.com/speeduino/Tunes.git speeduino_tunes
fi
( cd speeduino_tunes && git checkout -q "$SPEEDUINO_TUNES_SHA" ) || true

echo "rusEFI    -> $DEST/rusefi_research   ($(cd rusefi_research && git rev-parse HEAD))"
echo "Speeduino -> $DEST/speeduino_research ($(cd speeduino_research && git rev-parse HEAD))"
echo "Proteus F7 .ini: $DEST/rusefi_research/firmware/tunerstudio/generated/rusefi_proteus_f7.ini"
