# Steam Cloud saves

Madeira syncs the save files of installed Steam games with the signed-in
account's Steam Cloud. It uses the app's own Steam connection (the one the
library and downloads use, `docs/STEAM_LIBRARY.md`), which is closed
while a game session holds the account: saves sync before the selected game
starts or through the manual controls, and during a session only on the
game menu's upload button.

It is on by default. **Settings › Steam Cloud saves** turns it off, which
keeps `env.MADEIRA_STEAM_CLOUD = 0` in `madeira.cfg`; turning it back on
syncs the installed games at once.
`env.MADEIRA_STEAM_CLOUD_AUTO = 0` keeps the comparison and the game page
but copies nothing in either direction unless the user asks there.

## When it runs

- Before an online game launch, for that selected Steam game only. Opening
  iDeck or returning from the background does not start a whole-library sync.
- On **Settings › Steam › Sync all Steam Cloud saves**, for every installed
  Steam game. This explicit sync copies safe one-sided changes even when
  `env.MADEIRA_STEAM_CLOUD_AUTO = 0`; saves that differ on both sides still
  wait for a choice on the game's details page.
- When a Steam game's details page has no sync state yet in this app run,
  and on its **Sync now** button.

- On **Upload saves and close Madeira** in the game menu of a running Steam
  game.

Madeira cannot close a game: the user leaves one by quitting the app. So
there is no sync at exit. What was played is uploaded at the next sync of
that game: its next online launch, its details page, the Settings sync
button, or the game menu's upload button.

The button works while the game still runs. Madeira's own Steam connection
is closed for a session, because a second logon replaces the first; the
button logs Madeira on again, which ends the logon of Valve's client in the
session, and the app quits once the upload is confirmed. It only uploads:
files that changed on this device and not in the cloud. It waits until two
looks 2 s apart find the same device files, since the game may be writing.
A file that also changed in the cloud is not sent without the user choosing
to replace the cloud's copy; that conflict keeps the app open for the choice.
The action is a square tile at the top of the session menu. A confirmed upload
turns it green; an upload failure (including no network) turns it orange and
shows **Saved locally**. Both results stay visible for 2.5 s before the app
quits. Upload failure leaves the device's existing save files in their original
folders. The next online launch of that game retries through the same fresh
comparison, upload/download and conflict-choice flow described below. It uses
the local files and sync baseline already on disk, so it needs no separate
upload queue or forced overwrite. An offline launch or a skipped/disabled sync
continues using the local saves until a later sync.
`env.MADEIRA_STEAM_CLOUD_QUIT = 0` hides the button.

## Before a game starts

Play syncs the selected game's saves first (`env.MADEIRA_STEAM_CLOUD_PLAY_CHECK = 0`
turns this off):

- Each online Play starts a fresh sync of that game, even if it was checked
  recently. A progress sheet offers **Skip** and **Cancel**.
- Success dismisses the sheet, then continues through the normal JIT request
  and game launch. That continuation does not sync again after JIT returns.
- **Skip** cancels this sync attempt and continues with this device's saves.
  A cancelled request cannot later write a downloaded save or start the game
  a second time. Files already written remain intact.
- Failure (no network, for example) offers **Retry**, **Launch Anyway**, and
  **Cancel**. Retry syncs the same selected game again.
- Saves waiting for a choice also offer **Choose which saves to keep**, which
  opens the game's details page. No conflict is overwritten automatically.
- Explicit **Launch offline** retains its existing behavior: no online
  freshness check, while already-known conflicts/transfers still ask first.

The Cloud decision applies to this launch only. A later Play starts a new
sync. Each downloaded file is written whole.

## What it does

1. Asks Steam for the app's cloud file list (`Cloud.GetAppFileChangelist`).
2. Maps each cloud path to a file of Madeira Dock's Wine prefix, through
   the `%Root%` placeholder of the path and the app's `ufs` product info:
   `GameInstall` is the game's folder, `WinAppDataLocalLow` and its
   siblings are under the Windows user folder (the one Wine names after
   `$USER`), and a path with no placeholder is under Steam's
   `userdata/<account>/<app>/remote`. Names are matched without regard to
   case. A path that would leave its folder is refused.
3. Compares SHA-1 and size, and also lists files matching the app's save
   patterns that the cloud does not have.
4. Looks each file up in its record of what was last identical on both
   sides (`steam-cloud-sync.json` in Application Support):
   - changed on one side only, or new on one side: copied to the other;
   - changed on both, or different with no record: **left alone**. The
     library names the games, and the game's page shows each such
     save with both dates and sizes and asks which side to keep;
   - synced before and now missing on this device while the cloud still has
     it (a reset prefix, or the game deleted it): **a choice**, like a save
     that changed on both sides, and Play waits for it. Keeping the cloud's
     copy downloads it; keeping this device's state leaves it missing, which
     is recorded and not asked again unless the cloud's copy changes. Until
     the choice, a save of that name that appears on the device is a choice
     too, never uploaded over the cloud's copy unasked;
   - synced before and now missing in the cloud (deleted elsewhere): left
     alone, not sent back.

## Safety

- A downloaded file is checked against the SHA-1 in Steam's list before
  anything is written.
- Backups are kept where the Files app shows them, in
  `Madeira/Steam Cloud Backups/<game> (<App ID>)/<time>/`:
  - `device/` holds each device file a download replaced;
  - `cloud/` holds each cloud file an upload replaced. Steam keeps no copy
    of those, so Madeira downloads the cloud's copy (checked against its
    SHA-1) before the upload starts; if it cannot, nothing is uploaded.
- An upload over a differing cloud file only happens on the user's choice or
  when the record shows the cloud copy is the one this device last synced.
- Nothing is ever deleted in the cloud.

## Limits

- No download while a game runs, and no upload during play except by the
  menu button. Skipping the launch sync uses this device's existing saves;
  changes on both devices may require a choice at a later sync.
- A game whose Windows saves are redirected by a `rootoverrides` entry for
  Windows is compared and downloaded, but new device files there are not
  uploaded.
- Encrypted cloud files are not supported.
- Log tag `[steam-cloud]`: App IDs, counts and results; no file names or paths.
