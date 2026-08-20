import Foundation

/// Plain REST fetch for GET /brief -- same one-shot pattern as
/// AlphaModeDashboardClient/TradingDivisionClient. Unlike those, fetching
/// this is a real state-changing read on the backend (it marks the brief
/// as viewed, updating what "What Changed" means next time) -- so this
/// client deliberately does NOT poll on a timer the way InsightsCard
/// does; it should only fetch when the user actually opens the Brief.
@MainActor
public final class BriefClient: ObservableObject {
    @Published public private(set) var brief: Brief?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/brief")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            brief = try JSONDecoder().decode(Brief.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
