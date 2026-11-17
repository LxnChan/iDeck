#!/usr/bin/env python3
"""Exercise the production launch-sync controller and transfer sequencing without Steam."""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--require-swift", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
app = root / "app/Madeira"
content = (app / "ContentView.swift").read_text(encoding="utf-8")
owned = (app / "SteamOwnedLibrary.swift").read_text(encoding="utf-8")
games = (app / "SteamGames.swift").read_text(encoding="utf-8")
library = (app / "Library.swift").read_text(encoding="utf-8")


def block(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


# Startup and playtime refresh never schedule a whole-library save sync.
for signature in ["func start()", "private func refreshIfStale()", "func refreshLibrary(", "func refreshPlaytime()"]:
    startup = block(owned, signature)
    assert not any(name in startup for name in ["syncCloud(", "syncInstalledCloudSaves(", "auditCloudSaves("])
assert "await syncInstalledCloudSaves()" in block(owned, "func cloudTurnedOn()")
assert "syncCloud(game.id, forceTransfers: true)" in block(owned, "func syncAllCloud()")

for signature in ["private func launchLibraryEntry(", "private func startDock("]:
    launch = block(content, signature)
    assert launch.index("cloudClear(") < launch.index("jitReadyForLaunch(")
    assert "cloudConfirmed || cloudClear(" in launch
    assert "cloudConfirmed: true" in launch
sheet = block(games, "struct SteamCloudLaunchSheet: View")
for label in ["Skip", "Retry", "Launch Anyway", "Cancel", "Choose which saves to keep"]:
    assert f'Button("{label}"' in sheet
assert ".interactiveDismissDisabled()" in sheet and "ProgressView(" in sheet
assert "onDismiss: cloudDismissed" in content

# A cancelled network request must not later place a save or commit an upload.
download = block(owned, "private func download(")
between_fetch_and_place = download[download.index("await cloudFile("):download.index("SteamCloudTransfer.place(")]
assert "try Task.checkCancellation()" in between_fetch_and_place
upload = block(owned, "private func upload(")
between_send_and_commit = upload[upload.index("await SteamCloudTransfer.send("):upload.index("var commit =")]
assert "try Task.checkCancellation()" in between_send_and_commit
print("PASS: no startup sync; sync precedes JIT; skip/retry UI and transfer cancellation checkpoints")

notice = block(library, "struct CloudNotice: Equatable")
hold = block(owned, "enum CloudHold: Equatable")
controller = "\n".join(block(content, signature).replace("private func ", "func ", 1) for signature in [
    "private func cloudClear(", "private func cloudNotice(", "private func cloudWait(",
    "private func finishCloudLaunch(", "private func cloudDismissed(",
])
source = r'''
import Foundation
@MainActor final class LibraryModel {
    var enabled = true
''' + notice + r'''
    var cloudNotice: CloudNotice?
    var cloudRetry: (() -> Void)?
}
@MainActor final class LogStore {
    static let shared = LogStore()
    func log(_ text: String) {}
}
enum SteamLog { static func event(_ text: String) {} }
@MainActor final class SteamOwnedLibrary {
    static let shared = SteamOwnedLibrary()
    static var cloudPlayCheck = true
''' + hold + r'''
    var signedIn = true
    var knownHold: CloudHold?
    var calls: [Int] = []
    var outcomes: [Int: CloudHold] = [:]
    var paused = false
    var waiting: [CheckedContinuation<Void, Never>] = []
    func cloudHold(_ appID: Int, offline: Bool = false) -> CloudHold? { knownHold }
    func settleCloud(_ appID: Int) async -> CloudHold? {
        calls.append(appID)
        let answer = outcomes[appID]
        // Intentionally ignore cancellation here, like a late CM response.
        if paused { await withCheckedContinuation { waiting.append($0) } }
        return answer
    }
}
@MainActor final class LaunchHarness {
    let library = LibraryModel()
    var cloudTask: Task<Void, Never>?
    var cloudAttempt: UUID?
    var cloudAfterDismiss: (() -> Void)?
    var cloudSheetPresented = true
''' + controller + r'''
}
@MainActor final class SyncHarness {
    static let cloudEnabled = true, cloudPlayCheck = true, cloudAutomatic = true
    static let cloudNoFolders = "no folders"
    static let cloudFresh: TimeInterval = 600
''' + hold + r'''
    var signedIn = true, inSession = false
    var cloudBusy = Set<Int>()
    var cloudWaitingFor: Int?
    var cloudWaitID: UUID?
    enum Phase { case ready, checking, downloading, uploading, failed(String) }
    struct State {
        var phase = Phase.ready
        var problem: String?
        var conflicts: [Int] = []
        var checked: Date?
    }
    struct Plan { var download: [Int] = []; var upload: [Int] = [] }
    var cloud: [Int: State] = [:]
    var plan = Plan()
    var checks: [Int] = [], downloads: [Int] = [], uploads: [Int] = []
    var failure: String?
    var pauseDownload = false
    var waiting: CheckedContinuation<Void, Never>?
    func checkCloud(_ appID: Int) async -> Plan? {
        checks.append(appID)
        if let failure { cloud[appID] = State(phase: .failed(failure)); return nil }
        cloud[appID] = State(checked: Date())
        return plan
    }
    func download(_ appID: Int, _ files: [Int]) async -> Bool {
        downloads.append(appID)
        if pauseDownload { await withCheckedContinuation { waiting = $0 } }
        return true
    }
    func upload(_ appID: Int, _ files: [Int]) async -> Bool { uploads.append(appID); return true }
''' + "\n".join(block(owned, signature) for signature in [
    "func syncCloud(", "func cloudHold(", "func settleCloud("
]) + r'''
}
@MainActor func spin(_ done: () -> Bool) async {
    for _ in 0..<10000 {
        if done() { return }
        await Task.yield()
    }
    preconditionFailure("Timed out waiting for a launch transition")
}
@main struct Checks {
    @MainActor static func main() async {
        let steam = SteamOwnedLibrary.shared
        let flow = LaunchHarness()
        var launches = 0
        func play(_ appID: Int = 42, offline: Bool = false) -> Bool {
            flow.cloudClear(appID, name: "Fixture", offline: offline) { launches += 1 }
        }
        // Only the selected game syncs, even when a previous check was fresh.
        assert(!play() && steam.calls.isEmpty && launches == 0)
        flow.cloudWait(42)
        await spin { flow.cloudTask == nil }
        assert(steam.calls == [42] && launches == 0 && flow.library.cloudNotice == nil)
        flow.cloudDismissed()
        flow.cloudDismissed()
        assert(launches == 1)
        assert(!play())
        flow.cloudWait(42)
        await spin { flow.cloudTask == nil }
        flow.cloudDismissed()
        assert(steam.calls == [42, 42] && launches == 2)

        // Failure waits for a choice; Retry performs a new sync of the same game.
        steam.outcomes[42] = .unchecked("offline")
        assert(!play())
        flow.cloudWait(42)
        await spin { flow.cloudTask == nil }
        assert(flow.library.cloudNotice?.kind == .unchecked && launches == 2)
        steam.outcomes[42] = nil
        flow.cloudWait(42)
        await spin { flow.cloudTask == nil }
        flow.cloudDismissed()
        assert(launches == 3 && steam.calls.suffix(2) == [42, 42])

        // Skip cancels the attempt and continues once, without waiting for CM.
        steam.paused = true
        steam.outcomes[43] = .unchecked("late failure")
        assert(!play(43))
        flow.cloudWait(43)
        await spin { steam.waiting.count == 1 }
        flow.finishCloudLaunch(launch: true)
        flow.cloudDismissed()
        assert(launches == 4)
        steam.waiting.removeFirst().resume()
        for _ in 0..<100 { await Task.yield() }
        assert(flow.library.cloudNotice == nil && launches == 4)

        // A cancelled old response cannot finish or overwrite the next launch.
        assert(!play(44))
        flow.cloudWait(44)
        await spin { steam.waiting.count == 1 }
        flow.finishCloudLaunch(launch: false)
        flow.cloudDismissed()
        assert(!play(45))
        flow.cloudWait(45)
        await spin { steam.waiting.count == 2 }
        steam.waiting.removeFirst().resume()
        for _ in 0..<100 { await Task.yield() }
        assert(flow.library.cloudNotice?.appID == 45 && flow.cloudTask != nil && launches == 4)
        steam.waiting.removeFirst().resume()
        await spin { flow.cloudTask == nil }
        flow.cloudDismissed()
        assert(launches == 5)

        // Launch Anyway after failure and Cancel after conflict keep their meaning.
        steam.paused = false
        assert(!play(43))
        flow.cloudWait(43)
        await spin { flow.cloudTask == nil }
        flow.finishCloudLaunch(launch: true)
        flow.cloudDismissed()
        assert(launches == 6)
        steam.outcomes[42] = .conflict(2)
        assert(!play())
        flow.cloudWait(42)
        await spin { flow.cloudTask == nil }
        assert(flow.library.cloudNotice?.kind == .conflict)
        flow.finishCloudLaunch(launch: false)
        flow.cloudDismissed()
        assert(launches == 6)
        steam.knownHold = nil
        assert(play(offline: true))
        steam.knownHold = .conflict(1)
        assert(!play(offline: true) && flow.library.cloudNotice?.kind == .conflict)
        flow.finishCloudLaunch(launch: false)
        steam.knownHold = .syncing
        let beforeOffline = steam.calls
        assert(!play(offline: true) && flow.library.cloudNotice?.kind == .unchecked)
        assert(steam.calls == beforeOffline) // Offline warnings do not open a connection.
        flow.finishCloudLaunch(launch: false)
        SteamOwnedLibrary.cloudPlayCheck = false
        assert(play())
        SteamOwnedLibrary.cloudPlayCheck = true
        print("PASS: real launch controller handles success, repeat Play, Retry, Skip, Cancel, late responses and offline")

        let sync = SyncHarness()
        sync.plan = .init(download: [1], upload: [2])
        let first = await sync.settleCloud(42)
        assert(first == nil)
        assert(sync.checks == [42, 42] && sync.downloads == [42] && sync.uploads == [42])
        assert(sync.cloudWaitingFor == nil && sync.cloudBusy.isEmpty)
        sync.failure = "network"
        let failed = await sync.settleCloud(43)
        assert(failed == .unchecked("network"))
        sync.failure = nil
        let retried = await sync.settleCloud(43)
        assert(retried == nil)

        // Cancellation while waiting for another sync exits without starting one.
        sync.cloudBusy.insert(44)
        let busy = Task { await sync.settleCloud(44) }
        await spin { sync.cloudWaitingFor == 44 }
        busy.cancel()
        _ = await busy.value
        assert(!sync.checks.contains(44) && sync.cloudWaitingFor == nil)

        // Skip during a download prevents subsequent upload/confirmation work.
        sync.pauseDownload = true
        let transfer = Task { await sync.settleCloud(45) }
        await spin { sync.waiting != nil }
        transfer.cancel()
        sync.waiting?.resume()
        _ = await transfer.value
        assert(!sync.uploads.contains(45) && sync.checks.filter { $0 == 45 }.count == 1)
        assert(!sync.cloudBusy.contains(45) && sync.cloudWaitingFor == nil)
        print("PASS: real sync methods retain bidirectional transfers, report failures, retry and stop on cancellation")
    }
}
'''
compiler = shutil.which("swiftc")
if not compiler:
    if args.require_swift:
        raise RuntimeError("swiftc is required for launch sync regression tests")
    print("SKIP: swiftc unavailable; compiled launch regression checks run in CI")
else:
    with tempfile.TemporaryDirectory(prefix="ideck-cloud-launch-") as temporary:
        directory = Path(temporary)
        path = directory / "launch.swift"
        path.write_text(source, encoding="utf-8")
        executable = directory / "launch"
        subprocess.run([compiler, "-parse-as-library", "-swift-version", "5", str(path),
                        "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True, timeout=30)
