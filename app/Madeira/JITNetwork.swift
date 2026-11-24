// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
// Getting this device's own network path ready for JIT (docs/JIT.md).
//
// Built-in StikJIT and StikDebug reach this device's lockdownd through
// LocalDevVPN's loopback, which works on Wi-Fi or with no network at all but
// not over cellular data. Enable JIT first checks the loopback directly
// (LoopbackProbe, milliseconds when it works). Only when that fails, and the
// Madeira JIT shortcut is turned on, does Madeira run the shortcut to turn
// Cellular Data off (when there is no Wi-Fi) and connect LocalDevVPN; once a
// game's JIT pool is mapped and the debugger has left, it runs it again to put
// both back. Log tags: [jit-loopback], [jit-shortcut].

import Darwin
import Foundation
import Network
import UIKit

/// Whether LocalDevVPN's loopback reaches this device's lockdownd at 10.7.0.1:62078
/// (the address StikDebug uses). The established LocalDevVPN transport is probed
/// with TCP; alternative VPN routes must identify the lockdownd service:
/// 1. The route: the interface traffic to 10.7.0.1 would leave by, asked of the kernel
///    with an unsent UDP connect (no packets, microseconds). Not a VPN interface means
///    LocalDevVPN is not routing it, so a network that accepts any connection (a proxy;
///    the 18 Pro's Wi-Fi has one) is never asked.
///    Other VPNs can provide the same service. On those routes, verify a framed
///    lockdownd QueryType reply so a catch-all proxy accepting TCP is insufficient.
/// 2. Through the tunnel: a TCP connection, at most `timeout`. Through a working
///    tunnel it opens in milliseconds; over cellular data, where the tunnel does not
///    work, it fails. Only alternative routes receive a QueryType request.
enum LoopbackProbe {
    static let address = "10.7.0.1"
    static let port: UInt16 = 62078

    struct Result {
        let reachable: Bool
        let milliseconds: Double
        let detail: String
    }

    struct Route {
        let interface: String
        let address: String
        /// utun (packet tunnels such as LocalDevVPN), ipsec or ppp.
        var isVPN: Bool { ["utun", "ipsec", "ppp"].contains { interface.hasPrefix($0) } }
        /// LocalDevVPN's own tunnel: a VPN interface whose address is in its 10.7.0.0/16.
        var isLocalDevVPN: Bool { isVPN && address.hasPrefix("10.7.") }
    }

    private static func target() -> sockaddr_in? {
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        return inet_pton(AF_INET, address, &addr.sin_addr) == 1 ? addr : nil
    }

    private static func connect(_ fd: Int32, _ addr: inout sockaddr_in) -> Int32 {
        withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
    }

    /// The interface and local address traffic to 10.7.0.1 would leave by; nil without a route.
    static func route() -> Route? {
        guard var addr = target() else { return nil }
        let fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return nil }
        defer { close(fd) }
        guard connect(fd, &addr) == 0 else { return nil }
        var local = sockaddr_in()
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let got = withUnsafeMutablePointer(to: &local) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &len) }
        }
        guard got == 0 else { return nil }
        var text = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
        var sin = local.sin_addr
        inet_ntop(AF_INET, &sin, &text, socklen_t(INET_ADDRSTRLEN))
        return Route(interface: interfaceName(holding: local.sin_addr.s_addr) ?? "?", address: String(cString: text))
    }

    private static func interfaceName(holding ip: in_addr_t) -> String? {
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return nil }
        defer { freeifaddrs(list) }
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let entry = cursor {
            if let sa = entry.pointee.ifa_addr, sa.pointee.sa_family == sa_family_t(AF_INET),
               sa.withMemoryRebound(to: sockaddr_in.self, capacity: 1, { $0.pointee.sin_addr.s_addr }) == ip {
                return String(cString: entry.pointee.ifa_name)
            }
            cursor = entry.pointee.ifa_next
        }
        return nil
    }

    /// Blocks for at most `timeout`; use `check(timeout:completion:)` from the main thread.
    /// `requireVPN` is false only for host tests, whose listeners are on lo0.
    static func check(timeout: TimeInterval = 0.4, requireVPN: Bool = true) -> Result {
        let start = CFAbsoluteTimeGetCurrent()
        func done(_ ok: Bool, _ detail: String) -> Result {
            Result(reachable: ok, milliseconds: (CFAbsoluteTimeGetCurrent() - start) * 1000, detail: detail)
        }
        guard let route = route() else { return done(false, "no route") }
        if requireVPN, !route.isVPN { return done(false, "routed via \(route.interface), not a VPN") }
        guard var addr = target() else { return done(false, "bad address") }
        let fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)
        guard fd >= 0 else { return done(false, "socket: \(String(cString: strerror(errno)))") }
        defer { close(fd) }
        var one: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size))
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK)
        if connect(fd, &addr) != 0 {
            guard errno == EINPROGRESS else { return done(false, String(cString: strerror(errno))) }
            var pfd = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
            let ready = poll(&pfd, 1, Int32(max(1, (start + timeout - CFAbsoluteTimeGetCurrent()) * 1000)))
            guard ready > 0 else { return done(false, ready == 0 ? "timed out via \(route.interface)" : String(cString: strerror(errno))) }
            var err: Int32 = 0
            var len = socklen_t(MemoryLayout<Int32>.size)
            getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len)
            guard err == 0 else { return done(false, "\(String(cString: strerror(err))) via \(route.interface)") }
        }
        // The established LocalDevVPN transport closes plain QueryType requests.
        // Keep its connect probe, but positively identify the service on other VPNs.
        if !route.isLocalDevVPN {
            guard queryLockdown(fd, deadline: start + timeout) else {
                return done(false, "lockdownd did not answer via \(route.interface)")
            }
        }
        return done(true, "connected via \(route.interface) \(route.address)")
    }

    private static func queryLockdown(_ fd: Int32, deadline: CFAbsoluteTime) -> Bool {
        guard let payload = try? PropertyListSerialization.data(
            fromPropertyList: ["Request": "QueryType", "Label": "iDeck"], format: .xml, options: 0) else { return false }
        var length = UInt32(payload.count).bigEndian
        var request = withUnsafeBytes(of: &length) { Data($0) }
        request.append(payload)
        func ready(_ event: Int16) -> Bool {
            let remaining = deadline - CFAbsoluteTimeGetCurrent()
            guard remaining > 0 else { return false }
            var pfd = pollfd(fd: fd, events: event, revents: 0)
            return poll(&pfd, 1, Int32(max(1, remaining * 1000))) > 0 && pfd.revents & event != 0
        }
        var sent = 0
        while sent < request.count {
            guard ready(Int16(POLLOUT)) else { return false }
            let count = request.withUnsafeBytes { Darwin.send(fd, $0.baseAddress!.advanced(by: sent), request.count - sent, 0) }
            if count < 0 && (errno == EAGAIN || errno == EINTR) { continue }
            guard count > 0 else { return false }
            sent += count
        }
        func read(_ size: Int) -> Data? {
            var bytes = [UInt8](repeating: 0, count: size)
            var received = 0
            while received < size {
                guard ready(Int16(POLLIN)) else { return nil }
                let count = bytes.withUnsafeMutableBytes { Darwin.recv(fd, $0.baseAddress!.advanced(by: received), size - received, 0) }
                if count < 0 && (errno == EAGAIN || errno == EINTR) { continue }
                guard count > 0 else { return nil }
                received += count
            }
            return Data(bytes)
        }
        guard let header = read(4) else { return false }
        let size = header.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
        guard size > 0, size <= 64 * 1024, let response = read(Int(size)),
              let plist = try? PropertyListSerialization.propertyList(from: response, options: [], format: nil),
              let reply = plist as? [String: Any] else { return false }
        return reply["Type"] as? String == "com.apple.mobile.lockdown"
    }

    static func check(timeout: TimeInterval = 0.4, completion: @escaping @MainActor (Result) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = check(timeout: timeout)
            DispatchQueue.main.async { MainActor.assumeIsolated { completion(result) } }
        }
    }

    /// Checks again until the loopback answers or `within` seconds pass: a VPN that
    /// was just connected needs a moment before it routes.
    static func waitUntilReachable(within: TimeInterval, completion: @escaping @MainActor (Result) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let deadline = CFAbsoluteTimeGetCurrent() + within
            var result = check(timeout: 0.4)
            while !result.reachable, CFAbsoluteTimeGetCurrent() < deadline {
                Thread.sleep(forTimeInterval: 0.25)
                result = check(timeout: 0.4)
            }
            let final = result
            DispatchQueue.main.async { MainActor.assumeIsolated { completion(final) } }
        }
    }

    /// LocalDevVPN is connected: traffic to 10.7.0.1 leaves by its tunnel. Instant: no
    /// network traffic.
    static var vpnInterfaceUp: Bool { route()?.isLocalDevVPN ?? false }
}

/// On each Madeira launch, make sure LocalDevVPN is ready before the user starts a
/// JIT-dependent session. The connection URL returns to Madeira through its declared
/// callback scheme; becoming active again is the reliable signal to wait for the
/// tunnel, because LocalDevVPN can return before its route is usable.
@MainActor final class LocalDevVPNLaunchCoordinator {
    static let shared = LocalDevVPNLaunchCoordinator()

    private enum State { case idle, checking, waitingUntilActive, waitingForReturn, verifying, finished }
    private var state: State = .idle
    private var activeObserver: NSObjectProtocol?

    private init() {}

    func start() {
        guard state == .idle else { return }
        activeObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.becameActive() }
        }
        check()
    }

    private func check() {
        guard !StikJITHelper.ready else { finish("JIT is already ready"); return }
        state = .checking
        LogStore.shared.log("[jit] checking LocalDevVPN at launch")
        LoopbackProbe.check { [weak self] result in
            guard let self, self.state == .checking else { return }
            guard !StikJITHelper.ready else { self.finish("JIT is already ready"); return }
            if result.reachable {
                self.finish("already reachable (\(result.detail))")
                return
            }
            guard LocalDevVPN.isInstalled else {
                self.finish("not installed; leaving setup to onboarding", error: true)
                return
            }
            guard UIApplication.shared.applicationState == .active else {
                self.state = .waitingUntilActive
                LogStore.shared.log("[jit] LocalDevVPN launch check is waiting for Madeira to become active")
                return
            }
            self.state = .waitingForReturn
            LogStore.shared.log("[jit] LocalDevVPN is not reachable at launch (\(result.detail)); opening it")
            UIApplication.shared.open(LocalDevVPN.connect) { [weak self] opened in
                guard !opened else { return }
                MainActor.assumeIsolated { self?.finish("could not be opened", error: true) }
            }
        }
    }

    private func becameActive() {
        if state == .waitingUntilActive {
            check()
            return
        }
        guard state == .waitingForReturn else { return }
        state = .verifying
        LogStore.shared.log("[jit] returned from LocalDevVPN; waiting for its tunnel")
        LoopbackProbe.waitUntilReachable(within: 15) { [weak self] result in
            guard let self, self.state == .verifying else { return }
            self.finish(result.reachable ? "tunnel ready (\(result.detail))" : "tunnel did not become reachable (\(result.detail))",
                        error: !result.reachable)
        }
    }

    private func finish(_ detail: String, error: Bool = false) {
        guard state != .finished else { return }
        state = .finished
        if let activeObserver {
            NotificationCenter.default.removeObserver(activeObserver)
            self.activeObserver = nil
        }
        LogStore.shared.log("[jit] launch LocalDevVPN check: \(detail)", level: error ? .error : .info)
    }
}

/// The signed bundled shortcut is the import source. Share it to Shortcuts,
/// replacing the older Madeira JIT workflow. Do not offer the historical
/// iCloud workflow: it returns a VPN content object instead of explicit text.
/// Editable source: tools/shortcuts/Madeira JIT.plist; sign with Apple's CLI.
/// iOS 27 and later: Store Content preserves the previous VPN in Shortcuts.
enum JITShortcutFile {
    static var url: URL? { Bundle.main.url(forResource: "Madeira JIT", withExtension: "shortcut") }
    static var supported: Bool {
        ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: 27, minorVersion: 0, patchVersion: 0))
    }
}

/// The user's "Madeira JIT" shortcut (docs/JIT.md has its steps). Input "start",
/// with "cellular" when Madeira sees cellular data and no Wi-Fi: keep the VPN that is
/// connected (Get Current VPN into Store Content; iOS connects one VPN at a time, so
/// LocalDevVPN replaces it), turn Cellular Data off (only when asked), connect
/// LocalDevVPN, and output that VPN, which tells Madeira whether one was on. Input
/// "done", with "cellular" when "start" had it: turn Cellular Data back on; "vpn-off":
/// disconnect LocalDevVPN (no VPN was on); "vpn-restore": connect the kept VPN again.
/// Only Store Content keeps a VPN that Set VPN accepts: as text (a file, or a name
/// Madeira passed back) it is only a name, which Set VPN cannot convert ("couldn't
/// convert from Text to VPN"). Madeira runs "done" after any "start".
///
/// An app can only run a shortcut by opening the Shortcuts app, so each run leaves
/// Madeira for a moment and comes back through x-callback-url
/// (madeira://jit-network/...). Off unless Settings › JIT › Madeira JIT shortcut
/// turns it on (madeira.cfg env.MADEIRA_JIT_SHORTCUT = 1): without the shortcut the
/// Shortcuts app would only report that it is missing.
@MainActor final class JITNetworkShortcut: ObservableObject {
    static let shared = JITNetworkShortcut()
    static let name = "Madeira JIT"

    /// Settings › JIT › Madeira JIT shortcut: when LocalDevVPN's loopback does not answer,
    /// Enable JIT runs the shortcut. Off unless it is 1.
    @Published var enabled = MadeiraConfig.flag("MADEIRA_JIT_SHORTCUT", fallback: false) {
        didSet {
            guard enabled != oldValue else { return }
            MadeiraConfig.set("env.MADEIRA_JIT_SHORTCUT", enabled ? "1" : nil)
            LogStore.shared.log("[jit-shortcut] setting on=\(enabled ? 1 : 0)")
        }
    }

    enum Outcome { case done(String), failed(String) }

    /// Cellular data is carrying traffic and there is no Wi-Fi: the case LocalDevVPN's
    /// loopback cannot work in. From the system's network path, kept current.
    var cellularOnly: Bool {
        let path = monitor.currentPath
        return path.status == .satisfied && path.usesInterfaceType(.cellular) && !path.usesInterfaceType(.wifi)
    }
    private let monitor = NWPathMonitor()

    private init() {
        monitor.start(queue: DispatchQueue(label: "madeira.jit-network.path"))
    }

    /// The "done" input owed since a "start" (see above); nil when none. Kept on disk, so
    /// a run that ends between them (Madeira closed or crashed) is put back at the next
    /// launch. Main thread.
    private static let pendingKey = "madeiraJITShortcutPendingDone"
    private var pending: String? {
        get { UserDefaults.standard.string(forKey: Self.pendingKey) }
        set { UserDefaults.standard.set(newValue, forKey: Self.pendingKey) }
    }
    private var waiting: ((Outcome) -> Void)?
    private var timeout: Timer?

    /// Runs "start". Pending from before it runs: even a "start" that fails part-way may
    /// have changed something.
    func start(completion: @escaping (Outcome) -> Void) {
        let cellular = cellularOnly
        let base = cellular ? "done cellular" : "done"
        // LocalDevVPN already connected (its tunnel just does not work over cellular
        // data): "done" leaves it. Until "start" reports the VPN, "done" leaves VPNs alone.
        let localDevVPNWasUp = LoopbackProbe.vpnInterfaceUp
        pending = base
        run(cellular ? "start cellular" : "start") { [weak self] outcome in
            if case .done(let output) = outcome, !localDevVPNWasUp {
                let vpnWasOn = !output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                self?.pending = base + (vpnWasOn ? " vpn-restore" : " vpn-off")
            }
            completion(outcome)
        }
    }

    /// Runs "done" when "start" ran since the last "done", then calls `completion`.
    func restoreIfNeeded(completion: @escaping () -> Void) {
        guard let input = pending else { completion(); return }
        pending = nil
        run(input) { _ in completion() }
    }

    /// At launch: a run that ended between "start" and "done" left the device without
    /// cellular data or its VPN; put them back.
    func restoreLeftover(completion: @escaping () -> Void = {}) {
        guard pending != nil, enabled else { completion(); return }
        LogStore.shared.log("[jit-shortcut] an earlier run ended before done: restoring now")
        restoreIfNeeded(completion: completion)
    }

    /// From the launch thread, right after the debugger detached: runs "done" if
    /// needed and blocks until Madeira is back (or `timeout` passes). Nothing draws
    /// yet at that point, so the moment in the background is safe.
    nonisolated static func restoreBlocking(timeout: TimeInterval = 30) {
        let finished = DispatchSemaphore(value: 0)
        DispatchQueue.main.async {
            MainActor.assumeIsolated { shared.restoreIfNeeded { finished.signal() } }
        }
        if finished.wait(timeout: .now() + timeout) == .timedOut {
            LogStore.shared.log("[jit-shortcut] done did not return within \(Int(timeout)) s; continuing", level: .error)
        }
    }

    private func run(_ input: String, completion: @escaping (Outcome) -> Void) {
        finish(.failed("superseded"))
        guard let callbackScheme = SteamUIExperiment.callbackScheme else {
            completion(.failed("This installation has no valid callback URL scheme. Reinstall a complete iDeck build, or connect LocalDevVPN manually and disable the JIT shortcut."))
            return
        }
        var c = URLComponents()
        c.scheme = "shortcuts"
        c.host = "x-callback-url"
        c.path = "/run-shortcut"
        c.queryItems = [
            URLQueryItem(name: "name", value: Self.name),
            URLQueryItem(name: "input", value: "text"),
            URLQueryItem(name: "text", value: input),
            URLQueryItem(name: "x-success", value: "\(callbackScheme)://jit-network/success"),
            URLQueryItem(name: "x-error", value: "\(callbackScheme)://jit-network/error"),
            URLQueryItem(name: "x-cancel", value: "\(callbackScheme)://jit-network/cancel")
        ]
        guard let url = c.url else { completion(.failed("bad shortcut URL")); return }
        LogStore.shared.log("[jit-shortcut] run input=\(input)")
        waiting = completion
        timeout = Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated { self?.finish(.failed("the shortcut did not return within 60 s")) }
        }
        UIApplication.shared.open(url) { [weak self] opened in
            if !opened { MainActor.assumeIsolated { self?.finish(.failed("Shortcuts could not be opened")) } }
        }
    }

    /// madeira://jit-network/{success|error|cancel}, from Shortcuts' x-callback-url.
    @discardableResult
    func handle(_ url: URL) -> Bool {
        guard let scheme = SteamUIExperiment.callbackScheme, url.scheme?.caseInsensitiveCompare(scheme) == .orderedSame, url.host == "jit-network" else { return false }
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let value = { (name: String) in query.first { $0.name == name }?.value ?? "" }
        switch url.path {
        case "/success": finish(.done(value("result")))
        case "/error":   finish(.failed(value("errorMessage").isEmpty ? "the shortcut failed" : value("errorMessage")))
        default:         finish(.failed("the shortcut was cancelled"))
        }
        return true
    }

    private func finish(_ outcome: Outcome) {
        timeout?.invalidate()
        timeout = nil
        guard let waiting else { return }
        self.waiting = nil
        switch outcome {
        case .done(let result): LogStore.shared.log("[jit-shortcut] returned output=\(result.isEmpty ? "none" : "a VPN name")")
        case .failed(let why):  LogStore.shared.log("[jit-shortcut] failed: \(why)", level: .error)
        }
        waiting(outcome)
    }
}
