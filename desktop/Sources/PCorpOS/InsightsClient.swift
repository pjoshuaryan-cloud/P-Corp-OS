import Foundation

/// Plain REST fetch for GET /insights — same one-shot pattern as
/// MemoryClient/OperationsClient. Real, computed insights (app/insights.py),
/// not the hardcoded placeholder text this card used to show.
@MainActor
final class InsightsClient: ObservableObject {
    @Published private(set) var insights: [InsightItem] = []
    @Published private(set) var isLoading = false

    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/insights")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        isLoading = true
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            insights = try JSONDecoder().decode([InsightItem].self, from: data)
        } catch {
            insights = []
        }
        isLoading = false
    }
}
