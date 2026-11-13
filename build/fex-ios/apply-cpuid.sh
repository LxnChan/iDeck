#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
# Merge the existing iDeck CPUID patch with the pinned FEX revision.
# Its original context predates the fork's independent AVX2 reporting.
set -eu
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
F="$R/FEX"
PATCH="$R/build/fex-ios/fex-cpuid-bmi-fma.patch"
BASE=f59cab95659e8add0c88f0c76ec1cf483c536dbf
BASE_BLOB=9c305e8872d91ab03ac385382de84bfddbe2d4d8

if ! git -C "$F" cat-file -e "$BASE_BLOB" 2>/dev/null; then
    git -C "$F" fetch --no-tags --depth=1 origin "$BASE"
fi
# Three-way application keeps the upstream AVX2 change and is idempotent.
# A conflict stops the build instead of silently omitting BMI/FMA support.
git -C "$F" apply --3way --check "$PATCH"
git -C "$F" apply --3way "$PATCH"
