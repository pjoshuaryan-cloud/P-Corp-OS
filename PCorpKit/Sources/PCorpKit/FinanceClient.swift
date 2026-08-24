import Foundation

/// Plain REST fetch for GET /finance/dashboard -- same one-shot pattern
/// as JoshxClient/PersonalClient, backing the "Finance" section (Josh's
/// personal investment tracking -- see backend/app/finance_db.py's
/// docstring).
@MainActor
public final class FinanceClient: ObservableObject {
    @Published public private(set) var dashboard: FinanceDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/finance/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(FinanceDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
