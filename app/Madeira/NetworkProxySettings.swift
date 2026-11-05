import Foundation
import SwiftUI

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

    /// Applies proxy configuration to an existing or new URLSessionConfiguration
    public func apply(to configuration: URLSessionConfiguration) {
        guard isAppActive else {
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
