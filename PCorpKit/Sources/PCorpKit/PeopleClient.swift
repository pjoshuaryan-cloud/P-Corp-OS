import Foundation

/// Plain REST fetch for GET /people/dashboard -- same one-shot pattern as
/// JoshxClient/PersonalClient, backing the "PEOPLE" section inside
/// Personal (Josh's real personal/professional relationship network,
/// deliberately separate from Joshx/Alpha Mode Media clients -- see
/// backend/app/people_db.py's docstring). A sibling client alongside
/// PersonalClient in the view, not a merged endpoint -- keeps the two
/// data sources independently fetchable/failable, same as WarRoomView
/// already keeps focusClient/insightsClient separate.
@MainActor
public final class PeopleClient: ObservableObject {
    @Published public private(set) var dashboard: PeopleDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/people/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(PeopleDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
