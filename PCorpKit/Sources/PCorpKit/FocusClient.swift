import Foundation

/// Plain REST fetch for GET /focus -- same one-shot pattern as
/// AgentsClient, backing the Mission Status card's real "Focus: ..." line.
@MainActor
public final class FocusClient: ObservableObject {
    @Published public private(set) var objective: String?

    public init() {}

    private var url: URL { BackendHost.url(path: "/focus") }

    public func fetch() async {
        do {
            let (data, _) = try await BackendURLSession.shared.data(from: url)
            objective = try JSONDecoder().decode(FocusObjective.self, from: data).objective
        } catch {
            objective = nil
        }
    }
}
