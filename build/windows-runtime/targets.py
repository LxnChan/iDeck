#!/usr/bin/env python3
"""Select installable Wine PE modules from the configured, pinned source tree.

Wine's generated Makefile decides which architectures/modules are supported.
Keep externally owned DLLs out of this build so a fresh Wine farm cannot replace
FEX, DXMT, Madeira D3D12, or the iOS display driver with upstream stand-ins.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

EXTERNAL = {
    "d3d11.dll", "dxgi.dll", "winemetal.dll",
    "d3d12.dll", "d3d12core.dll", "xtajit.dll", "xtajit64.dll", "wow64cpu.dll",
    "wineios.drv", "faultrep.dll", "wintypes.dll",
}
GUEST_GRAPHICS = {"d3d9.dll", "d3d10core.dll"}
UNSUPPORTED = {
    "winemac.drv", "wineandroid.drv", "winewayland.drv", "winex11.drv",
    "wineps.drv", "winevulkan.dll", "vulkan-1.dll", "opencl.dll", "wpcap.dll",
    "winevdm.exe", "vga.dll", "hal.dll", "w32skrnl.dll", "wow32.dll",
    "winemenubuilder.exe", "wineconsole.exe", "winedevice.exe", "ntoskrnl.exe",
    "ir50_32.dll", "aero.msstyles",
}
EXTENSIONS = {".dll", ".exe", ".drv", ".cpl", ".acm", ".ax", ".ocx", ".tlb", ".com"}


def targets(makefile: str, arch: str) -> list[str]:
    pattern = re.compile(
        rf"^((?:dlls|programs)/[^/]+/{re.escape(arch)}-windows/([^/\s:]+))\s*:",
        re.MULTILINE,
    )
    selected = set()
    for target, filename in pattern.findall(makefile):
        filename = filename.lower()
        if filename in EXTERNAL or filename in UNSUPPORTED:
            continue
        if arch != "aarch64" and filename in GUEST_GRAPHICS:
            continue
        if Path(filename).suffix not in EXTENSIONS:
            continue
        selected.add(target)
    return sorted(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makefile", type=Path, required=True)
    parser.add_argument("--arch", choices=("arm64ec", "aarch64", "i386"), required=True)
    args = parser.parse_args()
    selected = targets(args.makefile.read_text(), args.arch)
    if not selected:
        parser.error(f"no {args.arch} Wine PE targets in {args.makefile}")
    if args.arch != "i386" and not any(t.endswith("/ntdll.dll") for t in selected):
        parser.error(f"configured {args.arch} tree is missing ntdll.dll")
    print("\n".join(selected))


if __name__ == "__main__":
    main()
