import Foundation

/// Plain REST fetch for GET /joshx/dashboard -- same one-shot pattern as
/// PersonalClient/TradingDivisionClient, backing the "Joshx" section
/// (Josh's independent freelance creative business, completely separate
/// from Alpha Mode Media -- see backend/app/joshx_db.py's docstring).
///
/// Update (2026-08-31): gained two PATCH methods for the new project
/// detail view's status/payment-status editing -- the first UI-driven
/// writes in Joshx (every prior write happened via a Frank chat tool).
/// Same PATCH mechanics as TriggersClient.toggleRule (URLRequest, JSON
/// dict body, URLSession.shared.data(for:)), but simpler on the local-
/// state side: JoshxProject carries far more fields than
/// TriggerRuleSection did, so reconstructing a new struct here risks a
/// copy-paste field-omission bug for little real benefit (this is an
/// occasional deliberate edit, not a rapid-toggle control) -- fire the
/// PATCH, then refetch from the server either way, same as
/// TriggersClient's own "either is fine" degree of freedom.
@MainActor
public final class JoshxClient: ObservableObject {
    @Published public private(set) var dashboard: JoshxDashboard?
    @Published public private(set) var analytics: JoshxAnalytics?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL { BackendHost.url(path: "/joshx/dashboard") }

    private func url(path: String) -> URL { BackendHost.url(path: path) }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(JoshxDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        // Same cheap, purely local read-only computation as the dashboard
        // itself (no external network call, unlike Connected Apps' own
        // Supabase check) -- fetched alongside it every time, not gated
        // behind a separate control. Best-effort: a failure here doesn't
        // block the dashboard's own errorMessage/isLoading handling above.
        do {
            let (analyticsData, _) = try await URLSession.shared.data(from: url(path: "/joshx/analytics"))
            analytics = try JSONDecoder().decode(JoshxAnalytics.self, from: analyticsData)
        } catch {
            analytics = nil
        }
        isLoading = false
    }

    private struct ErrorDetail: Decodable { let detail: String }

    /// Real gap found live (2026-09-06, systems audit §18 sweep): every
    /// write method below used to discard the request's result entirely
    /// via `try?`, so a real backend rejection (main.py's own
    /// `HTTPException(400/404, detail: "...")`, an honest and specific
    /// reason) was silently thrown away -- indistinguishable from success
    /// to the user, who'd just see the UI not update as expected with no
    /// explanation. Returns the real detail string on any non-2xx
    /// response, or a network-failure message; `nil` means genuine
    /// success. Set on `errorMessage` *after* the follow-up `fetch()`
    /// call below, since fetch() itself unconditionally clears
    /// `errorMessage` at its own start.
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

    public func updateProjectStatus(id: Int, status: String) async {
        var request = URLRequest(url: url(path: "/joshx/projects/\(id)/status"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["status": status])
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func updateProjectPaymentStatus(id: Int, paymentStatus: String) async {
        var request = URLRequest(url: url(path: "/joshx/projects/\(id)/payment-status"))
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["payment_status": paymentStatus])
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    /// Backs the LEADS section's delete action (2026-08-31) -- a dormant
    /// lead that never got closed out (see joshx_db.py's add_project doc
    /// comment for why one can linger indefinitely). Soft delete on the
    /// backend (leads.deleted_at), same DELETE-then-refetch shape as the
    /// PATCH methods above.
    public func deleteLead(id: Int) async {
        var request = URLRequest(url: url(path: "/joshx/leads/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    /// "Everything must be deletable if needed" (2026-08-31) -- same
    /// shape as deleteLead, for CLIENTS/PROJECTS.
    public func deleteClient(id: Int) async {
        var request = URLRequest(url: url(path: "/joshx/clients/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }

    public func deleteProject(id: Int) async {
        var request = URLRequest(url: url(path: "/joshx/projects/\(id)"))
        request.httpMethod = "DELETE"
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }
}
