#!/usr/bin/env bash
# Host tests for the offline Bosch components. These compile the REAL
# modules, not copies: anything in tests/host must stay free of SFR access.
#
#   bash tests/host/run_host_tests.sh
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# msys2 gcc fails silently (exit 1, no diagnostics) unless its own bin
# directory is on PATH - it needs the DLLs beside it.
for d in /c/msys64/mingw64/bin /mingw64/bin /usr/bin; do
    [ -x "$d/gcc.exe" ] && export PATH="$d:$PATH" && break
done
command -v gcc >/dev/null || { echo "no gcc on PATH - skipping host tests"; exit 0; }

BOSCH=firmware/targets/me711
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
rc=0

echo "=== host tests ==="
gcc -std=c99 -Wall -Wextra -Werror \
    -o "$OUT/test_asic_startup_frame" \
    tests/host/test_asic_startup_frame.c "$BOSCH/asic/hcasicframe.c" \
    -I"$BOSCH" -I"$BOSCH/asic" || { echo "BUILD FAILED"; exit 1; }
"$OUT/test_asic_startup_frame" || rc=1

exit $rc
