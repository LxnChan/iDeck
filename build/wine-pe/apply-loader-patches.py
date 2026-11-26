#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
"""Apply the versioned Wine PE loader overlay, preserving unrelated edits."""
from pathlib import Path
import subprocess
import sys


PATCH = Path(__file__).resolve().with_name("win32u-attach-order.patch")
PATCHES = (PATCH, PATCH.with_name("bounded-detach-probe.patch"))
WINE = PATCH.parents[2] / "wine"


def apply(wine=WINE):
    command = ["git", "-C", str(wine), "apply"]
    for patch in PATCHES:
        if subprocess.run(command + ["--reverse", "--check", str(patch)],
                          capture_output=True).returncode == 0:
            print(f"Wine PE loader overlay already applied: {patch.name}")
            continue
        subprocess.run(command + ["--check", str(patch)], check=True)
        subprocess.run(command + [str(patch)], check=True)
        print(f"Applied Wine PE loader overlay: {patch.name}")


if __name__ == "__main__":
    apply(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else WINE)
