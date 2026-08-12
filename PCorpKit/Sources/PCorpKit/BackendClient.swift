import Foundation
#if canImport(UIKit)
import UIKit
public typealias PlatformImage = UIImage
#else
import AppKit
public typealias PlatformImage = NSImage
#endif

/// A single turn in the conversation — user or assistant. Mirrors
/// backend/app/db.py's `messages` table. Conversations can now start fresh
/// (startNewConversation below) — durable memory, not the transcript, is
/// what carries "there is only ever one Frank" forward. See app/db.py.
public struct ChatMessage: Identifiable {
    public let id = UUID()
    public let role: String
    public var content: String
    /// An already-decoded image for a just-sent-this-session message --
    /// rendered as a real thumbnail. Deliberately a decoded PlatformImage
    /// (NSImage on macOS, UIImage on iOS), not raw Data (real bug found
    /// and fixed 2026-08-10: the first version stored raw Data and
    /// decoded it fresh via NSImage(data:) inside the SwiftUI view body --
    /// for a full-res Retina screenshot, that re-runs an expensive decode
    /// on *every* re-render, which happens repeatedly while a reply is
    /// streaming in, visibly freezing the whole chat view even though the
    /// backend had already finished normally). Decoded once at send time
    /// instead (see BackendClient.send below). nil for text-only messages,
    /// and also nil for a message loaded from a *reopened* old
    /// conversation (see hasStoredImage below) -- old images aren't
    /// re-fetched, only shown as a placeholder, confirmed decision
    /// 2026-08-05 (cost of re-sending an old image to Claude as real
    /// context on every reconnect vs. just knowing one was attached).
    public var image: PlatformImage? = nil
    /// True when GET /history reports this message had an image attached,
    /// but the bytes weren't re-fetched (see image above) -- renders as a
    /// plain "📎 image attached" indicator instead of the real picture.
    public var hasStoredImage: Bool = false

    public init(role: String, content: String, image: PlatformImage? = nil, hasStoredImage: Bool = false) {
        self.role = role
        self.content = content
        self.image = image
        self.hasStoredImage = hasStoredImage
    }
}

/// The connection from the shell to the Python backend, and the owner of
/// the live conversation state — real Claude reasoning streamed back
/// token-by-token (see backend/app/main.py), using native
/// `URLSessionWebSocketTask` (no third-party WebSocket library needed).
/// Loads prior history once on connect (GET /history) so relaunching the
/// app continues the same conversation instead of starting blank, matching
/// the backend's own "one continuous conversation" persistence.
@MainActor
public final class BackendClient: ObservableObject {
    @Published public private(set) var messages: [ChatMessage] = []
    @Published public private(set) var isConnected: Bool = false
    @Published public private(set) var isStreaming: Bool = false

    public init() {}

    private var task: URLSessionWebSocketTask?

    /// True once this process has already started its one fresh
    /// conversation for this launch (see connect()). A `static var`, not
    /// an instance property, deliberately — WarRoomView (and this class
    /// with it) gets torn down and recreated every time you navigate to a
    /// different sidebar section and back (ContentView forces this via
    /// `.id(selectedItem.id)`), so an instance property would re-trigger
    /// "start fresh" on every nav click, not just app launch. Confirmed
    /// decision (2026-07-28): a brand-new conversation starts once per
    /// app launch; clicking to Settings/Calendar/etc. and back to War
    /// Room within the same running session keeps whatever's active, it
    /// doesn't get wiped. Old conversations don't need to "just sit
    /// there" anymore either way — the conversation history browser
    /// (search + date grouping) already makes any of them reachable.
    private static var hasStartedFreshThisLaunch = false

    /// Host comes from BackendHost.host (2026-08-12) -- "127.0.0.1" by
    /// default (desktop: same Mac as the backend, unreachable over the
    /// network by design), settable by the iOS app to this Mac's
    /// Tailscale IP. Token appended fresh at connect time (see
    /// AuthToken.swift) — the backend rejects any connection without it
    /// (SECURITY.md's local-auth fix).
    private var wsURL: URL {
        var components = URLComponents(string: "ws://\(BackendHost.host):8731/ws")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var historyURL: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/history")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var newConversationURL: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private func conversationListURL(query: String?) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations")!
        var items = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        if let query, !query.isEmpty {
            items.append(URLQueryItem(name: "q", value: query))
        }
        components.queryItems = items
        return components.url!
    }

    private func activateURL(_ conversationID: Int) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/conversations/\(conversationID)/activate")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    /// Starts a fresh conversation on the backend, then reconnects so the
    /// live WebSocket picks it up (a connection is bound to whichever
    /// conversation was active at connect time — see backend/app/main.py).
    /// Memory (SECURITY.md-classified "regular" tool, app/memory.py) is
    /// untouched by this; only the transcript resets.
    public func startNewConversation() async {
        messages = []
        var request = URLRequest(url: newConversationURL)
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
        disconnect()
        connect()
    }

    /// Every past conversation, most-recently-active first, for the
    /// history browser. `query`, when non-nil/non-empty, searches real
    /// message content (backend/app/db.py's list_conversations), not just
    /// each conversation's preview — indefinite history only stays useful
    /// if you can actually find something in it later.
    public func fetchConversationList(query: String? = nil) async -> [ConversationSummary] {
        do {
            let (data, _) = try await URLSession.shared.data(from: conversationListURL(query: query))
            return try JSONDecoder().decode([ConversationSummary].self, from: data)
        } catch {
            return []
        }
    }

    /// Reopens an older conversation — makes it active, then reconnects
    /// (same reasoning as startNewConversation: the live WebSocket needs a
    /// fresh connection to pick up whichever conversation is now active).
    public func switchToConversation(_ conversationID: Int) async {
        messages = []
        var request = URLRequest(url: activateURL(conversationID))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
        disconnect()
        connect()
    }

    public func connect() {
        guard task == nil else { return }
        let task = URLSession.shared.webSocketTask(with: wsURL)
        self.task = task
        task.resume()
        isConnected = true
        listen()

        if Self.hasStartedFreshThisLaunch {
            Task { await loadHistory() }
        } else {
            Self.hasStartedFreshThisLaunch = true
            Task { await startFreshConversationForLaunch() }
        }
    }

    /// Creates a new conversation and makes it active — the same backend
    /// call startNewConversation() makes, but skipped-down for use during
    /// connect() itself: no need to clear `messages` (already empty on a
    /// fresh instance) or disconnect/reconnect (there's no live
    /// connection yet to restart), and no loadHistory() call since the
    /// new conversation is guaranteed to have none.
    private func startFreshConversationForLaunch() async {
        var request = URLRequest(url: newConversationURL)
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
    }

    public func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
    }

    /// Interrupts the current reply, similar to Claude's own stop button.
    /// Closes the live socket (the backend's in-flight `send_text` calls
    /// start failing the instant it does, which unwinds `run_claude_turn`
    /// on the server side) and opens a fresh one for the next message --
    /// deliberately NOT calling loadHistory() as part of that reconnect,
    /// since the interrupted turn was never persisted server-side and a
    /// reload would silently erase the partial reply still visible in
    /// `messages`, which is exactly what should stay on screen.
    public func stopGenerating() {
        isStreaming = false
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false

        let newTask = URLSession.shared.webSocketTask(with: wsURL)
        task = newTask
        newTask.resume()
        isConnected = true
        listen()
    }

    /// mediaType is a real image MIME type ("image/png"/"image/jpeg") --
    /// required alongside imageData, not inferred, since the wire payload
    /// (WirePayload below) needs it for Claude's own content-block format.
    public func send(_ text: String, imageData: Data? = nil, mediaType: String? = nil) {
        guard let task else { return }
        // Decoded exactly once, here -- not in the view body (see
        // ChatMessage.image's doc comment for the real bug this fixes).
        let decodedImage = imageData.flatMap { PlatformImage(data: $0) }
        messages.append(ChatMessage(role: "user", content: text, image: decodedImage))
        messages.append(ChatMessage(role: "assistant", content: ""))
        isStreaming = true

        let wireImage = imageData.flatMap { data in
            mediaType.map { WireImage(media_type: $0, data: data.base64EncodedString()) }
        }
        let payload = WirePayload(text: text, image: wireImage)
        guard let json = try? JSONEncoder().encode(payload), let jsonString = String(data: json, encoding: .utf8) else {
            appendToLastAssistantMessage("[connection error: couldn't encode message]")
            isStreaming = false
            return
        }

        task.send(.string(jsonString)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.appendToLastAssistantMessage(
                        "[connection error: \(error.localizedDescription) — is the backend running? `cd backend && uv run python -m app.main`]"
                    )
                    self?.isStreaming = false
                }
            }
        }
    }

    /// Wire format for a sent chat turn (2026-08-05, image upload support)
    /// -- was a bare string before; now a small JSON envelope so an
    /// optional image can ride alongside the text. See backend/app/
    /// main.py's websocket handler for the matching decode side.
    private struct WireImage: Encodable { let media_type: String; let data: String }
    private struct WirePayload: Encodable { let text: String; let image: WireImage? }

    private struct HistoryEntry: Decodable {
        let role: String
        let content: String
        let image_path: String?
    }

    private func loadHistory() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: historyURL)
            let entries = try JSONDecoder().decode([HistoryEntry].self, from: data)
            messages = entries.map {
                ChatMessage(role: $0.role, content: $0.content, hasStoredImage: $0.image_path != nil)
            }
        } catch {
            // Not critical enough to surface a hard error on first load —
            // the thread just starts empty, same as before this existed.
        }
    }

    private func appendToLastAssistantMessage(_ text: String) {
        guard let lastIndex = messages.indices.last, messages[lastIndex].role == "assistant" else { return }
        messages[lastIndex].content += text
    }

    private struct NotificationPayload: Decodable { let title: String; let body: String }
    private static let notifyPrefix = "\n[notify]"

    private func listen() {
        task?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                switch result {
                case .success(let message):
                    if case .string(let text) = message {
                        // Two sentinels from the backend (backend/app/main.py),
                        // neither part of the visible reply: "\n[done]" marks
                        // end of turn, "\n[notify]{json}" is Frank pushing a
                        // real notification (currently: whenever save_memory
                        // fires) rather than chat text.
                        if text == "\n[done]" {
                            self.isStreaming = false
                        } else if text.hasPrefix(Self.notifyPrefix) {
                            let payloadText = String(text.dropFirst(Self.notifyPrefix.count))
                            if let data = payloadText.data(using: .utf8),
                               let payload = try? JSONDecoder().decode(NotificationPayload.self, from: data) {
                                SystemNotification.post(title: payload.title, body: payload.body)
                            }
                        } else {
                            self.appendToLastAssistantMessage(text)
                        }
                    }
                    self.listen() // keep listening for the next chunk
                case .failure:
                    self.isConnected = false
                    self.isStreaming = false
                    self.task = nil
                }
            }
        }
    }
}
