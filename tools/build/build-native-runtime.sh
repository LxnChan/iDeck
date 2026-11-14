#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
# Keep binary-affecting commands in cache-keyed recipes, outside workflow YAML.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$ROOT/build/fex-ios/build.sh"
bash "$ROOT/build/ntdll-unix/build.sh"
bash "$ROOT/build/win32u-unix/build.sh"
WINE_REBUILD_ALL=1 bash "$ROOT/build/wineserver/build.sh"
bash "$ROOT/build/dxmt-ios/build.sh"
