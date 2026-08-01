import Foundation

/// Plain REST fetch for GET /operations/tasks — same one-shot pattern as
/// MemoryClient, not routed through BackendClient's WebSocket since this
/// is a simple read, not a persistent stream.
@MainActor
final class OperationsClient: ObservableObject {
    @Published private(set) var tasks: [OperationsTask] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/operations/tasks")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            tasks = try JSONDecoder().decode([OperationsTask].self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }
}
