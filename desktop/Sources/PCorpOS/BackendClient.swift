import Foundation

/// A single turn in the conversation — user or assistant. Mirrors
/// backend/app/db.py's `messages` table. Conversations can now start fresh
/// (startNewConversation below) — durable memory, not the transcript, is
/// what carries "there is only ever one Frank" forward. See app/db.py.
struct ChatMessage: Identifiable {
    let id = UUID()
    let role: String
    var content: String
}

/// The connection from the shell to the Python backend, and the owner of
/// the live conversation state — real Claude reasoning streamed back
/// token-by-token (see backend/app/main.py), using native
/// `URLSessionWebSocketTask` (no third-party WebSocket library needed).
/// Loads prior history once on connect (GET /history) so relaunching the
/// app continues the same conversation instead of starting blank, matching
/// the backend's own "one continuous conversation" persistence.
@MainActor
final class BackendClient: ObservableObject {
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var isConnected: Bool = false
    @Published private(set) var isStreaming: Bool = false

    private var task: URLSessionWebSocketTask?

    /// Bound to 127.0.0.1 only, matching the backend's own binding — this
    /// isn't reachable over the network, only from this same machine.
    /// Token appended fresh at connect time (see AuthToken.swift) — the
    /// backend rejects any connection without it (SECURITY.md's local-auth
    /// fix).
    private var wsURL: URL {
        var components = URLComponents(string: "ws://127.0.0.1:8731/ws")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var historyURL: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/history")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private var newConversationURL: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/conversations")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    private func conversationListURL(query: String?) -> URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/conversations")!
        var items = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        if let query, !query.isEmpty {
            items.append(URLQueryItem(name: "q", value: query))
        }
        components.queryItems = items
        return components.url!
    }

    private func activateURL(_ conversationID: Int) -> URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/conversations/\(conversationID)/activate")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    /// Starts a fresh conversation on the backend, then reconnects so the
    /// live WebSocket picks it up (a connection is bound to whichever
    /// conversation was active at connect time — see backend/app/main.py).
    /// Memory (SECURITY.md-classified "regular" tool, app/memory.py) is
    /// untouched by this; only the transcript resets.
    func startNewConversation() async {
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
    func fetchConversationList(query: String? = nil) async -> [ConversationSummary] {
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
    func switchToConversation(_ conversationID: Int) async {
        messages = []
        var request = URLRequest(url: activateURL(conversationID))
        request.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: request)
        disconnect()
        connect()
    }

    func connect() {
        guard task == nil else { return }
        let task = URLSession.shared.webSocketTask(with: wsURL)
        self.task = task
        task.resume()
        isConnected = true
        listen()
        Task { await loadHistory() }
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
    }

    func send(_ text: String) {
        guard let task else { return }
        messages.append(ChatMessage(role: "user", content: text))
        messages.append(ChatMessage(role: "assistant", content: ""))
        isStreaming = true
        task.send(.string(text)) { [weak self] error in
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

    private struct HistoryEntry: Decodable { let role: String; let content: String }

    private func loadHistory() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: historyURL)
            let entries = try JSONDecoder().decode([HistoryEntry].self, from: data)
            messages = entries.map { ChatMessage(role: $0.role, content: $0.content) }
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
