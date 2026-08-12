import Foundation

/// Plain REST fetch for GET /situation-room — same one-shot pattern as
/// InsightsClient, backing War Room's escalated alert banner (distinct
/// from the routine Insights card; see app/situation_room.py's docstring).
@MainActor
public final class SituationRoomClient: ObservableObject {
    @Published public private(set) var alerts: [SituationRoomAlert] = []

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/situation-room")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            alerts = try JSONDecoder().decode([SituationRoomAlert].self, from: data)
        } catch {
            alerts = []
        }
    }
}
