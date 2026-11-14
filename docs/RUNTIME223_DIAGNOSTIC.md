# Build 223 runtime diagnostic

Opt in with `gh workflow run build-ipa.yml -f runtime_profile=build223`.
The default push/dispatch profile remains `synced`. The profiles have separate
concurrency groups; the historical profile never restores or saves synced caches.

This tests the Steam session regression after the upstream runtime sync. Desktop
and most Win32 programs still work; a successful CI build does not prove the
Steam session regression fixed.

The reference is the last known-good **pre-sync** build: Build 223, commit
`47dfc1f2d9c4acb40c8602751be90e1757f62a17`, Actions run `43383581817`, completed
November 13, 2026 at 15:16:30 Asia/Shanghai. If that artifact expires, the
diagnostic fails; it must not silently substitute a different runtime.

The current tracked Swift frontend is overlaid onto a separate checkout of that
commit. Its native Winios bridge, Xcode project, Wine/FEX headers and Wine native
patch build scripts stay at the historical version. Unexpected frontend resource
or project changes fail for review. Historical precompiled libraries come from
the exact SHA-256-pinned alpha.5 relink companion, as in the original build chain.
FEX implementation is not modified. PE farms, DXMT resources, prefix template
and other selected runtime resources are restored from the real Build 223 IPA;
the packaged file set and hashes must match. Native converter signatures may
change during packaging. Recompiled native code uses today's available Xcode/SDK,
so this is a build-chain reproduction, not a claim of identical native bytes.

The app is named `iDeck RT223`, with `runtime223` in its logged build stamp. The
default bundle identifier remains unchanged. Install using the same signing
identity without uninstalling the existing app; the build itself does not erase
the Wine prefix, games or account data. Keep a backup before any app replacement.
Try the same Steam library launch and export a fresh log, whether it succeeds or
still hangs. A recovery implicates the changed runtime combination but does not
isolate a particular Wine/FEX/DXMT commit. A failure also needs comparison with
the untouched original Build 223 IPA on the same existing device data.

Only the `iDeck-fork-<sha>` artifact is needed for installation. Separate source
and relink artifacts include the actual legacy source pins plus Swift changes,
hash-verified original companion source/licenses, the diagnostic tooling, and
actual link inputs. The runtime manifest records source/toolchain provenance and
the unchanged precompiled inputs; it never labels this package source-matched to
the newer synced runtime. Artifacts currently retain the workflow's 14-day limit.
