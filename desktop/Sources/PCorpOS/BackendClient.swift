import Foundation

/// First real connection from the shell to the Python backend — proves the
/// IPC contract end to end (SwiftUI -> WebSocket -> FastAPI -> streamed
/// response -> SwiftUI), using native `URLSessionWebSocketTask` (no
/// third-party WebSocket library needed). The backend currently echoes
/// messages back in streamed word-by-word chunks (see backend/app/main.py) —
/// real streaming mechanics, canned content, per the explicit scoping
/// decision to prove the plumbing before adding real Frank intelligence.
@MainActor
final class BackendClient: ObservableObject {
    @Published private(set) var response: String = ""
    @Published private(set) var isConnected: Bool = false

    private var task: URLSessionWebSocketTask?

    /// Bound to 127.0.0.1 only, matching the backend's own binding — this
    /// isn't reachable over the network, only from this same machine.
    private let url = URL(string: "ws://127.0.0.1:8731/ws")!

    func connect() {
        guard task == nil else { return }
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        isConnected = true
        listen()
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        isConnected = false
    }

    func send(_ text: String) {
        guard let task else { return }
        response = ""
        task.send(.string(text)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.response = "[connection error: \(error.localizedDescription) — is the backend running? `cd backend && uv run python -m app.main`]"
                }
            }
        }
    }

    private func listen() {
        task?.receive { [weak self] result in
            guard let self else { return }
            Task { @MainActor in
                switch result {
                case .success(let message):
                    if case .string(let text) = message {
                        self.response += text
                    }
                    self.listen() // keep listening for the next chunk
                case .failure:
                    self.isConnected = false
                    self.task = nil
                }
            }
        }
    }
}
