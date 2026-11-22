# External game storage

iDeck can map a user-selected writable directory on a connected local drive to
`C:\External\<folder-id>`. The game data remains on that drive; this does not pool
the internal and external filesystems or enlarge the reported C: root capacity.
Windows system files and Windows user folders remain in the existing prefix.

## Use

1. Open Settings > Storage > External storage and add a directory using Files.
2. Setup verifies directory permissions and a complete create/write/read/rename/
   delete probe before accepting it. It creates a small `.ideck-storage-id` file
   to distinguish the selected directory from another at the same pathname.
3. Add ordinary games through the existing program browser under
   `drive_c/External/<folder-id>`. A Steam library uses `steamapps` directly below
   the selected directory. Existing Steam manifests are discovered there.
4. Choose the global default for new Steam downloads in External storage
   settings. Each game's install page also offers a location for that download
   only, including internal storage and connected writable external folders.
   Choosing it does not change the global default; Use default follows the
   current setting until Install is pressed. The selected target is then pinned
   across queues, pauses and app restarts. Updates, repairs and unfinished
   downloads retain their original location. Cancel a new install to remove its
   partial data before choosing a different target. There is no fallback to
   internal storage when an external target is unavailable.
5. Stop games, downloads and save synchronization, then use Safely disconnect
   before unplugging. Reconnect uses the saved directory authorization; if iOS
   revokes it, select the original folder again to preserve its game paths.

Removing a mapping preserves external files. Re-adding the original folder
restores the same mapping ID. Automatic migration of existing internal installs
is outside this change; no existing game directory is moved during setup.

## Behavior and boundaries

- Security-scoped access remains active while the directory is connected. A
  bookmark and identity file are checked after reconnection. No raw device path,
  drive label, executable name, or application name substitutes for permission.
- Directory events and a 1.5-second foreground poll refresh availability. Startup,
  return to foreground, game launch and install also check access. iOS suspension
  prevents continuous background polling; foreground entry requests a new check.
- Unavailable games retain their cached install records, artwork and profiles;
  cards become gray and Play is disabled. A failed library scan preserves its
  cache instead of treating the drive as uninstalled. Launch checks repeat after
  JIT and Steam connection waits.
- Ordinary paths keep their existing containment rules. Only registered mapping
  links can leave `drive_c`; nested escaping links, replaced mapping links and
  parent traversal are rejected. Reset/system-file protections remain scoped to
  the original prefix.
- Steam's library configuration is extended before its client starts. Existing
  entries and comments are preserved, with an original-file backup named
  `libraryfolders.vdf.ideck-before-external`. Download location, repair, removal
  and available-space reporting use the actual library.
- Steam Cloud checks availability before scanning, accepting a scan, and placing
  external save files. An unavailable drive is an access failure, not evidence
  that saves were deleted. Existing saves next to a game require its drive.
- Physical removal during active writes or mapped-file access can still fail the
  running game and lose unflushed writes. This feature cannot safely resume such
  a game or guarantee recovery from power loss. It never restarts it automatically.

## Interrupted downloads

Directory revoke/delete/rename events immediately request cancellation of active
downloads on that mapping and remove its queued and automatic-resume work. The
foreground 1.5-second poll and checks at each chunk boundary cover missing events;
OS event delivery and cancellation are cooperative, not hard real-time guarantees.
A foreground Steam alert explains the stop; background failure notifications use
the existing notification setting and system permission.

Before changing game files, external installs save a recovery description in
internal app support storage: library identity, relative paths, sizes and public
chunk hashes. It contains no account credentials or depot keys. Pending external
installs survive app restarts. Reconnecting the original writable folder starts
an offline checksum audit, one install at a time, while downloads remain stopped.
The download status reports intact and missing/damaged blocks. The audit preserves
game files; Resume downloads and replaces only blocks that fail verification.
Missing/corrupt recovery metadata falls back to verification against Steam on
Resume. Cancelling a new install removes its partial files through the existing
managed-library containment checks; cancelling an update preserves the install.

The shared downloader also verifies chunks claimed complete by a resume journal.
A journal entry alone no longer proves its corresponding data survived a disk
removal. The same rule protects internal downloads after crashes or interrupted
writes. Filesystem write errors stop the install instead of retrying content
servers. Checks and cancellation repeat after network waits and before writes.

## Validation

`python3 -B tests/host/check-external-storage.py --require-swift` executes the
production path resolver, identity/read-write probe and Steam configuration
registration against synthetic temporary folders, real symlinks and permissions.
It also checks shared install/removal containment and download journal recovery.
`check-download-recovery.py --require-swift` exercises per-download location
selection and persistent pins independently of the global default, the production
disconnect policy, persisted recovery audit, journal revalidation and chunk
request/write code with corrupted/truncated files and a real local in-flight HTTP
cancellation. It checks that updates/resumes keep their target and unavailable
selections never fall back to another drive.
The build workflow also runs the existing Steam game discovery, Dock contract,
legacy runtime, launch and Cloud checks, then builds and packages the app.

Hardware acceptance remains necessary on iPhone/iPad: Files directory selection,
persistent authorization after force-quit/reboot, writable and read-only media,
unplug/reinsert, directory rename/removal, insufficient space, gameplay and save
access, download interruption/resume, and external game startup through both
direct Wine launch and Steam. Include internal games as controls. Host tests and
a successful IPA build do not establish hardware compatibility.
