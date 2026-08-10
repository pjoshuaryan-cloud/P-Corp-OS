import Foundation

/// Plain REST fetch for GET /focus -- same one-shot pattern as
/// AgentsClient, backing the Mission Status card's real "Focus: ..." line.
@MainActor
final class FocusClient: ObservableObject {
    @Published private(set) var objective: String?

    private var url: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/focus")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            objective = try JSONDecoder().decode(FocusObjective.self, from: data).objective
        } catch {
            objective = nil
        }
    }
}
