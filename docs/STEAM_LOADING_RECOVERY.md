# Steam startup memory-read recovery

Recovery checkpoint: `checkpoint/20261126-steam-loading-memory-read-163156`
at `ecffb7215d987f81460c881ac8b5559c2c53d5fa`.

A reported startup stopped after loading the Steam client interfaces. During
thread exit, a TLS diagnostic read crossed into an inaccessible stack reservation.
Darwin delivered SIGBUS inside `NtReadVirtualMemory`. The SIGBUS path delivered a
guest exception without honoring the syscall's internal exception handler, leaving
its jump buffer installed. A subsequent protected operation asserted with
`0x80000101` and terminated the Dock host. The desktop remained alive and the host
had not written its final report, so the starting screen continued showing
"Loading Steam".

The shared SIGBUS path now uses the same syscall recovery as SIGSEGV. Protected
memory reads can return an error and clear their jump buffer. This applies to
other programs and protected syscall operations; no executable identity changes
the signal behavior. Faults outside a syscall retain guest exception delivery.
The Wine PE overlay also limits both thread-exit TLS diagnostic reads to the
owning heap allocation and the diagnostic buffer capacity.

The app can observe the exit of one designated process by its full UTF-16 image
path. The common runtime exit wrapper publishes its status before reclaiming
process mappings, including exits initiated by worker threads. A Dock session
watches its configured host path and shows an exit failure when no final report
exists. A final host report takes precedence. Other child processes do not affect
the watch; session reset clears it.

`tests/host/check-syscall-bus-recovery.py` applies the real loader overlays in a
temporary tree and compiles the production recovery, memory-read, diagnostic, and
process-watch functions. It exercises inaccessible source and destination pages,
repeated recovery, explicit SIGBUS, TLS allocation bounds, unrelated process
exits, clean exits, reset, and concurrent worker-thread reporting. The host signal
adapter models ARM64 context redirection; it does not execute the iOS dispatcher.
`tests/host/check-dock-start-screen.py` checks startup failure messages and final
report precedence using the production Swift rules.

The IPA workflow runs these checks and rebuilds both affected runtime caches.
Host regression checks and a successful IPA build do not establish a successful
Steam launch on the reporting iPad. Repeated device launches are still needed to
validate that original intermittent reproduction and normal game startup.
