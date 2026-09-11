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

    private var url: URL { BackendHost.url(path: "/agents") }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        // Real bug found live (2026-09-07): a cold app launch can briefly
        // race Tailscale's own route negotiation -- a single silent retry
        // after a short delay resolves what's actually just a momentary,
        // self-resolving startup timing issue, instead of leaving a
        // wrong-looking, permanently-stuck error until the user manually
        // re-navigates (this view's own `.task` only ever fires once per
        // appearance).
        //
        // Extended to three attempts over ~20s (2026-09-11): the real
        // cloud backend's shared database connection can now self-heal
        // from a genuine failure, but that recovery itself takes up to
        // ~20s (main.py's _postgres_health_check_loop) -- a single 2s
        // retry could still land inside that window and give up too
        // early, leaving "0 agents online" on screen with no indication
        // it was a fetch failure, not a real count. Never clears `agents`
        // on failure -- same "keep the last-known-good value, just don't
        // refresh its timestamp" reasoning as InsightsClient.
        let delaysSeconds: [Double] = [2, 6, 12]
        for delay in delaysSeconds {
            do {
                let (data, _) = try await BackendURLSession.shared.data(from: url)
                agents = try JSONDecoder().decode([Agent].self, from: data)
                errorMessage = nil
                isLoading = false
                return
            } catch {
                try? await Task.sleep(for: .seconds(delay))
            }
        }
        do {
            let (data, _) = try await BackendURLSession.shared.data(from: url)
            agents = try JSONDecoder().decode([Agent].self, from: data)
        } catch {
            errorMessage = "Couldn't reach Frank's backend — check your connection and try again."
        }
        isLoading = false
    }
}
