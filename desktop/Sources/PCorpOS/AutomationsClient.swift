import Foundation

/// Plain REST fetch for GET /automations/rules and GET /automations/runs --
/// same one-shot pattern as AgentsClient/OperationsClient.
@MainActor
final class AutomationsClient: ObservableObject {
    @Published private(set) var rules: [AutomationRule] = []
    @Published private(set) var runs: [AutomationRun] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private func url(path: String) -> URL {
        var components = URLComponents(string: "http://127.0.0.1:8731\(path)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (rulesData, _) = try await URLSession.shared.data(from: url(path: "/automations/rules"))
            rules = try JSONDecoder().decode([AutomationRule].self, from: rulesData)
            let (runsData, _) = try await URLSession.shared.data(from: url(path: "/automations/runs"))
            runs = try JSONDecoder().decode([AutomationRun].self, from: runsData)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }
}
