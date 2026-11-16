# Experimental x64 OpenGL through D3D12

This opt-in path builds Mesa 25.0.7's Windows WGL frontend and D3D12
Gallium driver. Windows OpenGL calls execute in the x64 guest; D3D12 calls reach
Madeira's existing Metal renderer. It does not provide Vulkan, 32-bit OpenGL,
or a guarantee that any particular game works.

The MIT-licensed patches in `patches/` keep shared submission fences on capable
backends, and retries with a private fence only when shared creation returns
`E_NOTIMPL` or `DXGI_ERROR_UNSUPPORTED`. Allocation and device failures still
fail initialization. This preserves the queue's local synchronization without
claiming cross-process sharing support. Initialization failures and successful
screen creation are logged even in release builds through Mesa's Windows debugger
log sink, so GUI applications without a console also emit them.

WGL accepts repeated selection of a window's existing pixel format. Godot sets
that format once for the window and again before its first context; upstream
Mesa 25.0.7 rejects the second call. The patch accepts the identical format,
continues rejecting changes to another format and retains the pbuffer exception.
Pixel format decisions and context initialization are logged for device diagnosis.

Godot's compatibility renderer uses point transform feedback for skeletons and
blend shapes. Madeira's D3D12 runtime currently has no native stream output;
the data-only vertex shaders also produce a void Metal return type and their
pipelines fail when rasterization is enabled. The point feedback patches write
the final float/integer outputs directly to UAVs on the GPU, preserving vertex
order, target ranges, append/reset offsets and whole-vertex overflow bounds.
A clipped position keeps those data-only passes valid on the current Metal
runtime without producing fragments. This avoids rebuilding or changing the
companion D3D12 runtime.

The launcher sets `MADEIRA_MESA_POINT_XFB=1` with the experimental OpenGL path.
The fallback covers direct, non-indexed, single-instance point feedback with
rasterization discarded and scalar/vector 32-bit outputs, including texture
driven Godot skinning. General primitive, geometry/tessellation, indirect/indexed
feedback and stream-output statistics are not implemented by this fallback.
Unsupported feedback shapes are logged and skipped. Native D3D12 backends keep
their original stream-output path when the variable is off.

## Build and distribution

The IPA workflow builds this driver separately from the existing Wine/DXMT
caches. `build.py` verifies exact source archive SHA-256 hashes, disables all
other Gallium/Vulkan drivers, statically links the toolchain's C++ runtime,
checks PE imports/exports, and stages these files in `arm64ec-windows`:

- `opengl32-mesa.dll`: Mesa's replacement WGL/OpenGL entry points.
- `madeira-mesa-gl.dll`: Mesa's OpenGL frontend, NIR/DXIL compiler and D3D12 driver.
- `opengl-probe-x64.exe`: hidden-window OpenGL 3.3 rendering canary.

Patch inputs and outputs have pinned file hashes. Repeated builds accept only
the original or exactly patched source. The distribution manifest records patch
hashes, and both the recipe key and CI cache key include the patches.

With the verified LLVM-MinGW directory in `LLVM_MINGW`:

```sh
python3 -m venv build/mesa-d3d12/work/venv
build/mesa-d3d12/work/venv/bin/python -m pip install -r build/mesa-d3d12/requirements.txt
build/mesa-d3d12/work/venv/bin/python -B build/mesa-d3d12/build.py
```

The Windows-host recipe also requires win_flex and win_bison on PATH. The build
uses Mesa's own NIR-to-DXIL compiler, without LLVM libraries or downloaded
Microsoft binary redistributables. The native Windows D3D12 driver requires a
DXIL validator to sign generated shaders; a host-only validator was used in the
local canary test, and is not included in the IPA. Madeira's converter receives
DXIL directly; that behavior still needs a device test with this Mesa build.

Original component notices are copied into the IPA's `licenses/mesa-d3d12`.
The matching source companion contains both complete checksum-pinned upstream
archives under `source/dependencies`, plus these build recipes and patches.
The patches retain Mesa's MIT license. Mesa's source licenses, third-party
notices, DirectX-Headers' MIT grant and the statically
linked LLVM/MinGW runtime notices are retained;
iDeck's exception is not applied to those components.

## Enabling and checking

In game details, enable **OpenGL support (experimental)** and fully restart
iDeck. This immediately saves `opengl-d3d12 = 1` in the game's config. Turning
the switch off saves `0`, including when a global config enables the feature.
For Buckshot Roulette, keep the program selected and append
`--rendering-driver opengl3` in its Arguments field.

The launch creates prefix-only links for the 64-bit `opengl32.dll` and adds
`opengl32=n,b` to the existing Wine overrides. The 32-bit Steam launcher retains
its Wine DLLs. Every normal session setup restores the standard farm links
before applying this option, so disabling it and restarting restores the
previous path. No game files or registry settings are changed.

For a smaller device test, add `C:\windows\sysx64\opengl-probe-x64.exe` to the
library and enable the same switch for it. The canary tests repeated identical
pixel format selection, rejection of a different valid format, a 3.3 core context,
GLSL 330 compilation/linking, framebuffer clear and triangle draw readbacks,
window readback, and SwapBuffers. It also checks a data-only feedback shader
with a bone texture, normalized short inputs and mixed float/uint outputs;
nonzero input starts, target offsets, append/reset, overflow guards, and an
indexed draw consuming the generated vertices are checked by readback. Set
`MADEIRA_MESA_POINT_XFB=1` to test the fallback on a native Windows backend.
`[opengl-probe] PASS` is the success marker;
it rejects a software OpenGL renderer and reports the D3D12 adapter name.

Build 247 reached Mesa and created the Metal-backed D3D12 device on an iPad,
then failed at Mesa's shared submission fence: Madeira currently returns
`E_NOTIMPL` for shared fences. The private-fence fallback addresses this specific
initialization blocker. It does not establish successful device rendering.

Build 248 passed the fence stage but still failed to create Godot's OpenGL
window. A host reproduction of Godot's repeated pixel format setup failed
with that build's Mesa behavior and passes with the identical-format patch,
including subsequent GLSL rendering, readbacks and presentation. The device
failure did not include the WGL call result; the added diagnostics expose it.

Validation boundary: the Windows-host canary passed using Mesa's D3D12 renderer
on an NVIDIA GeForce RTX 4060 Laptop GPU. This validates Mesa/WGL/D3D12, not
the iPad's Metal path. Device rendering, game compatibility and sustained
performance remain unverified until the installed IPA is tested.

Build 249 starts Buckshot Roulette on an iPad, but its log contains three
void-returning vertex pipelines rejected by Metal and skipped draws. The user
reports stretched/missing 3D triangles while text remains readable. Godot's
skeleton shader and mesh storage code confirm this engine uses data-only point
feedback for skeleton/blend passes. Both the native stream-output path and the
new forced UAV fallback pass the expanded canary on the Windows D3D12 adapter.
This establishes the fallback's buffer and geometry behavior, not the game's
appearance on Metal or its frame rate; the new IPA still needs device testing.
