#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
# Rebuild the complete ARM64EC and AArch64 Wine PE farms, then install the
# iDeck helper DLLs. FEX, DXMT and i386 Wine are built by their own stages.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${LLVM_MINGW:?Set LLVM_MINGW to the verified LLVM-MinGW toolchain directory}"
TC="$LLVM_MINGW/bin"
export PATH="$TC:$PATH"
JOBS="${JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 8)}"
backup="$(mktemp -d "${TMPDIR:-/tmp}/ideck-wine-makefiles.XXXXXX")"
undelayed=()
restore_makefiles() {
    local module
    for module in "${undelayed[@]+"${undelayed[@]}"}"; do
        cp "$backup/$module" "$R/wine/dlls/$module/Makefile.in"
    done
    undelayed=()
}
cleanup() { restore_makefiles; rm -rf "$backup"; }
trap cleanup EXIT

for arch in arm64ec aarch64; do
    case "$arch" in
        arm64ec) B="$R/wine/build-arm64ec"; STRIP="$TC/arm64ec-w64-mingw32-strip" ;;
        aarch64) B="$R/wine/build-macos"; STRIP="$TC/aarch64-w64-mingw32-strip" ;;
    esac
    DEST="$R/app/Madeira/$arch-windows"
    [ -f "$B/config.status" ] || { echo "ERROR: configure Wine $arch before building its PE farm" >&2; exit 1; }
    [ -x "$STRIP" ] || { echo "ERROR: missing $STRIP" >&2; exit 1; }
    mkdir -p "$DEST" "$B/dlls/stdole2.tlb"
    if [ "$arch" = arm64ec ] && [ ! -e "$B/dlls/stdole2.tlb/aarch64-windows" ]; then
        ln -s arm64ec-windows "$B/dlls/stdole2.tlb/aarch64-windows"
    fi
    python3 "$R/build/windows-runtime/targets.py" --makefile "$B/Makefile" --arch "$arch" > "$B/ideck-pe-targets.txt"
    TARGETS=()
    while IFS= read -r target; do TARGETS+=("$target"); done < "$B/ideck-pe-targets.txt"
    if [ "$arch" = arm64ec ] && [ "${UNDELAY:-1}" != 0 ]; then
        # Use Madeira's eager-import policy for ARM64EC modules, retaining
        # CRT delay imports to avoid locale initialization cycles. Restore
        # the original source bytes even if compilation fails.
        for target in "${TARGETS[@]}"; do
            case "$target" in dlls/*) ;; *) continue ;; esac
            module="${target#dlls/}"; module="${module%%/*}"
            mk="$R/wine/dlls/$module/Makefile.in"
            [ -f "$mk" ] || continue
            [ "$module" != msvcrt ] || continue
            grep -Eq '^PARENTSRC[[:space:]]*=[[:space:]]*\.\./msvcrt([[:space:]]|$)' "$mk" && continue
            delayed="$(sed -n 's/^DELAYIMPORTS[[:space:]]*=[[:space:]]*//p' "$mk")"
            [ -n "$delayed" ] && grep -q '^IMPORTS' "$mk" || continue
            complete=1
            for dependency in $delayed; do
                if [ ! -f "$DEST/$dependency.dll" ] && ! grep -F "/$dependency.dll" "$B/ideck-pe-targets.txt" >/dev/null; then
                    complete=0
                fi
            done
            [ "$complete" = 1 ] || continue
            cp "$mk" "$backup/$module"
            undelayed+=("$module")
            sed -i.bak -e '/^DELAYIMPORTS[[:space:]]*=/d' -e "s/^\(IMPORTS[[:space:]]*=.*\)\$/\1 $delayed/" "$mk"
            rm -f "$mk.bak" "$B/$target"
        done
    fi
    echo "== Building ${#TARGETS[@]} Wine $arch modules =="
    # File targets build the PE half only, including import libraries and host
    # tools it depends on. They do not try to build GStreamer/macOS unix .so's.
    make -C "$B" -j"$JOBS" "${TARGETS[@]}"
    for target in "${TARGETS[@]}"; do
        out="$DEST/$(basename "$target")"
        cp "$B/$target" "$out.tmp"
        case "$out" in *.tlb) ;; *) "$STRIP" --strip-debug "$out.tmp" ;; esac
        mv "$out.tmp" "$out"
    done
    restore_makefiles
done

# The ARM64EC image mapper needs ntdll's image-size padding. Its script uses
# the same build tree, so make reuses the ntdll built above.
bash "$R/build/wine-pe/build-ntdll.sh"
DEST="$R/app/Madeira/arm64ec-windows" bash "$R/build/faultrep/build.sh"
bash "$R/build/wintypes-compat/build.sh" "$R/build/stub-dlls/wintypes"
cp "$R/build/stub-dlls/wintypes/wintypes.dll" "$R/app/Madeira/arm64ec-windows/wintypes.dll"
echo "== Installed Wine PE farms from $(git -C "$R/wine" rev-parse --short HEAD) =="
