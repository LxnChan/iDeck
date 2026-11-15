# Steam initialization and crashhandler64.dll

Investigation: 2026-11-15. This is a compatibility workaround, not a repair of
Steam's reporting service or a claim that all Wine networking is correct.

## What the evidence establishes

The supplied failing traces show **successful loading** of `crashhandler64.dll`,
followed by a long wait. Renaming that DLL allowed the affected user to start a
game with both the previously working `bf40352` build and `97ec1cc`. This rules
out the simple explanation that only the newly synchronized runtime can fail;
it does not establish which external/persistent condition changed first.

The fixed official package already pinned in `SteamRuntime.swift` was inspected
in memory; no Valve binaries are stored in this repository. Its
`crashhandler64.dll` has SHA-256
`209d560ac43ce5dcf984c63d4ea41b64a0f6f4e42c53436a56be72c1f4e4cedf`,
image size `0x1af000`, and `.text` RVA/size `0x1000` / `0x54264`, matching the
image layout recorded in the failing trace. The installed DLL's SHA-256 was
not recorded, so layout agreement is not proof of byte-for-byte identity.

The matching instruction locations narrow the stall down substantially:

- The IPC thread's return address, DLL + `0x7643`, follows an infinite
  `WaitForSingleObject` on the report-completion semaphore. Immediately before
  waiting, it submits work through a different semaphore while holding a
  critical section. This is not the report worker's normal idle wait.
- The worker entry at + `0x63e0` processes the work and its callbacks before
  releasing that completion semaphore at + `0x64d4`.
- The other persistently waiting thread's return address, + `0x4d566`, follows
  the DLL's call to `HttpSendRequestW`. The trace also records a successful DNS
  lookup of `crash.steampowered.com`, followed by a port-443 connection attempt.

Together with the rename test, these observations strongly support a report
submission that does not finish, holding up Steam initialization. They do not
distinguish an unreachable/slow reporting endpoint or proxy path from a Wine
WinINet/socket completion problem. The connection line lacks the necessary
error and completion details; `ret=-1` alone is not a definitive failure cause.
**Network involvement cannot be excluded.** Nor is a wrapped global event
history evidence that the semaphore producer never ran.

An SDL3 load assertion precedes reporting, but the earlier successful Steam
session also logged an SDL3 loading error. That assertion alone therefore does
not explain the change from working to hanging. The first changed condition
and the underlying HTTP completion failure remain unproven.

## Workaround in Settings

Settings → Steam Client → **Disable crashhandler64.dll** is on by default.
It saves `env.MADEIRA_DISABLE_STEAM_CRASHHANDLER = 1` (off: `0`) in `madeira.cfg`.
The native loader reads the switch on each load attempt, rather than depending
on Wine's cached `WINEDLLOVERRIDES` parser. It refuses that exact DLL basename,
case-insensitively, including requests with absolute Windows paths.

The policy applies only to sessions launched through Steam/Dock. Ordinary Wine
Desktop sessions are unchanged. The setting is unavailable while Wine or its
server is running. Quit and reopen iDeck between comparisons: already-loaded
modules and existing sessions cannot be retroactively changed by the switch.
The historical RT223 diagnostic profile deliberately retains its old runtime;
it disables this unsupported switch and explains why.

No DLL is renamed, removed or replaced. Turning the switch off only removes
this policy: it cannot restore a manually renamed DLL or undo a separate
user-supplied Wine override. The disabled reporter can no longer submit reports
through this DLL, reducing diagnostic information available to Valve; it is
not a game renderer or a general fix for game crashes. Steam has been observed
to continue without it in the affected user's two builds, not tested universally.

## Minimal device confirmation

1. Restore a manually renamed `crashhandler64.dll` to its original name first.
   Keep the same app, prefix, account, game and network throughout the test.
2. With the switch on, restart iDeck and launch the affected game. Look for
   `[steam-crashhandler] blocked crashhandler64.dll; file preserved`.
3. Turn the switch off, restart and repeat. A load attempt should instead log
   `[steam-crashhandler] allowed by setting crashhandler64.dll; file preserved`.
   If the hang returns, record the duration and focused thread/network traces.
4. Turn it back on and repeat once more. A reproducible on/off/on result in the
   same build tests the new switch independently of the original rename test.

Do not clear the prefix, delete Steam configuration, log out, or redistribute
Valve binaries to perform this comparison. Host tests cover policy selection,
configuration wiring, metadata and UI structure; they cannot establish device
gameplay or whether a particular reporting request completes.
