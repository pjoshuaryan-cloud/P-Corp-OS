import Foundation

/// Plain REST fetch for GET /memory — separate from BackendClient's
/// WebSocket connection since this is a simple one-shot read, not a
/// persistent stream.
@MainActor
public final class MemoryClient: ObservableObject {
    @Published public private(set) var records: [MemoryRecord] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    /// Token appended fresh at fetch time (see AuthToken.swift) — the
    /// backend rejects any request without it (SECURITY.md's local-auth fix).
    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/memory")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
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

    /// Manual forgetting from the UI — same soft-delete Frank's own
    /// forget_memory tool uses (backend/app/db.py's deleted_at). Removes it
    /// from the local list optimistically rather than waiting on a refetch.
    public func forget(_ record: MemoryRecord) async {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/memory/\(record.id)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        var request = URLRequest(url: components.url!)
        request.httpMethod = "DELETE"
        _ = try? await URLSession.shared.data(for: request)
        records.removeAll { $0.id == record.id }
    }
}
