import Combine
import Foundation
import PCorpKit

/// iOS-only, unlike every other *Client.swift so far -- desktop reads its
/// knowledge docs straight off local disk (KnowledgeDocs.swift +
/// ProjectPaths.swift there), which only works because desktop runs on
/// the same Mac as the repo. A phone has no filesystem access to that Mac
/// at all, so this talks to the new GET /knowledge / GET /knowledge/
/// {filename} routes (backend/app/knowledge.py) instead. Doc content is
/// fetched on demand per selection, not all at once on load -- some of
/// these files (CHANGELOG.md) are large, and there's no reason to pull
/// every doc's full text before the user has even picked one.
public struct KnowledgeDocSummary: Identifiable, Hashable, Decodable {
    public let filename: String
    public let title: String
    public let subtitle: String
    public var id: String { filename }
}

@MainActor
final class KnowledgeClient: ObservableObject {
    @Published private(set) var docs: [KnowledgeDocSummary] = []
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?

    private var listURL: URL {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/knowledge")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: listURL)
            docs = try JSONDecoder().decode([KnowledgeDocSummary].self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }

    func fetchContent(filename: String) async -> String {
        var components = URLComponents(string: "http://\(BackendHost.host):8731/knowledge/\(filename)")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        guard let url = components.url else { return "Couldn't load \(filename)." }
        struct ContentResponse: Decodable { let content: String }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            return try JSONDecoder().decode(ContentResponse.self, from: data).content
        } catch {
            return "Couldn't load \(filename)."
        }
    }
}
