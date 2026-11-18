import Foundation

/// Describe an edit from the phone (Cinematic Reel Autopilot phase 6b, 2026-11-18). The phone can't plan (the footage is on the Mac's drives), so it leaves the
/// sentence in the shared database and the Mac's backend picks it up: it writes the costed card back, and runs it when Go is pressed here. The phone shows only
/// what the Mac wrote, and whether the Mac is online.
public struct EditChatRelayRequest: Decodable, Identifiable, Sendable {
    public let id: Int
    public let text: String
    public let status: String
    public let card: EditChatCard?
    public let run: EditChatRun?
    public let message: String?
    public let updatedAt: String

    /// Waiting on the Mac (it will change by itself).
    public var isPending: Bool { ["new", "understanding", "go", "starting", "running"].contains(status) }
}

@MainActor
public final class EditChatRelayClient: ObservableObject {
    @Published public private(set) var request: EditChatRelayRequest?
    @Published public private(set) var macOnline = false
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var isSending = false

    public init() {}

    private struct ErrorDetail: Decodable { let detail: String }
    private struct Latest: Decodable { let request: EditChatRelayRequest?; let macOnline: Bool? }
    private struct One: Decodable { let request: EditChatRelayRequest? }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func call(_ method: String, _ path: String, body: [String: Any]? = nil) async -> (Data?, String?) {
        var r = URLRequest(url: BackendHost.url(path: path))
        r.httpMethod = method
        r.timeoutInterval = 30
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: r)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return (nil, (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode)).")
            }
            return (data, nil)
        } catch {
            return (nil, "No connection. Check your signal and try again.")
        }
    }

    /// The newest request and whether the Mac is online. Poll this while the screen is open.
    public func refresh() async {
        let (data, error) = await call("GET", "/post/edit-chat/relay")
        if let error { errorMessage = error; return }
        guard let data, let latest = try? Self.decoder.decode(Latest.self, from: data) else { return }
        errorMessage = nil
        request = latest.request
        macOnline = latest.macOnline ?? false
    }

    public func send(_ text: String) async {
        isSending = true
        defer { isSending = false }
        let (data, error) = await call("POST", "/post/edit-chat/relay", body: ["text": text])
        if let error { errorMessage = error; return }
        if let data, let latest = try? Self.decoder.decode(Latest.self, from: data) {
            errorMessage = nil
            request = latest.request
            macOnline = latest.macOnline ?? macOnline
        }
    }

    public func go() async { await act("go") }
    public func cancel() async { await act("cancel") }

    private func act(_ what: String) async {
        guard let id = request?.id else { return }
        let (data, error) = await call("POST", "/post/edit-chat/relay/\(id)/\(what)")
        if let error { errorMessage = error; return }
        if let data, let one = try? Self.decoder.decode(One.self, from: data) { errorMessage = nil; request = one.request }
    }
}
