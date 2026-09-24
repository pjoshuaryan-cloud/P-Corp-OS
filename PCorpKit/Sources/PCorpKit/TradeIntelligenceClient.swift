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
    @Published public private(set) var setupSuggestedTrade: SuggestedTrade?
    private var setupHistory: [Any] = []

    @Published public private(set) var chartMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isAnalyzingChart = false
    @Published public private(set) var chartAnalysisError: String?
    @Published public private(set) var chartSuggestedTrade: SuggestedTrade?
    private var chartHistory: [Any] = []

    @Published public private(set) var signalMessages: [TradeIntelligenceMessage] = []
    @Published public private(set) var isGeneratingSignal = false
    @Published public private(set) var signalError: String?
    @Published public private(set) var signalSuggestedTrade: SuggestedTrade?
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

    @Published public private(set) var proposals: [TradeProposal] = []
    @Published public private(set) var isLoadingProposals = false
    @Published public private(set) var proposalsError: String?

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
            setupSuggestedTrade = parseSuggestedTrade(json)
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
            setupSuggestedTrade = parseSuggestedTrade(json)
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
        setupSuggestedTrade = nil
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
            chartSuggestedTrade = parseSuggestedTrade(json)
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
            chartSuggestedTrade = parseSuggestedTrade(json)
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
        chartSuggestedTrade = nil
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
            signalSuggestedTrade = parseSuggestedTrade(json)
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
            signalSuggestedTrade = parseSuggestedTrade(json)
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
        signalSuggestedTrade = nil
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

    /// "Propose This Trade" (2026-09-22) -- `suggested_trade` is only
    /// ever present when the backend's extract_trade_suggestion found
    /// and validated a well-defined block in the reply; absent or null
    /// otherwise. Returning nil for anything that doesn't decode cleanly
    /// (same fail-closed posture as the backend side) rather than
    /// showing a partial/garbled suggestion.
    private func parseSuggestedTrade(_ json: [String: Any]) -> SuggestedTrade? {
        guard let dict = json["suggested_trade"] as? [String: Any], JSONSerialization.isValidJSONObject(dict),
              let data = try? JSONSerialization.data(withJSONObject: dict)
        else { return nil }
        return try? JSONDecoder().decode(SuggestedTrade.self, from: data)
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

    // MARK: - Trade Proposals (approval-gated execution, 2026-09-22)
    //
    // Josh fills TradeProposalDraft in himself from a Trade Setup reply
    // he's already read -- no auto-parsing of numbers out of the LLM's
    // prose (see the plan doc's own explicit deferral of that). Approve/
    // reject are the only actions that ever let a proposal reach the
    // real account, and only via a separate Mac-only sync loop + MQL5
    // bridge EA neither of which this client talks to directly.

    private struct ProposalsListResponse: Decodable { let proposals: [TradeProposal] }
    private struct ProposalCreateResponse: Decodable { let id: Int }
    private struct ProposalApproveResponse: Decodable { let approved: Bool; let localNodeOnline: Bool
        enum CodingKeys: String, CodingKey { case approved; case localNodeOnline = "local_node_online" }
    }

    /// Automated hourly market scan (2026-09-22) -- only ever creates an
    /// inert, pending proposal, same as one Josh types himself; this is
    /// purely the in-app "something's ready to look at" signal he asked
    /// for instead of a push notification (which needs a paid Apple
    /// Developer account he's declined). Matches main.py's own
    /// MARKET_SCAN_REASONING_PREFIX exactly -- a plain string prefix,
    /// not a separate column, so this is the one place both sides need
    /// to agree on that literal text.
    public static let scanProposalReasoningPrefix = "[Automated hourly scan] "

    public var pendingScanProposalCount: Int {
        proposals.filter { $0.status == "pending" && $0.reasoning.hasPrefix(Self.scanProposalReasoningPrefix) }.count
    }

    public func fetchProposals(status: String? = nil) async {
        isLoadingProposals = true
        proposalsError = nil
        var path = "/trade-intelligence/proposals"
        if let status { path += "?status=\(status)" }
        do {
            let (data, _) = try await URLSession.shared.data(from: url(path))
            proposals = try JSONDecoder().decode(ProposalsListResponse.self, from: data).proposals
        } catch {
            proposalsError = "Couldn't reach the backend — is it running?"
        }
        isLoadingProposals = false
    }

    /// Returns the new proposal's id on success, so a "Propose This
    /// Trade" button can confirm and clear its own form.
    public func createProposal(_ draft: TradeProposalDraft) async -> Int? {
        isLoadingProposals = true
        proposalsError = nil
        var request = URLRequest(url: url("/trade-intelligence/proposals"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(draft)
        var newId: Int?
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                proposalsError = errorMessage(from: data, http: http)
            } else {
                newId = try? JSONDecoder().decode(ProposalCreateResponse.self, from: data).id
            }
        } catch {
            proposalsError = "Couldn't reach the backend — is it running?"
        }
        isLoadingProposals = false
        if newId != nil { await fetchProposals(status: "pending") }
        return newId
    }

    /// Returns whether the Mac (and so the execution bridge) is online
    /// right now, per the backend's own local_node heartbeat check --
    /// the approval itself always succeeds; this is just honest,
    /// immediate feedback instead of a silently-stuck approval when the
    /// Mac happens to be asleep or closed.
    @discardableResult
    public func approveProposal(id: Int) async -> Bool {
        var request = URLRequest(url: url("/trade-intelligence/proposals/\(id)/approve"))
        request.httpMethod = "POST"
        var localNodeOnline = false
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                proposalsError = errorMessage(from: data, http: http)
            } else {
                localNodeOnline = (try? JSONDecoder().decode(ProposalApproveResponse.self, from: data).localNodeOnline) ?? false
            }
        } catch {
            proposalsError = "Couldn't reach the backend — is it running?"
        }
        await fetchProposals()
        return localNodeOnline
    }

    public func rejectProposal(id: Int) async {
        var request = URLRequest(url: url("/trade-intelligence/proposals/\(id)/reject"))
        request.httpMethod = "POST"
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            proposalsError = "Couldn't reach the backend — is it running?"
        }
        await fetchProposals()
    }

    public func deleteProposal(id: Int) async {
        var request = URLRequest(url: url("/trade-intelligence/proposals/\(id)"))
        request.httpMethod = "DELETE"
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            proposalsError = "Couldn't reach the backend — is it running?"
        }
        await fetchProposals()
    }
}
