#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Check a bundled Wine prefix template without extracting it.

This checks archive integrity, the three nonempty registry files loaded by
Wine, and the existing restriction on absolute build-host symlinks. It does
not validate registry keys or establish runtime/game compatibility.
"""
import argparse
import gzip
import tarfile
import zlib
from pathlib import Path, PurePosixPath


REGISTRY_FILES = {"system.reg", "user.reg", "userdef.reg"}
CHUNK_SIZE = 64 * 1024


def validate(path):
    """Return the number of checked members, or raise ValueError on failure."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"no such archive: {path}")

    registry_files = set()
    member_count = 0
    try:
        with gzip.open(path, "rb") as stream:
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                for member in archive:
                    member_count += 1
                    # Match PrefixExtractor.c: the generated archive's prefix/
                    # is stripped; archives with files directly at root also work.
                    name = member.name
                    if name.startswith("prefix/"):
                        name = name[7:]
                    name = PurePosixPath(name).as_posix()

                    if member.issym() and member.linkname.startswith("/"):
                        if not member.linkname.startswith(("/tmp/", "/var/", "/private/")):
                            raise ValueError(
                                f"absolute host symlink: {member.name} -> {member.linkname}"
                            )

                    # Read every declared payload, including tar padding required
                    # by the app's block-based extractor, rather than only listing.
                    stream.seek(member.offset_data)
                    remaining = (member.size + 511) // 512 * 512
                    while remaining:
                        data = stream.read(min(CHUNK_SIZE, remaining))
                        if not data:
                            raise ValueError(f"truncated tar member: {member.name}")
                        remaining -= len(data)

                    if name in REGISTRY_FILES and member.isfile():
                        if member.size > 0:
                            registry_files.add(name)
                        else:
                            # Later regular members overwrite earlier files when
                            # the app extracts the template.
                            registry_files.discard(name)

                # tarfile treats a bad header after a valid member as EOF. Reject
                # that case explicitly; the app accepts a zero block or clean EOF.
                stream.seek(archive.offset)
                ending = stream.read(512)
                if ending and ending != bytes(512):
                    raise ValueError("invalid or truncated tar header")

            # A tar reader can stop before the gzip trailer. Read through EOF to
            # verify the checksum/length and catch damage after the tar terminator.
            stream.seek(0)
            while stream.read(CHUNK_SIZE):
                pass
    except (OSError, EOFError, tarfile.TarError, zlib.error) as exc:
        raise ValueError(f"invalid gzip/tar archive: {exc}") from exc

    if member_count == 0:
        raise ValueError("empty tar archive")
    missing = REGISTRY_FILES - registry_files
    if missing:
        raise ValueError("missing nonempty regular registry file(s): " + ", ".join(sorted(missing)))
    return member_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path,
                        default=Path("app/Madeira/prefix-template.tar.gz"))
    args = parser.parse_args()
    try:
        count = validate(args.archive)
    except ValueError as exc:
        parser.exit(1, f"check-prefix-template: FAIL -- {exc}\n")
    print(f"check-prefix-template: OK -- {count} members; registry files and archive verified")


if __name__ == "__main__":
    main()
