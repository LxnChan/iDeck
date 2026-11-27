#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
"""Apply shared Shell fixes without replacing unrelated Wine working-tree edits."""
from pathlib import Path
import subprocess
import sys


PATCH = Path(__file__).resolve().with_name("shell-folder-view.patch")
WINE = PATCH.parents[2] / "wine"


def apply(wine=WINE):
    command = ["git", "-C", str(wine), "apply"]
    if subprocess.run(command + ["--reverse", "--check", str(PATCH)],
                      capture_output=True).returncode == 0:
        print("Shared Shell overlay already applied")
        return
    subprocess.run(command + ["--check", str(PATCH)], check=True)
    subprocess.run(command + [str(PATCH)], check=True)
    print("Applied shared Shell folder-view overlay")


if __name__ == "__main__":
    apply(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else WINE)
