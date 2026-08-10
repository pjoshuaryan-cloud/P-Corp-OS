import Foundation

/// Plain REST fetch for GET /alpha-mode/dashboard -- same one-shot
/// pattern as AgentsClient, backing the sidebar's real "Alpha Mode
/// Media" section (previously a generic unbuilt placeholder).
@MainActor
final class AlphaModeDashboardClient: ObservableObject {
    @Published private(set) var dashboard: AlphaModeDashboard?
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/alpha-mode/dashboard")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
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
