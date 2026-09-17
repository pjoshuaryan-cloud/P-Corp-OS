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

    private var url: URL { BackendHost.url(path: "/personal/dashboard") }

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

    private struct ErrorDetail: Decodable { let detail: String }

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

    private struct GoalCreatePayload: Encodable {
        let title: String
        let targetDate: String?
        let notes: String?
        enum CodingKeys: String, CodingKey { case title; case targetDate = "target_date"; case notes }
    }

    /// Backs Personal's new "+Add" goal form (2026-09-17, Editability
    /// Pass 1) -- wraps the same add_goal Frank's own ADD_GOAL_TOOL
    /// already uses.
    public func addGoal(title: String, targetDate: String? = nil, notes: String? = nil) async {
        var request = URLRequest(url: BackendHost.url(path: "/personal/goals"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(GoalCreatePayload(title: title, targetDate: targetDate, notes: notes))
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    private struct HabitCreatePayload: Encodable {
        let title: String
        let cadence: String?
        let notes: String?
    }

    /// Backs Personal's new "+Add" habit form (2026-09-17, Editability
    /// Pass 1) -- wraps the same add_habit Frank's own ADD_HABIT_TOOL
    /// already uses.
    public func addHabit(title: String, cadence: String? = nil, notes: String? = nil) async {
        var request = URLRequest(url: BackendHost.url(path: "/personal/habits"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(HabitCreatePayload(title: title, cadence: cadence, notes: notes))
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }
}
