# DXMT on iOS

Builds the iOS side of DXMT — the D3D11→Metal translation layer — as a
static library that links into Madeira.app, plus the aarch64-windows PE
DLLs the game loads via Wine.

The upstream DXMT source lives at `dxmt/` as a git submodule
pointing at our fork [willfaust/dxmt](https://github.com/willfaust/dxmt),
`ios-port` branch. The iOS patches are committed there, not here.

## What this produces

- `libdxmt_combined.a` (~79MB) → `app/Madeira/libdxmt_combined.a`.
  DXMT's unix/Metal side + airconv shader translator + LLVM 15 static
  libs, combined into one archive Xcode links.
- `d3d11.dll`, `dxgi.dll`, `winemetal.dll`, `d3d10core.dll`, `d3d9.dll` →
  `app/Madeira/arm64ec-windows/` and `app/Madeira/i386-windows/`.
  The i386 D3D9 shim is installed as `d3d9.dll` and `d3d9shim.dll`, with
  the emulated frontend beside it as `d3d9-emulated.dll`.
- `d3d11.dll`, `dxgi.dll`, `winemetal.dll` → `app/Madeira/aarch64-windows/`.
  AArch64's existing `d3d9.dll` and `d3d10core.dll` keep their Wine ownership.
- `nvapi64.dll` → `app/Madeira/arm64ec-windows/`.

Both are gitignored — rebuild via the steps below.

## Prerequisites

1. Clone with submodules: `git clone --recurse-submodules ...`, or run
   `git submodule update --init --recursive` after cloning.

2. **llvm-mingw** (aarch64-w64-mingw32) at
   `toolchains/llvm-mingw-20260421-ucrt-macos-universal/`:
   ```
   mkdir -p toolchains && \
   curl -L https://github.com/mstorsjo/llvm-mingw/releases/download/20260421/llvm-mingw-20260421-ucrt-macos-universal.tar.xz \
       | tar -xJ -C toolchains/
   ```

3. **LLVM 15.0.7 cross-built for iOS-aarch64** at `toolchains/llvm-ios-build/`.
   Two-stage build — first llvm-tblgen for macOS host, then iOS target libs
   reusing it. Flags used (summary):
   - Host stage: vanilla Release build of `llvm-tblgen`.
   - iOS stage: `CMAKE_SYSTEM_NAME=iOS`, `CMAKE_OSX_SYSROOT=iphoneos`,
     `LLVM_TABLEGEN=<host tblgen>`, `LLVM_BUILD_UTILS=Off`, no targets.
     Needs a one-line edit to `llvm/cmake/modules/AddLLVM.cmake` changing
     `MATCHES "Darwin"` to `MATCHES "Darwin|iOS"` so `-dead_strip` is used
     instead of `--gc-sections` (which Apple ld doesn't accept).

4. **Metal Toolchain**: `xcodebuild -downloadComponent MetalToolchain`

5. **Wine aarch64-windows static libs** already built in
   `wine/build-macos/` — see `build/ntdll-unix/build.sh` and the Wine
   submodule for the original configure.

6. **DXMT's own nested submodules**: nvapi + mingw-directx-headers.
   Covered by the top-level recursive submodule update in step 1.

## Build steps

### PE side

First build Wine's three Windows farms and their import libraries in
`wine/build-arm64ec`, `wine/build-macos` and `wine/build-i386`. When the
complete runtime build calls this DXMT script separately, run the i386 Wine
build with `SKIP_DXMT=1` to avoid rebuilding DXMT twice.

From the repository root:

```sh
bash build/dxmt-ios/build-pe.sh
```

The script builds all three architectures from the pinned DXMT revision,
validates the outputs before installing them, and preserves the source
ownership listed above. `LLVM_MINGW` may override the toolchain directory
(without `/bin`); `JOBS` controls parallel compilation. ARM64EC outputs stay
under `dxmt/build-arm64ec` for the Madeira D3D12 link.

### Unix side (libdxmt_combined.a)

```
bash build/dxmt-ios/build.sh
```

A full build clears previous DXMT objects and creates a new combined archive
from those objects and the pinned iOS LLVM libraries. It stages the result
into `app/Madeira/libdxmt_combined.a`, replacing any companion-release copy.
Both build halves apply `build/dxmt-patches/` and generate Metal 3.1 shader
headers through `tools/build/build-shader-headers.sh`, including the existing
Xcode 27 atomic patch. Updating only the submodule pin does not update the IPA's
native archive or its Windows DLLs.

## What the fork changes vs upstream

See `git log --oneline upstream/main..ios-port` on the `willfaust/dxmt`
repo. Summary: Cocoa→UIKit conditionals, NSScreen/ColorSync/CGDirectDisplay
stubs, bootstrap.h fallback, symbol rename to avoid collision with ntdll's
own `__wine_unix_call_funcs`, skip cross-process swapchain check, and the
`build-aarch64-win.txt` meson cross file.
