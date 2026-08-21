import Foundation

/// Plain REST fetch for GET /joshx/dashboard -- same one-shot pattern as
/// PersonalClient/TradingDivisionClient, backing the "Joshx" section
/// (Josh's independent freelance creative business, completely separate
/// from Alpha Mode Media -- see backend/app/joshx_db.py's docstring).
@MainActor
public final class JoshxClient: ObservableObject {
    @Published public private(set) var dashboard: JoshxDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/joshx/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(JoshxDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
