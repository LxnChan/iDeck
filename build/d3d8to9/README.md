# Shared Direct3D 8 frontend

The i386 Wine D3D8 frontend uses WineD3D/OpenGL, which has no 32-bit renderer in
iDeck. Old engines can show a GDI splash and then fail adapter/context creation.
The IPA build now stages **d3d8to9 1.16.0** after every Wine/DXMT farm restore or
rebuild. All 32-bit applications using the system D3D8 DLL share this fix:

`application -> d3d8to9 -> existing D3D9 shim -> DXMT -> Metal`

The upstream BSD-2-Clause translation sources are unchanged. The recipe pins
their complete source archive and SHA-256, statically links the C++ runtime,
keeps Wine's `D3D8GetSWInfo` compatibility export, and verifies that the DLL
imports D3D9 without WineD3D/OpenGL. Wine supplies `d3dx9_43.dll`; the build does
not download Microsoft's DirectX redistributables. Original upstream notices
are in the IPA's `licenses/d3d8to9`, and the matching source companion contains
the exact upstream archive plus this build recipe and compatibility export.

Build using the verified LLVM-MinGW toolchain:

```sh
python3 -B build/d3d8to9/build.py --toolchain "$LLVM_MINGW"
```

The normal prefix setup refreshes syswow64 links every session, including a
64-bit launcher's 32-bit children. A game-supplied local D3D8 wrapper retains
its existing DLL search behavior; remove or replace it separately if needed.
This change does not supply 32-bit OpenGL or DirectDraw acceleration.

## Validation

Run `C:\windows\syswow64\d3d8-probe-x86.exe` on a device. It checks the five
legacy exports, adapter enumeration, device creation, a fixed-function triangle
and pixel readback. A host run exercises the same D3D8 translation against the
host's D3D9; it cannot validate DXMT/Metal on an iPad.

Ballance's `CKDX8Rasterizer.dll` is one reproduction: the supplied log loads
Wine D3D8, then fails GL context creation. Its `InterfaceControls.dll` and
`CK2UI.dll` also import **32-bit MFC42.DLL**, which is an independent missing
dependency. Supply an unmodified runtime obtained under Microsoft's terms to
the game's `Bin` directory or the prefix's `drive_c/windows/syswow64` directory.
For example, a local Windows installation may have the x86 DLL under
`C:\Windows\SysWOW64\mfc42.dll`. The x64 System32 DLL cannot serve a 32-bit
game. Do not commit or publish private runtime copies, game binaries or logs.

`tools/prepare-mfc42.py --source <x86-mfc42.dll> --dest <private-directory>
--requires <dependent-dll> ...` validates the architecture and required MFC42
exports, then copies the runtime byte-for-byte. It refuses to replace a
different existing DLL. The tool is application-independent and never fetches
Microsoft binaries or adds them to the IPA.

The original log also contains access violations after initialization fails.
Complete game compatibility requires a device retest with both dependencies
resolved; a successful build or host canary alone does not establish that.
