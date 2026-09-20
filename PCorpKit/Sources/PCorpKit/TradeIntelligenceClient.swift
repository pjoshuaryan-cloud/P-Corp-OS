import Foundation

/// Backs the Trade Intelligence section inside Trading Division --
/// Chart Analysis, Trading Signals, Position Review, and Trade Breakdown.
/// A separate ObservableObject from TradingDivisionClient, not an
/// extension of it: these four capabilities need roughly 15 published
/// properties (loading/result/error x3 Claude calls, plus trades list/
/// save/delete/breakdown state) against TradingDivisionClient's own 9 --
/// keeping "read-only reporting glue" and "advisory-agent + persistence
/// glue" in separate classes matches the whole structural-separation
/// point of this feature (see AdvisoryDisclaimerBanner.swift and
/// backend/app/trade_intelligence_agent.py's own docstrings).
@MainActor
public final class TradeIntelligenceClient: ObservableObject {
    @Published public private(set) var chartAnalysis: String?
    @Published public private(set) var isAnalyzingChart = false
    @Published public private(set) var chartAnalysisError: String?

    @Published public private(set) var signal: String?
    @Published public private(set) var isGeneratingSignal = false
    @Published public private(set) var signalError: String?

    @Published public private(set) var positionReview: String?
    @Published public private(set) var isReviewingPosition = false
    @Published public private(set) var positionReviewError: String?

    @Published public private(set) var trades: [Trade] = []
    @Published public private(set) var isLoadingTrades = false
    @Published public private(set) var tradesError: String?

    @Published public private(set) var breakdown: TradeBreakdown?
    @Published public private(set) var isLoadingBreakdown = false
    @Published public private(set) var breakdownError: String?

    public init() {}

    private func url(_ path: String) -> URL { BackendHost.url(path: path) }

    private struct ChartAnalysisResponse: Decodable { let analysis: String }
    private struct SignalResponse: Decodable { let signal: String }
    private struct PositionReviewResponse: Decodable { let review: String }
    private struct TradesListResponse: Decodable { let trades: [Trade] }
    private struct ErrorDetail: Decodable { let detail: String }

    private func errorMessage(from data: Data, http: HTTPURLResponse) -> String {
        (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode))."
    }

    /// All four Claude-backed calls genuinely take real seconds (web
    /// search + extended thinking, confirmed live -- one test run took
    /// close to a minute) -- a generous timeout, same "manual, on-demand,
    /// no silent retry" reasoning as TradingDivisionClient's own
    /// fetchHoldingUpdate.
    private static let advisoryTimeout: TimeInterval = 90

    public func analyzeChart(imageData: Data, mediaType: String, filename: String, symbol: String?, note: String?) async {
        isAnalyzingChart = true
        chartAnalysisError = nil
        var request = URLRequest(url: url("/trade-intelligence/chart-analysis"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.advisoryTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode([
            "media_type": mediaType,
            "filename": filename,
            "data": imageData.base64EncodedString(),
            "symbol": symbol ?? "",
            "note": note ?? "",
        ])
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                chartAnalysisError = errorMessage(from: data, http: http)
            } else {
                chartAnalysis = try JSONDecoder().decode(ChartAnalysisResponse.self, from: data).analysis
            }
        } catch {
            chartAnalysisError = "Couldn't reach the backend — is it running?"
        }
        isAnalyzingChart = false
    }

    public func generateSignal(symbol: String) async {
        isGeneratingSignal = true
        signalError = nil
        var request = URLRequest(url: url("/trade-intelligence/signal"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.advisoryTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(["symbol": symbol])
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                signalError = errorMessage(from: data, http: http)
            } else {
                signal = try JSONDecoder().decode(SignalResponse.self, from: data).signal
            }
        } catch {
            signalError = "Couldn't reach the backend — is it running?"
        }
        isGeneratingSignal = false
    }

    public func reviewPosition(
        symbol: String, direction: String, entryPrice: Double, size: Double, currentPrice: Double,
        stopLoss: Double?, takeProfit: Double?
    ) async {
        isReviewingPosition = true
        positionReviewError = nil
        var request = URLRequest(url: url("/trade-intelligence/position-review"))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.advisoryTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = [
            "symbol": symbol, "direction": direction, "entry_price": entryPrice,
            "size": size, "current_price": currentPrice,
        ]
        if let stopLoss { body["stop_loss"] = stopLoss }
        if let takeProfit { body["take_profit"] = takeProfit }
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                positionReviewError = errorMessage(from: data, http: http)
            } else {
                positionReview = try JSONDecoder().decode(PositionReviewResponse.self, from: data).review
            }
        } catch {
            positionReviewError = "Couldn't reach the backend — is it running?"
        }
        isReviewingPosition = false
    }

    public func fetchTrades() async {
        isLoadingTrades = true
        tradesError = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/trade-intelligence/trades"))
            trades = try JSONDecoder().decode(TradesListResponse.self, from: data).trades
        } catch {
            tradesError = "Couldn't reach the backend — is it running?"
        }
        isLoadingTrades = false
    }

    /// Returns whether the save succeeded, so the caller (AsyncButton's
    /// action) can decide whether to clear the form / show a toast.
    public func addTrade(_ draft: TradeDraft) async -> Bool {
        isLoadingTrades = true
        tradesError = nil
        var request = URLRequest(url: url("/trade-intelligence/trades"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(draft)
        var succeeded = false
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                tradesError = errorMessage(from: data, http: http)
            } else {
                succeeded = true
            }
        } catch {
            tradesError = "Couldn't reach the backend — is it running?"
        }
        isLoadingTrades = false
        if succeeded { await fetchTrades() }
        return succeeded
    }

    public func deleteTrade(id: Int) async {
        var request = URLRequest(url: url("/trade-intelligence/trades/\(id)"))
        request.httpMethod = "DELETE"
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            tradesError = "Couldn't reach the backend — is it running?"
        }
        await fetchTrades()
    }

    public func fetchBreakdown() async {
        isLoadingBreakdown = true
        breakdownError = nil
        do {
            let (data, _) = try await URLSession.shared.data(from: url("/trade-intelligence/trades/breakdown"))
            breakdown = try JSONDecoder().decode(TradeBreakdown.self, from: data)
        } catch {
            breakdownError = "Couldn't reach the backend — is it running?"
        }
        isLoadingBreakdown = false
    }
}
