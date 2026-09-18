import Foundation

/// Plain REST fetch for GET /trading-division/dashboard -- same one-shot
/// pattern as AlphaModeDashboardClient, backing the "Trading Division"
/// section (previously a generic unbuilt placeholder, deliberately left
/// that way until Joshua explicitly asked to override the documented
/// blocker -- see backend/app/trading_division.py's docstring).
@MainActor
public final class TradingDivisionClient: ObservableObject {
    @Published public private(set) var dashboard: TradingDivisionDashboard?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?
    /// Separate loading/result/error state from the dashboard fetch
    /// above (2026-09-18, "make everything more...interactive") -- a
    /// live web_search/web_fetch call genuinely takes several real
    /// seconds, materially slower than the plain dashboard GET, so it
    /// gets its own indicator rather than reusing isLoading and making
    /// the whole tab look like it's still doing its normal fast fetch.
    @Published public private(set) var holdingUpdate: String?
    @Published public private(set) var isFetchingHoldingUpdate = false
    @Published public private(set) var holdingUpdateError: String?

    public init() {}

    private var url: URL { BackendHost.url(path: "/trading-division/dashboard") }
    private var holdingUpdateURL: URL { BackendHost.url(path: "/trading-division/holding-update") }

    public func fetch() async {
        isLoading = true
        errorMessage = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            dashboard = try JSONDecoder().decode(TradingDivisionDashboard.self, from: data)
        } catch {
            errorMessage = "Couldn't reach the backend — is it running?"
        }
        isLoading = false
    }

    private struct HoldingUpdateResponse: Decodable { let update: String }

    /// A real live call (web_search + web_fetch server-side), not a
    /// cached number -- can genuinely take 10-20+ real seconds, unlike
    /// every other fetch in this app. No retry/backoff here deliberately
    /// -- this is a manual, on-demand action Josh explicitly triggers,
    /// not a background poll that should quietly retry on its own.
    public func fetchHoldingUpdate() async {
        isFetchingHoldingUpdate = true
        holdingUpdateError = nil
        var request = URLRequest(url: holdingUpdateURL)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                holdingUpdateError = "Request failed (\(http.statusCode))."
            } else {
                holdingUpdate = try JSONDecoder().decode(HoldingUpdateResponse.self, from: data).update
            }
        } catch {
            holdingUpdateError = "Couldn't reach the backend — is it running?"
        }
        isFetchingHoldingUpdate = false
    }
}
