import Foundation

/// Plain REST fetch for GET /alpha-mode/dashboard -- same one-shot
/// pattern as AgentsClient, backing the sidebar's real "Alpha Mode
/// Media" section (previously a generic unbuilt placeholder).
@MainActor
public final class AlphaModeDashboardClient: ObservableObject {
    @Published public private(set) var dashboard: AlphaModeDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/alpha-mode/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(AlphaModeDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }
}
