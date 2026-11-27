# Desktop Shell folder fixes

The shared Wine Shell layer now preserves the background New Folder menu and
keeps recursive filesystem notifications from inserting descendant files into
the current folder's list. Explorer was the reproduction case; the fixes also
apply to callers using the same default Shell folder view and context menu.

## Root causes and changes

The background resource used small IDs for its View, Arrange Icons, and New
popups. The context-menu merger subtracts the Shell command base before adding
the caller's first command ID. This put those popups outside the allowed range,
so the merger discarded them. The resource IDs now use the same range as the
other Shell commands. Sort commands have distinct IDs, and numeric background
commands are translated back to the resource range before reaching the view.
This also makes the restored view-mode and sorting commands usable.

The default folder view subscribes to recursive notifications but previously
inserted each notification's final PIDL component without checking its parent.
Copying a folder therefore created the correct on-disk tree while its nested
files appeared as extra rows in the destination's list. Descendant deletions
and renames could also affect unrelated rows with the same final name.

The view now retains its normalized subscription PIDL and checks direct-child
membership before changing a row. It handles both endpoints of a rename or
move, respects the host's object filter, and avoids duplicate insertions and
invalid deletion indices. The notification router now checks both endpoints of
two-item events, allowing a destination subscriber to receive inbound moves.
Recursive delivery remains available to other subscribers. The paste target
buffer is also initialized with room for the double-null-terminated path list
required by `SHFileOperationW`.

These changes are a versioned LGPL Wine overlay in
`build/wine-pe/shell-folder-view.patch`. The ARM64EC/AArch64 runtime builder,
i386 builder, and individual PE module builder apply it idempotently. The Wine
submodule pin is unchanged. No application-name checks or external-drive path
exceptions are used.

## Validation

- Release regression suite: 123 tests run locally, with 112 passing and 11
  platform or dependency skips. The Shell tests compile extracted production notification
  handlers and command dispatch code with a small host shim.
- Before/after notification regression: the original code reproduces descendant
  insertion and missed inbound rename delivery. The overlay covers direct and
  nested creation, duplicate notifications, host filtering, same-name descendant
  deletion, rename, moves into and out of the view, and allocation failure.
- Command dispatch regression: icon modes, four sort columns, New Folder, and
  Paste are exercised using command offsets from multiple menu ID bases.
- Native Windows menu probe: the production background menu and extracted
  `Shell_MergeMenus` retain View, Arrange Icons, New Folder, and sorting at first
  command IDs 0, 1, and 256. Only the probe's separator syntax was adapted for
  LLVM's resource compiler.
- Native Windows PIDL/notification probe: direct rows are accepted; nested
  file and folder events are delivered recursively but do not add current-view
  rows. A nested copy retains its physical directory structure.

These host checks do not replace testing the resulting IPA on an iOS device.
Other applications using custom folder views or independent file managers are
outside this fix's demonstrated scope. Genuine existing destination files still
produce normal conflict prompts; the captured reproduction did not establish a
separate false-conflict defect in the copy engine.

## Recovery

The annotated checkpoint
`checkpoint/before-shell-folder-fixes-20261127-134744` was pushed before edits
and points to `596d45f7f2f30c2c5f19ba5636eb6920889e055d`.
Preexisting untracked local work was archived separately and verified before
editing. Private diagnostic captures and generated probe binaries are excluded
from the commit.
