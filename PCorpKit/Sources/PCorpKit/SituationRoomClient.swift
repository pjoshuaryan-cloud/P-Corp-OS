import Foundation

/// Plain REST fetch for GET /situation-room — same one-shot pattern as
/// InsightsClient, backing War Room's escalated alert banner (distinct
/// from the routine Insights card; see app/situation_room.py's docstring).
@MainActor
public final class SituationRoomClient: ObservableObject {
    @Published public private(set) var alerts: [SituationRoomAlert] = []
    /// Real fetch time (2026-09-03, P Corp OS systems audit) -- same
    /// reasoning as InsightsClient.lastFetchedAt: this polls silently
    /// every 30s with no manual refresh and no visible staleness signal.
    /// Only advances on a successful fetch, so a run of failures honestly
    /// stops the clock rather than faking freshness.
    @Published public private(set) var lastFetchedAt: Date?

    public init() {}

    private var url: URL { BackendHost.url(path: "/situation-room") }

    public func fetch() async {
        do {
            let (data, _) = try await BackendURLSession.shared.data(from: url)
            alerts = try JSONDecoder().decode([SituationRoomAlert].self, from: data)
            lastFetchedAt = Date()
        } catch {
            // Real gap found live (2026-09-06, systems audit §18 sweep):
            // this used to clear `alerts` to `[]` on any failed poll --
            // directly undercutting lastFetchedAt's own stated purpose
            // above ("a run of failures honestly stops the clock rather
            // than faking freshness"). A cleared list looks identical to
            // "nothing escalated right now," so a transient failure made
            // a real, already-shown risk alert disappear entirely
            // instead of staying visible and flagged stale via
            // lastFetchedAt not advancing. Now keeps the last-known-good
            // alerts on screen; only the clock stops.
        }
    }
}
