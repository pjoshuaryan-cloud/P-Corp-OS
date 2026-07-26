import Foundation

/// Plain REST fetch for GET /memory — separate from BackendClient's
/// WebSocket connection since this is a simple one-shot read, not a
/// persistent stream. Same 127.0.0.1-only binding as the rest of the backend.
@MainActor
final class MemoryClient: ObservableObject {
    @Published private(set) var records: [MemoryRecord] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    /// Token appended fresh at fetch time (see AuthToken.swift) — the
    /// backend rejects any request without it (SECURITY.md's local-auth fix).
    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/memory")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            records = try JSONDecoder().decode([MemoryRecord].self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }
}
