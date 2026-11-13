#!/usr/bin/env bash
# Generate the Metal 3.1 shader headers consumed by both DXMT build halves.
set -euo pipefail
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC="$ROOT/dxmt/src/airconv/shaders"
OUT="$ROOT/build/dxmt-ios/shader-headers"
PATCH="$ROOT/build/dxmt-ios/xcode27-metal-atomic.patch"
if git -C "$ROOT/dxmt" apply --unidiff-zero --check "$PATCH"; then
  git -C "$ROOT/dxmt" apply --unidiff-zero "$PATCH"
elif ! git -C "$ROOT/dxmt" apply --unidiff-zero --reverse --check "$PATCH"; then
  echo "ERROR: DXMT Metal atomic patch does not match the pinned source" >&2
  exit 1
fi
mkdir -p "$OUT"
for name in air_msad air_samplepos air_tessellation; do
  xcrun -sdk macosx metal -o "$OUT/$name.air" -c "$SRC/$name.metal" \
    -std=metal3.1 --target=air64-apple-macos14.0
  xxd -n "$name" -i "$OUT/$name.air" "$OUT/$name.h"
done
