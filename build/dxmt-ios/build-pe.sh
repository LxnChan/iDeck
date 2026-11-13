#!/usr/bin/env bash
# Build all shipped DXMT Windows DLLs against the matching Wine import libraries.
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TC="${LLVM_MINGW:-$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal}/bin"
export PATH="$TC:$PATH"
export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
JOBS="${JOBS:-$(sysctl -n hw.ncpu)}"
REVISION="$(git -C "$R/dxmt" rev-parse HEAD)"
bash "$R/build/dxmt-patches/apply.sh"
bash "$R/tools/build/build-shader-headers.sh"

# Configure with explicit tool paths rather than requiring a toolchains symlink
# in the submodule. The ARM64EC build path is also used by Madeira's D3D12 link.
for arch in arm64ec aarch64 i386; do
    case "$arch" in
        arm64ec) triple=arm64ec; family=aarch64; cpu=aarch64; W="$R/wine/build-arm64ec"; nvapi=true ;;
        aarch64) triple=aarch64; family=aarch64; cpu=aarch64; W="$R/wine/build-macos"; nvapi=false ;;
        i386) triple=i686; family=x86; cpu=i686; W="$R/wine/build-i386"; nvapi=false ;;
    esac
    B="$R/dxmt/build-$arch"
    X="$W/dxmt-$arch.ini"
    [ -x "$TC/$triple-w64-mingw32-clang" ] || { echo "Missing $triple llvm-mingw compiler" >&2; exit 1; }
    [ -x "$W/tools/winebuild/winebuild" ] || { echo "Build the $arch Wine runtime first" >&2; exit 1; }
    cat > "$X" <<EOF
[binaries]
c = '$TC/$triple-w64-mingw32-clang'
cpp = '$TC/$triple-w64-mingw32-clang++'
ar = '$TC/$triple-w64-mingw32-ar'
strip = '$TC/$triple-w64-mingw32-strip'
windres = '$TC/$triple-w64-mingw32-windres'
dlltool = '$TC/$triple-w64-mingw32-dlltool'

[properties]
needs_exe_wrapper = true

[host_machine]
system = 'windows'
cpu_family = '$family'
cpu = '$cpu'
endian = 'little'
EOF
    reconfigure=""
    [ ! -f "$B/build.ninja" ] || reconfigure=--reconfigure
    meson setup "$B" "$R/dxmt" $reconfigure \
        --cross-file "$X" --native-file "$R/dxmt/build-osx.txt" --buildtype release \
        -Dwine_build_path="$W" -Dwine_builtin_dll=true -Denable_nvapi="$nvapi" \
        -Dmetal_std=metal3.1
    meson compile -C "$B" -j "$JOBS"
done

# Validate every architecture before overwriting any installed DXMT module.
for arch in arm64ec aarch64 i386; do
    B="$R/dxmt/build-$arch"
    for m in d3d11/d3d11.dll dxgi/dxgi.dll d3d10/d3d10core.dll winemetal/winemetal.dll d3d9/d3d9.dll; do
        [ -s "$B/src/$m" ] || { echo "Missing DXMT $arch/$m" >&2; exit 1; }
    done
    if [ "$arch" = i386 ]; then
        [ -s "$B/src/d3d9shim/d3d9shim.dll" ] || { echo "Missing i386 D3D9 shim" >&2; exit 1; }
    elif [ "$arch" = arm64ec ]; then
        [ -s "$B/src/nvapi/nvapi64.dll" ] || { echo "Missing ARM64EC NVAPI" >&2; exit 1; }
    fi
done
[ "$(git -C "$R/dxmt" rev-parse HEAD)" = "$REVISION" ] || { echo "DXMT revision changed during build" >&2; exit 1; }

for arch in arm64ec aarch64 i386; do
    B="$R/dxmt/build-$arch"
    DEST="$R/app/Madeira/$arch-windows"
    triple="$arch"
    [ "$arch" != i386 ] || triple=i686
    STRIP="$TC/$triple-w64-mingw32-strip"
    mkdir -p "$DEST"
    for m in d3d11/d3d11.dll dxgi/dxgi.dll d3d10/d3d10core.dll winemetal/winemetal.dll; do
        # Preserve the inherited AArch64 Wine D3D9/D3D10 ownership. The x64
        # ARM64EC and WoW64 i386 game paths use the DXMT frontends below.
        [ "$arch:$m" != aarch64:d3d10/d3d10core.dll ] || continue
        "$STRIP" --strip-debug -o "$DEST/$(basename "$m").tmp" "$B/src/$m"
        mv -f "$DEST/$(basename "$m").tmp" "$DEST/$(basename "$m")"
    done
    if [ "$arch" = i386 ]; then
        pairs=('d3d9shim/d3d9shim.dll:d3d9.dll' 'd3d9shim/d3d9shim.dll:d3d9shim.dll' 'd3d9/d3d9.dll:d3d9-emulated.dll')
    elif [ "$arch" = arm64ec ]; then
        pairs=('d3d9/d3d9.dll:d3d9.dll' 'nvapi/nvapi64.dll:nvapi64.dll')
    else
        pairs=()
    fi
    if [ ${#pairs[@]} -gt 0 ]; then
        for pair in "${pairs[@]}"; do
            "$STRIP" --strip-debug -o "$DEST/${pair#*:}.tmp" "$B/src/${pair%:*}"
            mv -f "$DEST/${pair#*:}.tmp" "$DEST/${pair#*:}"
        done
    fi
    echo "Staged DXMT $arch from $REVISION"
done
