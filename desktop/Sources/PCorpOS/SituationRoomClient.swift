import Foundation

/// Plain REST fetch for GET /situation-room — same one-shot pattern as
/// InsightsClient, backing War Room's escalated alert banner (distinct
/// from the routine Insights card; see app/situation_room.py's docstring).
@MainActor
final class SituationRoomClient: ObservableObject {
    @Published private(set) var alerts: [SituationRoomAlert] = []

    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/situation-room")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            alerts = try JSONDecoder().decode([SituationRoomAlert].self, from: data)
        } catch {
            alerts = []
        }
    }
}
