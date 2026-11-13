#!/usr/bin/env bash
# Preserve cached headers; obtain separate Git source trees when packaging.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_CACHE="$ROOT/toolchains/runtime-sources"
prepare() {
  local preferred=$1 fallback=$2 url=$3 tag=$4 expected=$5 name=$6 source
  source="$preferred"
  if [[ ! -e "$source/.git" ]]; then
    source="$SOURCE_CACHE/$fallback"
    if [[ ! -e "$source/.git" ]]; then
      [[ ! -e "$source" ]] || { echo "Incomplete source checkout: $source" >&2; exit 1; }
      mkdir -p "$SOURCE_CACHE"
      git clone --depth 1 --branch "$tag" "$url" "$source"
    fi
  fi
  [[ "$(git -C "$source" rev-parse HEAD)" == "$expected" ]] || {
    echo "Source revision does not match the runtime dependency: $source" >&2
    exit 1
  }
  printf '%s=%s\n' "$name" "$source" >> "$GITHUB_ENV"
}
prepare "$ROOT/toolchains/llvm-project" llvm-project \
  https://github.com/llvm/llvm-project.git llvmorg-15.0.7 \
  8dfdcc7b7bf66834a761bd8de445840ef68e4d1a RUNTIME_LLVM_SOURCE
# The FreeType pin is the peeled VER-2-13-3 release tag.
prepare "$ROOT/research/freetype" freetype \
  https://github.com/freetype/freetype.git VER-2-13-3 \
  42608f77f20749dd6ddc9e0536788eaad70ea4b5 RUNTIME_FREETYPE_SOURCE
