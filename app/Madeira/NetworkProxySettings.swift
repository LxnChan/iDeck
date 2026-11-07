import Foundation
import SwiftUI
import CFNetwork
import Darwin

public enum NetworkProxyType: String, CaseIterable, Identifiable {
    case http = "HTTP"
    case socks5 = "SOCKS5"
    public var id: String { rawValue }
}

public final class NetworkProxySettings: ObservableObject {
    public static let shared = NetworkProxySettings()

    @AppStorage("networkProxyEnabled") public var enabled: Bool = false
    @AppStorage("networkProxyType") public var type: String = NetworkProxyType.http.rawValue
    @AppStorage("networkProxyHost") public var host: String = "127.0.0.1"
    @AppStorage("networkProxyPort") public var port: Int = 7890
    @AppStorage("networkProxyAppEnabled") public var appEnabled: Bool = true
    @AppStorage("networkProxyWineEnabled") public var wineEnabled: Bool = true

    public var isProxyConfigured: Bool {
        enabled && !cleanHost.isEmpty && port > 0 && port <= 65535
    }

    public var isAppActive: Bool {
        enabled && appEnabled && !cleanHost.isEmpty && port > 0
    }

    public var isWineActive: Bool {
        enabled && wineEnabled && !cleanHost.isEmpty && port > 0
    }

    public var cleanHost: String {
        host.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public var proxyScheme: String {
        type == NetworkProxyType.socks5.rawValue ? "socks5" : "http"
    }

    public var proxyURLString: String {
        "\(proxyScheme)://\(cleanHost):\(port)"
    }

    /// CEF argument for steamwebhelper: -proxy-server="http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    public var cefArguments: String {
        guard isWineActive else { return "" }
        return " -proxy-server=\"\(proxyURLString)\""
    }

    /// Applies proxy dictionary whenever proxy is enabled (used by network probe and sessions).
    public func applyProxyDictionary(to configuration: URLSessionConfiguration) {
        guard isProxyConfigured else {
            configuration.connectionProxyDictionary = nil
            return
        }

        var dict: [AnyHashable: Any] = [:]
        if type == NetworkProxyType.socks5.rawValue {
            dict[kCFStreamPropertySOCKSProxy] = true
            dict[kCFStreamPropertySOCKSProxyHost] = cleanHost
            dict[kCFStreamPropertySOCKSProxyPort] = port
            dict[kCFStreamPropertySOCKSVersion] = kCFStreamSocketSOCKSVersion5
            dict["SOCKSEnable"] = true
            dict["SOCKSProxy"] = cleanHost
            dict["SOCKSPort"] = port
            dict["SOCKSVersion"] = kCFStreamSocketSOCKSVersion5
        } else {
            dict[kCFNetworkProxiesHTTPEnable] = true
            dict[kCFNetworkProxiesHTTPProxy] = cleanHost
            dict[kCFNetworkProxiesHTTPPort] = port
            dict["HTTPEnable"] = true
            dict["HTTPProxy"] = cleanHost
            dict["HTTPPort"] = port
            dict["HTTPSEnable"] = true
            dict["HTTPSProxy"] = cleanHost
            dict["HTTPSPort"] = port
        }
        configuration.connectionProxyDictionary = dict
    }

    /// Applies proxy configuration to an existing or new URLSessionConfiguration
    public func apply(to configuration: URLSessionConfiguration) {
        guard isAppActive else {
            configuration.connectionProxyDictionary = nil
            return
        }
        applyProxyDictionary(to: configuration)
    }

    /// Factory for ephemeral or default URLSession that respects proxy
    public func makeSession(configuration: URLSessionConfiguration = .default, delegate: URLSessionDelegate? = nil, delegateQueue: OperationQueue? = nil) -> URLSession {
        apply(to: configuration)
        return URLSession(configuration: configuration, delegate: delegate, delegateQueue: delegateQueue)
    }

    /// Convenience shared session that reflects current proxy settings
    public static var session: URLSession {
        if shared.isAppActive {
            let config = URLSessionConfiguration.default
            shared.apply(to: config)
            return URLSession(configuration: config)
        }
        return URLSession.shared
    }

    /// Helper to configure any ephemeral session
    public static func makeEphemeralSession() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        shared.apply(to: config)
        return URLSession(configuration: config)
    }
}

public struct NetworkProxySettingsSection: View {
    @ObservedObject private var proxy = NetworkProxySettings.shared

    public init() {}

    public var body: some View {
        Section {
            Toggle("Enable proxy", isOn: $proxy.enabled)

            if proxy.enabled {
                Picker("Protocol", selection: $proxy.type) {
                    Text("HTTP(S)").tag(NetworkProxyType.http.rawValue)
                    Text("SOCKS5").tag(NetworkProxyType.socks5.rawValue)
                }
                .pickerStyle(.segmented)

                HStack {
                    Text("Host")
                    Spacer()
                    TextField("127.0.0.1", text: $proxy.host)
                        .multilineTextAlignment(.trailing)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                        .frame(maxWidth: 180)
                }

                HStack {
                    Text("Port")
                    Spacer()
                    TextField("7890", value: $proxy.port, format: .number)
                        .multilineTextAlignment(.trailing)
                        .keyboardType(.numberPad)
                        .frame(maxWidth: 100)
                }

                Toggle("App native proxy", isOn: $proxy.appEnabled)
                Toggle("Wine internal proxy", isOn: $proxy.wineEnabled)
            }
        } header: {
            Text("Network Proxy")
        } footer: {
            if proxy.enabled {
                Text("Supports local background proxy tools (e.g. Shadowsocks, Surge at 127.0.0.1) or LAN gateways. App proxy applies to Steam sign-in, Cloud saves, and artwork. Wine proxy applies to Steam Store, CEF browser, and client updates upon session launch.")
            } else {
                Text("Route App and Wine traffic through an HTTP or SOCKS5 proxy.")
            }
        }
    }
}

@MainActor
public final class SteamNetworkChecker: ObservableObject {
    public static let shared = SteamNetworkChecker()

    public enum ProbeState: Equatable {
        case idle
        case checking(viaProxy: Bool, proxySummary: String?)
        case success(latencyMs: Int, viaProxy: Bool, proxySummary: String?)
        case failure(latencyMs: Int, viaProxy: Bool, proxySummary: String?, reason: String)
    }

    @Published public private(set) var state: ProbeState = .idle
    @Published public var showDisableProxyAlert: Bool = false
    @Published public private(set) var alertMessage: String = ""

    private var checkTask: Task<Void, Never>?

    private init() {}

    public func check() {
        checkTask?.cancel()
        let proxy = NetworkProxySettings.shared
        let viaProxy = proxy.enabled
        let host = proxy.cleanHost
        let port = proxy.port
        let proto = proxy.type
        let proxySummary: String? = viaProxy ? "\(proto) \(host):\(port)" : nil

        state = .checking(viaProxy: viaProxy, proxySummary: proxySummary)

        checkTask = Task { @MainActor in
            let startTime = CFAbsoluteTimeGetCurrent()

            if viaProxy {
                if !proxy.isProxyConfigured {
                    let ms = max(1, Int((CFAbsoluteTimeGetCurrent() - startTime) * 1000))
                    self.state = .failure(latencyMs: ms, viaProxy: true, proxySummary: proxySummary, reason: "Invalid proxy")
                    self.alertMessage = "Cannot connect to proxy (\(host):\(port)). Would you like to disable the proxy?"
                    self.showDisableProxyAlert = true
                    return
                }

                let tcpReachable = await Task.detached(priority: .userInitiated) {
                    Self.checkProxyTCPReachable(host: host, port: port, timeoutMs: 3000)
                }.value

                guard !Task.isCancelled else { return }

                if !tcpReachable {
                    let ms = max(1, Int((CFAbsoluteTimeGetCurrent() - startTime) * 1000))
                    self.state = .failure(latencyMs: ms, viaProxy: true, proxySummary: proxySummary, reason: "Proxy unreachable")
                    self.alertMessage = "Could not connect to proxy server (\(proto) \(host):\(port)). Would you like to disable the proxy?"
                    self.showDisableProxyAlert = true
                    return
                }
            }

            let config = URLSessionConfiguration.ephemeral
            config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            config.urlCache = nil
            config.timeoutIntervalForRequest = 8.0
            config.timeoutIntervalForResource = 8.0
            if viaProxy {
                proxy.applyProxyDictionary(to: config)
            } else {
                config.connectionProxyDictionary = nil
            }

            let session = URLSession(configuration: config)
            defer { session.finishTasksAndInvalidate() }

            guard let url = URL(string: "https://store.steampowered.com") else { return }
            var request = URLRequest(url: url)
            request.httpMethod = "GET"
            request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            request.timeoutInterval = 8.0
            request.setValue("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148", forHTTPHeaderField: "User-Agent")

            let httpStart = CFAbsoluteTimeGetCurrent()
            do {
                let (_, response) = try await session.data(for: request)
                guard !Task.isCancelled else { return }
                let ms = max(1, Int((CFAbsoluteTimeGetCurrent() - httpStart) * 1000))
                if let http = response as? HTTPURLResponse, (200..<400).contains(http.statusCode) {
                    self.state = .success(latencyMs: ms, viaProxy: viaProxy, proxySummary: proxySummary)
                    self.showDisableProxyAlert = false
                } else {
                    let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                    self.state = .failure(latencyMs: ms, viaProxy: viaProxy, proxySummary: proxySummary, reason: "HTTP \(code)")
                    if viaProxy {
                        self.alertMessage = "Connected to proxy (\(proto) \(host):\(port)), but HTTPS GET to steampowered.com failed (HTTP \(code)). Would you like to disable the proxy?"
                        self.showDisableProxyAlert = true
                    }
                }
            } catch {
                guard !Task.isCancelled else { return }
                if (error as? URLError)?.code == .cancelled { return }
                let ms = max(1, Int((CFAbsoluteTimeGetCurrent() - startTime) * 1000))
                self.state = .failure(latencyMs: ms, viaProxy: viaProxy, proxySummary: proxySummary, reason: "Unreachable")
                if viaProxy {
                    self.alertMessage = "Failed to connect to steampowered.com through proxy (\(proto) \(host):\(port)): \(error.localizedDescription)\n\nWould you like to disable the proxy?"
                    self.showDisableProxyAlert = true
                }
            }
        }
    }

    public func disableProxyAndRecheck() {
        NetworkProxySettings.shared.enabled = false
        showDisableProxyAlert = false
        check()
    }

    nonisolated static func checkProxyTCPReachable(host: String, port: Int, timeoutMs: Int = 3000) -> Bool {
        guard !host.isEmpty, port > 0, port <= 65535 else { return false }
        var hints = addrinfo()
        hints.ai_family = AF_UNSPEC
        hints.ai_socktype = SOCK_STREAM
        hints.ai_protocol = IPPROTO_TCP

        var res: UnsafeMutablePointer<addrinfo>?
        let status = getaddrinfo(host, String(port), &hints, &res)
        guard status == 0, let firstAddr = res else { return false }
        defer { freeaddrinfo(res) }

        var ptr: UnsafeMutablePointer<addrinfo>? = firstAddr
        while let info = ptr {
            ptr = info.pointee.ai_next
            let fd = socket(info.pointee.ai_family, info.pointee.ai_socktype, info.pointee.ai_protocol)
            guard fd >= 0 else { continue }
            defer { close(fd) }

            let flags = fcntl(fd, F_GETFL, 0)
            _ = fcntl(fd, F_SETFL, flags | O_NONBLOCK)

            let rc = connect(fd, info.pointee.ai_addr, info.pointee.ai_addrlen)
            if rc == 0 {
                return true
            }
            if errno == EINPROGRESS {
                var pfd = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                let polled = poll(&pfd, 1, Int32(timeoutMs))
                if polled > 0 && (pfd.revents & Int16(POLLOUT)) != 0 {
                    var soError: Int32 = 0
                    var len = socklen_t(MemoryLayout<Int32>.size)
                    if getsockopt(fd, SOL_SOCKET, SO_ERROR, &soError, &len) == 0 && soError == 0 {
                        return true
                    }
                }
            }
        }
        return false
    }
}

public struct SteamNetworkIndicatorBar: View {
    @ObservedObject private var checker = SteamNetworkChecker.shared
    @ObservedObject private var proxy = NetworkProxySettings.shared

    public init() {}

    private var barBackground: Color {
        switch checker.state {
        case .success:
            return Color.green.opacity(0.14)
        case .failure:
            return Color.red.opacity(0.14)
        case .idle, .checking:
            return Color(uiColor: .secondarySystemGroupedBackground)
        }
    }

    private var barBorder: Color {
        switch checker.state {
        case .success:
            return Color.green.opacity(0.55)
        case .failure:
            return Color.red.opacity(0.55)
        case .idle, .checking:
            return Color.secondary.opacity(0.25)
        }
    }

    public var body: some View {
        Button {
            checker.check()
        } label: {
            HStack(spacing: 8) {
                switch checker.state {
                case .idle, .checking:
                    ProgressView()
                        .controlSize(.mini)
                case .success:
                    Circle()
                        .fill(Color.green)
                        .frame(width: 8, height: 8)
                case .failure:
                    Circle()
                        .fill(Color.red)
                        .frame(width: 8, height: 8)
                }

                Text("steampowered.com")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(1)

                Text(proxy.enabled ? "Proxy (\(proxy.type) \(proxy.cleanHost):\(proxy.port))" : "Direct")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)

                Spacer(minLength: 6)

                switch checker.state {
                case .idle, .checking:
                    Text("Checking…")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                case .success(let latencyMs, _, _):
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption2)
                        Text("\(latencyMs) ms")
                            .font(.caption.weight(.bold).monospacedDigit())
                    }
                    .foregroundStyle(.green)
                case .failure(let latencyMs, _, _, let reason):
                    HStack(spacing: 4) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.caption2)
                        Text("\(reason) · \(latencyMs) ms")
                            .font(.caption.weight(.bold).monospacedDigit())
                    }
                    .foregroundStyle(.red)
                }

                Image(systemName: "arrow.clockwise")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(barBackground, in: Capsule())
            .overlay(Capsule().strokeBorder(barBorder, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .onAppear {
            checker.check()
        }
        .onChange(of: proxy.enabled) { _, _ in
            checker.check()
        }
        .onChange(of: proxy.type) { _, _ in
            if proxy.enabled { checker.check() }
        }
        .onChange(of: proxy.host) { _, _ in
            if proxy.enabled { checker.check() }
        }
        .onChange(of: proxy.port) { _, _ in
            if proxy.enabled { checker.check() }
        }
        .alert("Proxy Connection Failed", isPresented: $checker.showDisableProxyAlert) {
            Button("Disable Proxy", role: .destructive) {
                checker.disableProxyAndRecheck()
            }
            Button("Keep Proxy", role: .cancel) {
                checker.showDisableProxyAlert = false
            }
        } message: {
            Text(checker.alertMessage)
        }
    }
}
