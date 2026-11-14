#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$ROOT/build/windows-runtime/build.sh"
SKIP_DXMT=1 bash "$ROOT/build/wine-i386/build.sh"
bash "$ROOT/build/dxmt-ios/build-pe.sh"
bash "$ROOT/build/fex-arm64ec/build.sh"
bash "$ROOT/build/fex-wow64/build.sh"
