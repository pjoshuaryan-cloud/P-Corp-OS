import Foundation

/// Plain REST fetch for GET /agents -- same one-shot pattern as
/// OperationsClient/MemoryClient, not routed through BackendClient's
/// WebSocket since this is a simple read, not a persistent stream.
@MainActor
public final class AgentsClient: ObservableObject {
    @Published public private(set) var agents: [Agent] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/agents")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            agents = try JSONDecoder().decode([Agent].self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }
}
