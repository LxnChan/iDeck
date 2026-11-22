# On-demand legacy Windows runtimes

MFC42 is downloaded on the user's device, never by CI or into the IPA. The
launcher scans the selected installation's x86 PE imports and delay imports,
including plugins below conventional binary directories, and checks both
application-local and shared MFC42 exports. x64 imports do not trigger an x86
installation. Scans are bounded to 8192 directory entries, 512 PE files and
64 MiB of PE reads; optional plugins may reference a runtime even if a particular
launch does not use them. Confirmed late x86 loader failures are remembered for
the next launch, since this runtime requires an app restart between Wine sessions.

The first download shows the original supplemental Microsoft license and asks
the user to confirm acceptance and their authorization under the referenced
development-tool license. That confirmation is pinned to the package hash. This
is not a claim that downloading establishes rights for every platform or user.
The download uses only `download.microsoft.com` over HTTPS, including redirects,
and verifies the complete package's size and SHA-256. It can be cancelled or
retried, and a verified local cache is reused. An incompatible existing runtime
is reported instead of overwritten. Settings provides an alternative import of
a user-obtained x86 DLL, checked against the importing application's exports.

Source: Microsoft's signed `VC6RedistSetup_deu.exe`, an older VC6 package with
German system messages. The English endpoint is no longer available. The exact
URL, size and hash are in `LegacyRuntimeCore.swift`; the original supplemental
license is retained in `LegacyRuntime.swift`. The system DLL copied from a
Windows installation for private diagnosis is not this package's DLL, and is
not an input to the public build or on-device download.

The small source-built helper is staged in both the i386 and ARM64EC farms.
Inside the same Wine session as the original launch it:

1. Rehashes the downloaded archive, reads its nested cabinets with Wine's FDI,
   and extracts only `mfc42.dll` into bounded memory buffers.
2. Verifies the DLL's independent SHA-256 and writes it atomically to syswow64.
   Existing different files, directories and reparse points are retained.
3. Starts the original program only on success, preserving its arguments and
   exit status without an extra command shell. It never runs the old Microsoft
   installer or replaces Wine's MSVCRT, OLE or COM libraries.

The helper's `asInvoker` manifest avoids Windows installer-name elevation
heuristics; it needs only access to the user's Wine prefix. No registry changes
are necessary for this shared DLL. A pending install is retried on the next
launch if preparation was interrupted; the installed DLL is checked on reuse.

Build with `python3 -B build/legacy-runtime/build.py --toolchain <LLVM-MinGW>`.
The IPA synchronization manifest requires both helper architectures. The source
companion includes this recipe and helper source, with no Microsoft binaries.

## Validation

`tests/host/check-legacy-runtime.py --require-swift` compiles the production
scanner and runs generated PE fixtures: normal/delay/VA/ordinal imports,
dynamically discovered plugins, two unrelated applications, architecture
separation, shared runtime reuse, conflicting local DLLs and truncated files.

On Windows, `tests/host/check-legacy-runtime-installer.py --helper <x86-helper>
--package <user-downloaded-official-package> --compiler <i686-clang>` exercises
the production helper against the real package without downloading or publishing
it. This checks nested extraction, hashes, idempotence, conflict retention,
tampering, child argv/exit status and refusal to launch after installation failure.

Host checks do not validate Wine FDI/FEX on an iPad or full game compatibility.
Those require a device test, including a first download/consent, offline reuse,
cancel/retry and Ballance's plugin loading with MFC42 installed.
