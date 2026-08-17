import Foundation

/// Plain REST fetch for GET /trading-division/dashboard -- same one-shot
/// pattern as AlphaModeDashboardClient, backing the "Trading Division"
/// section (previously a generic unbuilt placeholder, deliberately left
/// that way until Joshua explicitly asked to override the documented
/// blocker -- see backend/app/trading_division.py's docstring).
@MainActor
public final class TradingDivisionClient: ObservableObject {
    @Published public private(set) var dashboard: TradingDivisionDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/trading-division/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(TradingDivisionDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
