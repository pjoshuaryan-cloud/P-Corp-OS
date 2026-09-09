import Foundation

/// Plain REST fetch for GET /insights — same one-shot pattern as
/// MemoryClient/OperationsClient. Real, computed insights (app/insights.py),
/// not the hardcoded placeholder text this card used to show.
@MainActor
public final class InsightsClient: ObservableObject {
    @Published public private(set) var insights: [InsightItem] = []
    @Published public private(set) var isLoading = false
    /// Real fetch time (2026-09-03, P Corp OS systems audit) -- this card
    /// polls silently every 30s with no manual refresh and no way to tell
    /// how stale what's on screen is; set on every successful fetch so the
    /// UI can show it honestly rather than leaving staleness invisible.
    @Published public private(set) var lastFetchedAt: Date?

    public init() {}

    private var url: URL { BackendHost.url(path: "/insights") }

    public func fetch() async {
        isLoading = true
        do {
            let (data, _) = try await BackendURLSession.shared.data(from: url)
            insights = try JSONDecoder().decode([InsightItem].self, from: data)
            lastFetchedAt = Date()
        } catch {
            // Real gap found live (2026-09-06, systems audit §18 sweep):
            // this used to clear `insights` to `[]` on any failed poll --
            // directly undercutting lastFetchedAt's own stated purpose
            // ("a run of failures honestly stops the clock rather than
            // faking freshness"). A cleared list looks identical to "no
            // real insights right now," so a transient failure made a
            // genuine, already-shown insight disappear entirely instead
            // of staying visible and flagged stale via lastFetchedAt not
            // advancing. Now keeps the last-known-good data on screen;
            // only the clock stops.
        }
        isLoading = false
    }
}
