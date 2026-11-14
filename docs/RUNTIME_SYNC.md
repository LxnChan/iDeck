# Runtime synchronization, 2026-11-13

The iOS forks are advanced together to the versions already selected by Madeira
at `fbad430410b4075192166172447c859714726de9`:

| Component | Previous pin | Selected pin | Existing commits |
| --- | --- | --- | --- |
| FEX | f59cab95659e8add0c88f0c76ec1cf483c536dbf | 1dc6ed4932bd231df1c53dd7b8043ffdee0ac34a | 24 |
| Wine (madeira-lgpl) | 9129e9684daaeae70da9435e7c6060e59392634e | ddf92babc5ba71f4586cc4713f5a8eb39f63d39b | 36 |
| DXMT | 128b297c6e9a00014408dc68b4c2c2373b5813de | 3d62913b75fb8b21ad6494f9d9f9853b19d9a014 | 30 |

The original snapshot record in `PROVENANCE.json` remains historical. These
updates preserve each component's license and authorship. No original FEX
implementation is generated for this synchronization.

## Sources and retained patches

- Madeira's three FEX build recipes, existing 16 KB SMC patch, LLVM 15.0.7
  bootstrap, LLVM-MinGW bootstrap and FreeType clean bootstrap are taken from
  the selected Madeira tree. The LLVM native target remains iOS 17.0 here.
- `build/fex-ios/fex-cpuid-bmi-fma.patch` is retained byte for byte. Its old
  base blob is obtained from the fixed previous FEX pin. Git three-way
  application preserves the newer independent AVX2 reporting; conflicts abort
  the build. This is an application of an existing patch, not a new FEX patch.
- `build/fex-patches/` records the existing Madeira SMC patch from
  `b0742a76d2a820638806786fc9bcd6644ff80f27`.
- Wine's TLS PE-write synchronization bridge and the FEX above-4-GB window
  protocol are imported from Madeira's existing native bridge implementation,
  including `eb0da2ea4244f0bc4df5067204b716ec2aff777f`. Local iDeck bridge changes
  remain in place.
- `build/dxmt-patches/` retains Madeira's existing D3D9 per-draw index-range
  patch. It is enabled by default; `MADEIRA_D3D9_INDEX_RANGE=0` restores whole
  buffer copying. The existing Xcode 27 atomic patch and Metal 3.1 target remain.

## Build and package contract

`Build iDeck IPA` now builds complete source-matched native FEX, Wine and DXMT,
and the ARM64EC/AArch64/i386 PE runtimes. AArch64 D3D9 and D3D10 core retain
their Wine owner; ARM64EC and i386 use the DXMT frontends. Third-party dependency
versions remain unchanged. Companion assets supply unchanged components such
as the prefix template, StikJIT, and the separate Madeira D3D12 runtime.

Caches match exact versioned build inputs, component pins, and Apple compiler /
SDK identities. They have no fallback restore keys. Generated trees and staged
companion binaries do not enter source-input hashes. `rebuild_fex=true` bypasses
the Windows and native runtime caches to force a fresh full runtime build.

`legal/runtime-sync.json` in the IPA records pins, patch hashes, native link
input hashes, and all packaged PE files in the three farms. The post-package
gate verifies required modules, PE architectures, the exact file set and bytes.
The artifact includes the IPA, package inventory and a copy of this manifest,
plus matching source and portable relink companion archives and checksums. The
relink command is executed against the actual link inputs before upload.
These checks establish build/package integrity, not game behavior on a device.
Wine foreground queries are paired with the existing Madeira op 3 bridge while
retaining iDeck focus rules. Optional XInput battery queries (op 4) keep their
unknown-battery fallback in this update.

The original FEX mainline, Wine mainline and DXMT mainline are not merged in
this update. DXMT's later upstream DXBC use-after-free fix is deferred to a
separate backport with its LGPL provenance and focused validation.

## Validation scope

Local verification covers release tests, the synthetic PE/archive package
checks, build-script syntax, and application / patch idempotence. The GitHub
Actions result is the source of truth for cross-compilation and IPA delivery.
Device validation of repeated game exits, Unity/Mono, WoW64 and D3D9/11 remains
pending; this Windows workspace has no available iOS test device session.

## CI integration repair, 2026-11-14

Run `43395096183` built the Windows runtime in 42m24s, then failed in the
native DXMT stage: the converter extracted from the companion IPA did not
match the original package SHA-256 required by `build/madeira-d3d12/deps.sh`.
`tools/build/stage-metal-converter.sh` now stages the original bytes from the
fixed Madeira revision above and checks that same SHA-256. The converter and
vendored headers are checked before expensive compilation.

Runtime commands live in `tools/build/build-{native,windows}-runtime.sh`.
Cache keys cover these recipes, their source inputs and component pins;
workflow scheduling and upload edits no longer discard runtime caches.
Windows-only recipes and native-only recipes have separate invalidation
boundaries. Native converter service sources and headers are now included in
the native key. Wine's configured headers and host tools have their own cache,
keyed by the Wine pin, toolchain recipe and Apple SDK/compiler identity.
The Windows farm key also includes the selected companion release, because
the farm retains externally owned D3D12 and driver modules from that IPA.

The shorter native build runs before Windows compilation to expose integration
errors earlier. Existing binary integrity, source/relink packaging and IPA
validation remain required. Cache keys have no broad fallback restore keys;
the first run of the new cache schema still requires a full build. A warm run
is needed to measure steady-state duration separately from that cold build.

Run `43561594583` completed the source runtime builds but exposed three missing
native bridge symbols at the application link. The selected Madeira tree's
`ios_atom_arg` and class-name normalization are now included in `class_ios.c`,
and its layer-keyed frame-time producer/reader is included in `Winios.m`.
`madeira_swap_overlay_stats` reports this bridge's real file-backed swap usage
and zero donor counters: the later donor allocator is not part of this sync.
No no-op frame hook, blanket undefined-symbol linker option, or FEX
implementation change is used to resolve these integration gaps.
