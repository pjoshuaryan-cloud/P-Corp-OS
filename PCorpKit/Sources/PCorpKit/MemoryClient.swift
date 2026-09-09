import Foundation

/// Plain REST fetch for GET /memory — separate from BackendClient's
/// WebSocket connection since this is a simple one-shot read, not a
/// persistent stream.
@MainActor
public final class MemoryClient: ObservableObject {
    @Published public private(set) var records: [MemoryRecord] = []
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?
    /// Set only by forget()'s own failure path -- deliberately separate
    /// from errorMessage, which drives a full-list empty-state
    /// replacement in FrankView; a single failed delete shouldn't hide an
    /// otherwise successfully loaded list behind a "backend unreachable"
    /// screen. The view shows this as a small inline banner instead.
    @Published public private(set) var forgetErrorMessage: String?

    public init() {}

    /// Token appended fresh at fetch time (see AuthToken.swift) — the
    /// backend rejects any request without it (SECURITY.md's local-auth fix).
    private var url: URL { BackendHost.url(path: "/memory") }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            records = try JSONDecoder().decode([MemoryRecord].self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running? `cd backend && uv run python -m app.main`"
        }
        isLoading = false
    }

    private struct ForgetResponse: Decodable { let forgotten: Bool }

    /// Manual forgetting from the UI — same soft-delete Frank's own
    /// forget_memory tool uses (backend/app/db.py's deleted_at).
    ///
    /// Real gap found live (2026-09-06, systems audit §18 sweep): this
    /// used to remove the record from the local list unconditionally,
    /// regardless of whether the DELETE actually succeeded -- a network
    /// failure or a real "forgotten: false" (id already gone) would still
    /// show the memory as forgotten in the UI while it stayed in the
    /// database, with no way to notice or recover. Now only removes it
    /// locally once the backend confirms `forgotten: true`; any other
    /// outcome leaves the record in place and surfaces a real error.
    public func forget(_ record: MemoryRecord) async {
        forgetErrorMessage = nil
        var request = URLRequest(url: BackendHost.url(path: "/memory/\(record.id)"))
        request.httpMethod = "DELETE"
        do {
            let (data, _) = try await URLSession.shared.data(for: request)
            let response = try JSONDecoder().decode(ForgetResponse.self, from: data)
            guard response.forgotten else {
                forgetErrorMessage = "Couldn't forget that memory — it may already be gone."
                return
            }
            records.removeAll { $0.id == record.id }
        } catch {
            forgetErrorMessage = "Couldn't reach the backend — is it running?"
        }
    }
}
