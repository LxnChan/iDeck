#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
# An IPA contains a re-signed converter. Native DXMT requires the original
# package bytes pinned by build/madeira-d3d12/deps.sh, before code signing.
set -euo pipefail
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DEST="$ROOT/app/Madeira/d3d12/libmetalirconverter.dylib"
SHA256=073f903be98e973ff38f4d79f2c48d61ef938754a77b1caedda79c9f05a068c2
REVISION=fbad430410b4075192166172447c859714726de9
URL="https://raw.githubusercontent.com/willfaust/Madeira/$REVISION/app/Madeira/d3d12/libmetalirconverter.dylib"
if [[ -f "$DEST" ]] && printf '%s  %s\n' "$SHA256" "$DEST" | shasum -a 256 -c - >/dev/null 2>&1; then
    echo "Metal Shader Converter: verified original package bytes"
    exit 0
fi
mkdir -p "$(dirname "$DEST")"
curl -fL --retry 3 "$URL" -o "$DEST.part"
printf '%s  %s\n' "$SHA256" "$DEST.part" | shasum -a 256 -c -
mv -f "$DEST.part" "$DEST"
