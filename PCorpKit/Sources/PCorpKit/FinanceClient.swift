import Foundation

/// Plain REST fetch for GET /finance/dashboard -- same one-shot pattern
/// as JoshxClient/PersonalClient, backing the "Finance" section (Josh's
/// personal investment tracking -- see backend/app/finance_db.py's
/// docstring).
@MainActor
public final class FinanceClient: ObservableObject {
    @Published public private(set) var dashboard: FinanceDashboard?
    @Published public private(set) var concentration: FinanceConcentration?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private var url: URL { BackendHost.url(path: "/finance/dashboard") }

    private func url(path: String, extraItems: [URLQueryItem] = []) -> URL {
        BackendHost.url(path: path, extraQueryItems: extraItems)
    }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(FinanceDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        // Same cheap, purely local computation as the dashboard itself --
        // fetched alongside it every time, best-effort (a failure here
        // doesn't block the dashboard's own error handling above).
        do {
            let (data, _) = try await URLSession.shared.data(from: url(path: "/finance/concentration"))
            concentration = try JSONDecoder().decode(FinanceConcentration.self, from: data)
        } catch {
            concentration = nil
        }
        isLoading = false
    }

    /// Backs the new per-account history drill-down (2026-09-06, systems
    /// audit §4's date-range filtering). `from`/`to` are optional
    /// "YYYY-MM-DD" strings -- omitting both returns the full history.
    /// Throws on a real fetch/decode failure rather than returning `[]` --
    /// real gap found live (systems audit §18 sweep): a failed request
    /// and a genuinely empty period both read as "No snapshots logged in
    /// this period yet" with no way to tell them apart. Callers should
    /// catch and show a real "couldn't load" state instead.
    public func fetchHistory(accountId: Int, from: String? = nil, to: String? = nil) async throws -> [BalanceHistoryEntry] {
        var items = [URLQueryItem(name: "account_id", value: "\(accountId)")]
        if let from { items.append(URLQueryItem(name: "from", value: from)) }
        if let to { items.append(URLQueryItem(name: "to", value: to)) }
        let (data, _) = try await URLSession.shared.data(from: url(path: "/finance/history", extraItems: items))
        return try JSONDecoder().decode([BalanceHistoryEntry].self, from: data)
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

    private struct BalanceUpdatePayload: Encodable { let balance: Double }

    /// Backs Finance's inline-edit balances for the 4 manual accounts
    /// (2026-09-17, Editability Pass 1) -- wraps the same log_balance
    /// Frank's own LOG_FINANCE_BALANCE_TOOL already uses, so this reads
    /// as a real new snapshot (with its own recorded_at), not an
    /// overwrite of history. accountName is percent-encoded into the
    /// path since real account names contain spaces ("Liberty Stash").
    public func updateBalance(accountName: String, balance: Double) async {
        let encodedName = accountName.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? accountName
        var request = URLRequest(url: BackendHost.url(path: "/finance/accounts/\(encodedName)/balance"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(BalanceUpdatePayload(balance: balance))
        let writeError = await performWrite(request)
        await fetch()
        if let writeError { errorMessage = writeError }
    }
}
