import Foundation

/// Plain REST fetch for GET /focus -- same one-shot pattern as
/// AgentsClient, backing the Mission Status card's real "Focus: ..." line.
@MainActor
public final class FocusClient: ObservableObject {
    @Published public private(set) var objective: String?

    public init() {}

    private var url: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/focus")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    public func fetch() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            objective = try JSONDecoder().decode(FocusObjective.self, from: data).objective
        } catch {
            objective = nil
        }
    }
}
