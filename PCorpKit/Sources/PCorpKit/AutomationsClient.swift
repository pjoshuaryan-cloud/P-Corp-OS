import Foundation

/// Plain REST fetch for GET /automations/rules and GET /automations/runs --
/// same one-shot pattern as AgentsClient/OperationsClient.
@MainActor
public final class AutomationsClient: ObservableObject {
    @Published public private(set) var rules: [AutomationRule] = []
    @Published public private(set) var runs: [AutomationRun] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private func url(path: String) -> URL { BackendHost.url(path: path) }

    public func fetch() async {
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

    private struct ErrorDetail: Decodable { let detail: String }

    /// Real gap found live (2026-09-06, systems audit §18 sweep) -- mirrors
    /// JoshxClient's own performWrite exactly. A real backend rejection
    /// (main.py's `HTTPException(404, detail: "...")`) used to be
    /// silently discarded via `try?`; now surfaced honestly. Set on
    /// `errorMessage` *after* the follow-up `fetch()` call, since fetch()
    /// itself unconditionally clears `errorMessage` at its own start.
    private func performWrite(_ request: URLRequest) async -> String? {
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail
                    ?? "Request failed (\(http.statusCode))."
            }
            return nil
        } catch {
            return "Couldn't reach the backend — is it running?"
        }
    }

    /// Pause/resume a rule (2026-09-06) -- mirrors Triggers' own already-
    /// proven enable/disable pattern. Refetches everything afterward
    /// rather than reconstructing local state, same deliberate choice
    /// JoshxClient's own write methods already make (avoids a copy-paste
    /// field-omission bug for the sake of an update that's an occasional
    /// deliberate action, not a rapid-fire control).
    public func toggleRule(id: String, enabled: Bool) async {
        var request = URLRequest(url: url(path: "/automations/rules/\(id)"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["enabled": enabled])
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func deleteRule(id: String) async {
        var request = URLRequest(url: url(path: "/automations/rules/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }
}
