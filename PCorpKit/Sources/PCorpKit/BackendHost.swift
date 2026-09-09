import Foundation

/// Which real backend a client talks to (2026-09-09, Infrastructure
/// Independence Phase 1, Stage 2). `.staging`/`.production` are
/// placeholders on the reserved `.invalid` TLD (RFC 2606 -- guaranteed to
/// never resolve to a real domain) since no cloud backend exists yet;
/// selecting either today will just fail to connect, which is the honest,
/// correct behavior for an environment that doesn't exist, not a bug to
/// work around. Once real cloud hosting is provisioned, these two cases'
/// `host` values become the only change needed here.
public enum PCorpEnvironment {
    case local
    case staging
    case production

    var host: String {
        switch self {
        case .local: return BackendHost.localHost
        case .staging: return "staging.pcorp.invalid"
        case .production: return "api.pcorp.invalid"
        }
    }

    /// `.local` keeps the real backend's fixed port; a real cloud host
    /// terminates TLS on the standard port instead (nil means "use the
    /// scheme's default").
    var port: Int? {
        switch self {
        case .local: return 8731
        case .staging, .production: return nil
        }
    }

    var isSecure: Bool {
        switch self {
        case .local: return false
        case .staging, .production: return true
        }
    }
}

/// Every `*Client.swift` file builds its URLs off this instead of a
/// hardcoded "127.0.0.1" (2026-08-12, split out when the iOS companion
/// app needed a real host to talk to). Extended to a real environment
/// system (2026-09-09) once the audit found every client independently
/// reconstructing the same "http://host:8731/path + token" shape by hand,
/// with no single place an environment switch could actually take effect.
///
/// `localHost` is exactly the old `host` value, renamed to reflect what it
/// actually is: what ".local" resolves to on this platform. Desktop
/// leaves it at its default -- same Mac as the backend, unreachable over
/// the network by design. iOS sets it to this Mac's Tailscale-assigned IP
/// (the listener backend/app/main.py's run() already adds when
/// TAILSCALE_IP is set) -- never a public IP, matching SECURITY.md's
/// threat model.
public enum BackendHost {
    public static var localHost: String = "127.0.0.1"

    /// Which environment every client currently targets. Defaults to
    /// `.local` on both platforms -- unchanged behavior from before this
    /// enum existed. No Settings-screen switcher yet: there's nothing real
    /// to switch to until a cloud backend is actually provisioned.
    public static var environment: PCorpEnvironment = .local

    private static var scheme: String { environment.isSecure ? "https" : "http" }
    private static var wsScheme: String { environment.isSecure ? "wss" : "ws" }

    private static var hostAndPort: String {
        guard let port = environment.port else { return environment.host }
        return "\(environment.host):\(port)"
    }

    /// The one place every REST call builds its URL from now -- `path`
    /// starts with "/", `extraQueryItems` covers the handful of call
    /// sites that need more than just the auth token (SearchClient's `q`,
    /// FinanceClient.fetchHistory's `account_id`/`from`/`to`, etc.).
    public static func url(path: String, extraQueryItems: [URLQueryItem] = []) -> URL {
        var components = URLComponents(string: "\(scheme)://\(hostAndPort)\(path)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")] + extraQueryItems
        return components.url!
    }

    /// The WebSocket equivalent -- only ever used for /ws today.
    public static func wsURL(path: String) -> URL {
        var components = URLComponents(string: "\(wsScheme)://\(hostAndPort)\(path)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }
}
