import Foundation

/// Plain REST fetch for GET /personal/dashboard -- same one-shot pattern
/// as TradingDivisionClient/AlphaModeDashboardClient, backing the
/// "Personal" section (previously a generic unbuilt placeholder,
/// deliberately left that way until Joshua explicitly scoped it -- see
/// backend/app/personal_db.py's docstring).
@MainActor
public final class PersonalClient: ObservableObject {
    @Published public private(set) var dashboard: PersonalDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/personal/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(PersonalDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
