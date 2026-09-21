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
///
/// Real conversations (2026-09-21, "I want to be able to respond"): each
/// capability's `*History` property is an opaque JSON blob (Anthropic's
/// own message/content-block shape) this client threads through
/// unmodified -- built with plain `[String: Any]`/JSONSerialization
/// rather than Codable, since it never needs to understand that shape,
/// only round-trip it. `*Messages` is the display-only model the UI
/// actually renders (TradeIntelligenceMessage, TradeIntelligenceModels.swift).
@MainActor
public final class TradeIntelligenceClient: ObservableObject {
    @Published public private(set) var setupMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isAnalyzingSetup = false
    @Published public private(set) var setupError: String?
    private var setupHistory: [Any] = []

    @Published public private(set) var chartMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isAnalyzingChart = false
    @Published public private(set) var chartAnalysisError: String?
    private var chartHistory: [Any] = []

    @Published public private(set) var signalMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isGeneratingSignal = false
    @Published public private(set) var signalError: String?
    private var signalHistory: [Any] = []

    @Published public private(set) var positionMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isReviewingPosition = false
    @Published public private(set) var positionReviewError: String?
    private var positionHistory: [Any] = []

    @Published public private(set) var breakdownMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var breakdownStats: TradeBreakdownStats?
    @Published public private(set) var isLoadingBreakdown = false
    @Published public private(set) var breakdownError: String?
    private var breakdownHistory: [Any] = []

    @Published public private(set) var trades: [Trade] = []
    @Published public private(set) var isLoadingTrades = false
    @Published public private(set) var tradesError: String?

    public init() {}

    private func url(_ path: String) -> URL { BackendHost.url(path: path) }

    /// All four Claude-backed calls genuinely take real seconds (web
    /// search + extended thinking, confirmed live -- one test run took
    /// close to a minute) -- a generous timeout, same "manual, on-demand,
    /// no silent retry" reasoning as TradingDivisionClient's own
    /// fetchHoldingUpdate.
    private static let advisoryTimeout: TimeInterval = 90

    private enum ConversationalOutcome {
        case success([String: Any])
        case failure(String)
    }

    private func postConversational(path: String, body: [String: Any]) async -> ConversationalOutcome {
        var request = URLRequest(url: url(path))
        request.httpMethod = "POST"
        request.timeoutInterval = Self.advisoryTimeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
                return .failure(detail ?? "Request failed (\(http.statusCode)).")
            }
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure("Unexpected response from the backend.")
            }
            return .success(json)
        } catch {
            return .failure("Couldn't reach the backend — is it running?")
        }
    }

    // MARK: - Trade Setup (the comprehensive "should I take this trade" flow)

    /// images may be empty here (unlike Chart Analysis, where at least
    /// one is required) -- Josh can ask a pure text question with no
    /// chart. The backend always grounds the seed turn in his real
    /// account balance and real logged trade history; nothing extra
    /// needs sending from here for that.
    public func analyzeTradeSetup(images: [(data: Data, mediaType: String, filename: String)], symbol: String?, question: String?) async {
        isAnalyzingSetup = true
        setupError = nil
        let body: [String: Any] = [
            "images": images.map { ["media_type": $0.mediaType, "filename": $0.filename, "data": $0.data.base64EncodedString()] },
            "symbol": symbol ?? "",
            "question": question ?? "",
        ]
        switch await postConversational(path: "/trade-intelligence/setup", body: body) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                setupError = "Unexpected response from the backend."
                break
            }
            setupHistory = history
            let questionText = (question?.isEmpty == false) ? question! : "Where should I buy or sell, and why? How long should I hold? Where should I put my stop-loss?"
            setupMessages = [
                TradeIntelligenceMessage(role: "user", text: questionText, imageDataList: images.map { $0.data }),
                TradeIntelligenceMessage(role: "assistant", text: reply),
            ]
        case .failure(let message):
            setupError = message
        }
        isAnalyzingSetup = false
    }

    public func sendSetupFollowUp(_ text: String) async {
        isAnalyzingSetup = true
        setupError = nil
        setupMessages.append(TradeIntelligenceMessage(role: "user", text: text))
        switch await postConversational(path: "/trade-intelligence/setup", body: ["history": setupHistory, "message": text]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                setupError = "Unexpected response from the backend."
                break
            }
            setupHistory = history
            setupMessages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
        case .failure(let message):
            setupError = message
        }
        isAnalyzingSetup = false
    }

    public func resetSetup() {
        setupMessages = []
        setupHistory = []
        setupError = nil
    }

    // MARK: - Chart Analysis

    public func analyzeChart(images: [(data: Data, mediaType: String, filename: String)], symbol: String?, note: String?) async {
        isAnalyzingChart = true
        chartAnalysisError = nil
        let body: [String: Any] = [
            "images": images.map { ["media_type": $0.mediaType, "filename": $0.filename, "data": $0.data.base64EncodedString()] },
            "symbol": symbol ?? "",
            "note": note ?? "",
        ]
        switch await postConversational(path: "/trade-intelligence/chart-analysis", body: body) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                chartAnalysisError = "Unexpected response from the backend."
                break
            }
            chartHistory = history
            chartMessages = [
                TradeIntelligenceMessage(role: "user", text: note ?? "", imageDataList: images.map { $0.data }),
                TradeIntelligenceMessage(role: "assistant", text: reply),
            ]
        case .failure(let message):
            chartAnalysisError = message
        }
        isAnalyzingChart = false
    }

    public func sendChartFollowUp(_ text: String) async {
        isAnalyzingChart = true
        chartAnalysisError = nil
        chartMessages.append(TradeIntelligenceMessage(role: "user", text: text))
        switch await postConversational(path: "/trade-intelligence/chart-analysis", body: ["history": chartHistory, "message": text]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                chartAnalysisError = "Unexpected response from the backend."
                break
            }
            chartHistory = history
            chartMessages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
        case .failure(let message):
            chartAnalysisError = message
        }
        isAnalyzingChart = false
    }

    public func resetChart() {
        chartMessages = []
        chartHistory = []
        chartAnalysisError = nil
    }

    // MARK: - Trading Signals

    public func generateSignal(symbol: String) async {
        isGeneratingSignal = true
        signalError = nil
        switch await postConversational(path: "/trade-intelligence/signal", body: ["symbol": symbol]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                signalError = "Unexpected response from the backend."
                break
            }
            signalHistory = history
            signalMessages = [
                TradeIntelligenceMessage(role: "user", text: "Generate a signal for \(symbol)."),
                TradeIntelligenceMessage(role: "assistant", text: reply),
            ]
        case .failure(let message):
            signalError = message
        }
        isGeneratingSignal = false
    }

    public func sendSignalFollowUp(_ text: String) async {
        isGeneratingSignal = true
        signalError = nil
        signalMessages.append(TradeIntelligenceMessage(role: "user", text: text))
        switch await postConversational(path: "/trade-intelligence/signal", body: ["history": signalHistory, "message": text]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                signalError = "Unexpected response from the backend."
                break
            }
            signalHistory = history
            signalMessages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
        case .failure(let message):
            signalError = message
        }
        isGeneratingSignal = false
    }

    public func resetSignal() {
        signalMessages = []
        signalHistory = []
        signalError = nil
    }

    // MARK: - Position Review

    public func reviewPosition(
        symbol: String, direction: String, entryPrice: Double, size: Double, currentPrice: Double,
        stopLoss: Double?, takeProfit: Double?
    ) async {
        isReviewingPosition = true
        positionReviewError = nil
        var body: [String: Any] = [
            "symbol": symbol, "direction": direction, "entry_price": entryPrice,
            "size": size, "current_price": currentPrice,
        ]
        if let stopLoss { body["stop_loss"] = stopLoss }
        if let takeProfit { body["take_profit"] = takeProfit }
        switch await postConversational(path: "/trade-intelligence/position-review", body: body) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                positionReviewError = "Unexpected response from the backend."
                break
            }
            positionHistory = history
            positionMessages = [
                TradeIntelligenceMessage(role: "user", text: "Review my \(direction) \(symbol) position: entry \(entryPrice), size \(size), current \(currentPrice)."),
                TradeIntelligenceMessage(role: "assistant", text: reply),
            ]
        case .failure(let message):
            positionReviewError = message
        }
        isReviewingPosition = false
    }

    public func sendPositionFollowUp(_ text: String) async {
        isReviewingPosition = true
        positionReviewError = nil
        positionMessages.append(TradeIntelligenceMessage(role: "user", text: text))
        switch await postConversational(path: "/trade-intelligence/position-review", body: ["history": positionHistory, "message": text]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                positionReviewError = "Unexpected response from the backend."
                break
            }
            positionHistory = history
            positionMessages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
        case .failure(let message):
            positionReviewError = message
        }
        isReviewingPosition = false
    }

    public func resetPosition() {
        positionMessages = []
        positionHistory = []
        positionReviewError = nil
    }

    // MARK: - Trade Breakdown (CRUD + narration)

    private struct TradesListResponse: Decodable { let trades: [Trade] }
    private struct ErrorDetail: Decodable { let detail: String }

    private func errorMessage(from data: Data, http: HTTPURLResponse) -> String {
        (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode))."
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

    private func decodeStats(_ json: [String: Any]) -> TradeBreakdownStats? {
        guard let statsDict = json["stats"], JSONSerialization.isValidJSONObject(statsDict),
              let statsData = try? JSONSerialization.data(withJSONObject: statsDict)
        else { return nil }
        return try? JSONDecoder().decode(TradeBreakdownStats.self, from: statsData)
    }

    public func fetchBreakdown() async {
        isLoadingBreakdown = true
        breakdownError = nil
        switch await postConversational(path: "/trade-intelligence/trades/breakdown", body: [:]) {
        case .success(let json):
            guard let reply = json["reply"] as? String else {
                breakdownError = "Unexpected response from the backend."
                break
            }
            breakdownHistory = (json["history"] as? [Any]) ?? []
            breakdownStats = decodeStats(json)
            breakdownMessages = [TradeIntelligenceMessage(role: "assistant", text: reply)]
        case .failure(let message):
            breakdownError = message
        }
        isLoadingBreakdown = false
    }

    public func sendBreakdownFollowUp(_ text: String) async {
        isLoadingBreakdown = true
        breakdownError = nil
        breakdownMessages.append(TradeIntelligenceMessage(role: "user", text: text))
        switch await postConversational(path: "/trade-intelligence/trades/breakdown", body: ["history": breakdownHistory, "message": text]) {
        case .success(let json):
            guard let reply = json["reply"] as? String, let history = json["history"] as? [Any] else {
                breakdownError = "Unexpected response from the backend."
                break
            }
            breakdownHistory = history
            breakdownMessages.append(TradeIntelligenceMessage(role: "assistant", text: reply))
        case .failure(let message):
            breakdownError = message
        }
        isLoadingBreakdown = false
    }

    public func resetBreakdown() {
        breakdownMessages = []
        breakdownHistory = []
        breakdownStats = nil
        breakdownError = nil
    }
}
