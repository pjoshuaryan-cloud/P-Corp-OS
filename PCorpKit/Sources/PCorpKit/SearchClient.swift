import Foundation

/// Backs GET /search -- the magnifying-glass button's real destination on
/// both platforms (2026-08-27), a genuine cross-domain "Spotlight for
/// P Corp OS" search, distinct from BackendClient.fetchConversationList
/// (which searches real message CONTENT within chat history only). Same
/// one-shot REST pattern as JoshxClient/AgentsClient, with debouncing
/// centralized here (300ms) rather than duplicated in each platform's own
/// view -- ConversationHistorySheet/ConversationListPopover each
/// implement their own scheduleSearch already; this consolidates that so
/// both UniversalSearchSheet (iOS) and UniversalSearchPopover (desktop)
/// share one implementation instead of copying it a third and fourth time.
@MainActor
public final class SearchClient: ObservableObject {
    @Published public private(set) var results: [SearchResult] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    private var searchTask: Task<Void, Never>?

    public init() {}

    private func url(for query: String) -> URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/search")!
        components.queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "token", value: AuthToken.current ?? ""),
        ]
        return components.url!
    }

    /// Call on every keystroke -- cancels any pending/in-flight search
    /// before scheduling a new one 300ms out, same debounce window as
    /// ConversationHistorySheet's own scheduleSearch. An empty/whitespace
    /// query clears results immediately without a request, matching
    /// UniversalSearchSheet/UniversalSearchPopover's own "nothing typed
    /// yet" empty state.
    public func scheduleSearch(_ query: String) {
        searchTask?.cancel()
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            results = []
            isLoading = false
            return
        }
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            await performSearch(trimmed)
        }
    }

    private func performSearch(_ query: String) async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url(for: query))
            guard !Task.isCancelled else { return }
            results = try JSONDecoder().decode([SearchResult].self, from: data)
        } catch {
            if !Task.isCancelled {
                errorMessage = "Couldn't reach the backend — is it running?"
            }
        }
        isLoading = false
    }
}
