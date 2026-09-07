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
            let (data, _) = try await BackendURLSession.shared.data(from: url)
            agents = try JSONDecoder().decode([Agent].self, from: data)
        } catch {
            // Real bug found live (2026-09-07): a cold app launch can
            // briefly race Tailscale's own route negotiation -- a single
            // silent retry after a short delay resolves what's actually
            // just a momentary, self-resolving startup timing issue,
            // instead of leaving a wrong-looking, permanently-stuck error
            // until the user manually re-navigates (this view's own
            // `.task` only ever fires once per appearance).
            try? await Task.sleep(for: .seconds(2))
            do {
                let (data, _) = try await BackendURLSession.shared.data(from: url)
                agents = try JSONDecoder().decode([Agent].self, from: data)
            } catch {
                errorMessage = "Couldn't reach Frank's backend — check your connection and try again."
            }
        }
        isLoading = false
    }
}
