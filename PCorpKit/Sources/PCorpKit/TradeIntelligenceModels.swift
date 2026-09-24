import Foundation

/// Fixed vocabularies, not freeform text -- mirrors backend/app/
/// trade_intelligence_db.py's SETUP_TAGS/TIMEFRAMES exactly, keeps
/// Trade Breakdown's pattern-grouping reliable at scale.
public let setupTagOptions = ["trend_continuation", "reversal", "breakout", "range_bound", "news_event", "other"]
public let timeframeOptions = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

/// One turn in a real Trade Intelligence conversation (2026-09-21, "I
/// want to be able to respond"). Purely a display model -- the real
/// conversation state the backend needs (Anthropic's own message/content-
/// block shape) is an opaque JSON blob TradeIntelligenceClient threads
/// through untouched; this struct never needs to represent that shape,
/// only what's shown on screen. `imageDataList` is never resent after
/// the turn that attached it -- it's cached here purely so the UI can
/// keep showing the user's own thumbnails in the thread.
public struct TradeIntelligenceMessage: Identifiable {
    public let id = UUID()
    public let role: String
    public let text: String
    public let imageDataList: [Data]

    public init(role: String, text: String, imageDataList: [Data] = []) {
        self.role = role
        self.text = text
        self.imageDataList = imageDataList
    }
}

public struct Trade: Identifiable, Decodable {
    public let id: Int
    public let symbol: String
    public let direction: String
    public let entryPrice: Double
    public let exitPrice: Double?
    public let entryTimestamp: String
    public let exitTimestamp: String?
    public let size: Double
    public let pnl: Double?
    public let setupTag: String
    public let timeframe: String
    public let screenshotPath: String?
    public let notes: String?
    public let aiAnalysis: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, symbol, direction, size, pnl, notes
        case entryPrice = "entry_price"
        case exitPrice = "exit_price"
        case entryTimestamp = "entry_timestamp"
        case exitTimestamp = "exit_timestamp"
        case setupTag = "setup_tag"
        case timeframe
        case screenshotPath = "screenshot_path"
        case aiAnalysis = "ai_analysis"
        case createdAt = "created_at"
    }
}

/// The add-trade form's payload -- a separate Encodable type from `Trade`
/// (which is Decodable, read-only client-side) since the form never has
/// an id/createdAt to send.
public struct TradeDraft: Encodable {
    public var symbol: String
    public var direction: String
    public var entryPrice: Double
    public var entryTimestamp: String
    public var size: Double
    public var setupTag: String
    public var timeframe: String
    public var exitPrice: Double?
    public var exitTimestamp: String?
    public var pnl: Double?
    public var screenshotPath: String?
    public var notes: String?
    public var aiAnalysis: String?

    public init(
        symbol: String, direction: String, entryPrice: Double, entryTimestamp: String, size: Double,
        setupTag: String, timeframe: String, exitPrice: Double? = nil, exitTimestamp: String? = nil,
        pnl: Double? = nil, screenshotPath: String? = nil, notes: String? = nil, aiAnalysis: String? = nil
    ) {
        self.symbol = symbol
        self.direction = direction
        self.entryPrice = entryPrice
        self.entryTimestamp = entryTimestamp
        self.size = size
        self.setupTag = setupTag
        self.timeframe = timeframe
        self.exitPrice = exitPrice
        self.exitTimestamp = exitTimestamp
        self.pnl = pnl
        self.screenshotPath = screenshotPath
        self.notes = notes
        self.aiAnalysis = aiAnalysis
    }

    enum CodingKeys: String, CodingKey {
        case symbol, direction, size, pnl, notes
        case entryPrice = "entry_price"
        case entryTimestamp = "entry_timestamp"
        case setupTag = "setup_tag"
        case timeframe
        case exitPrice = "exit_price"
        case exitTimestamp = "exit_timestamp"
        case screenshotPath = "screenshot_path"
        case aiAnalysis = "ai_analysis"
    }
}

/// Matches trade_intelligence_db.py's _group_stats -- count/winRate/avgPnl/
/// totalPnl with no "group" key, used for the ungrouped "overall" totals.
public struct TradeBreakdownGroupStats: Decodable {
    public let count: Int
    public let winRate: Double
    public let avgPnl: Double
    public let totalPnl: Double

    enum CodingKeys: String, CodingKey {
        case count
        case winRate = "win_rate"
        case avgPnl = "avg_pnl"
        case totalPnl = "total_pnl"
    }
}

/// _grouped_by's shape -- _group_stats's same four fields plus the group
/// key itself (a setup_tag/timeframe/session name).
public struct TradeBreakdownGroup: Decodable, Identifiable {
    public var id: String { group }
    public let group: String
    public let count: Int
    public let winRate: Double
    public let avgPnl: Double
    public let totalPnl: Double

    enum CodingKeys: String, CodingKey {
        case group, count
        case winRate = "win_rate"
        case avgPnl = "avg_pnl"
        case totalPnl = "total_pnl"
    }
}

/// Approval-gated trade execution (2026-09-22) -- mirrors backend/app/
/// trade_proposals_db.py's own row shape exactly. Josh fills this in
/// himself from a Trade Setup reply he's already read (deliberately no
/// auto-parsing of numbers out of the LLM's free-form prose -- see the
/// plan doc's own "explicitly NOT doing this pass" note); this struct is
/// what that manual form submits and what the pending-approvals list
/// reads back.
public struct TradeProposalDraft: Encodable {
    public var symbol: String
    public var direction: String
    public var entryPrice: Double
    public var stopLoss: Double
    public var takeProfit: Double
    public var riskPct: Double
    public var reasoning: String
    public var computedLotsEstimate: Double?

    public init(
        symbol: String, direction: String, entryPrice: Double, stopLoss: Double, takeProfit: Double,
        riskPct: Double, reasoning: String, computedLotsEstimate: Double? = nil
    ) {
        self.symbol = symbol
        self.direction = direction
        self.entryPrice = entryPrice
        self.stopLoss = stopLoss
        self.takeProfit = takeProfit
        self.riskPct = riskPct
        self.reasoning = reasoning
        self.computedLotsEstimate = computedLotsEstimate
    }

    enum CodingKeys: String, CodingKey {
        case symbol, direction, reasoning
        case entryPrice = "entry_price"
        case stopLoss = "stop_loss"
        case takeProfit = "take_profit"
        case riskPct = "risk_pct"
        case computedLotsEstimate = "computed_lots_estimate"
    }
}

public struct TradeProposal: Identifiable, Decodable {
    public let id: Int
    public let symbol: String
    public let direction: String
    public let entryPrice: Double
    public let stopLoss: Double
    public let takeProfit: Double
    public let riskPct: Double
    public let computedLotsEstimate: Double?
    public let reasoning: String
    public let status: String
    public let createdAt: String
    public let resolvedAt: String?
    public let executedTicket: String?
    public let executedResult: String?

    enum CodingKeys: String, CodingKey {
        case id, symbol, direction, status, reasoning
        case entryPrice = "entry_price"
        case stopLoss = "stop_loss"
        case takeProfit = "take_profit"
        case riskPct = "risk_pct"
        case computedLotsEstimate = "computed_lots_estimate"
        case createdAt = "created_at"
        case resolvedAt = "resolved_at"
        case executedTicket = "executed_ticket"
        case executedResult = "executed_result"
    }
}

/// "Propose This Trade" (2026-09-22) -- a structured suggestion the
/// Trade Intelligence Agent optionally includes in a Setup/Chart/Signal
/// reply when it has real, specific numbers (backend/app/
/// trade_intelligence_agent.py's extract_trade_suggestion parses a
/// well-defined fenced block, never free-form prose). Pre-fills the
/// Propose tab's form -- still fully editable there, never submitted
/// automatically.
public struct SuggestedTrade: Decodable {
    public let symbol: String
    public let direction: String
    public let entryPrice: Double
    public let stopLoss: Double
    public let takeProfit: Double
    public let riskPct: Double

    enum CodingKeys: String, CodingKey {
        case symbol, direction
        case entryPrice = "entry_price"
        case stopLoss = "stop_loss"
        case takeProfit = "take_profit"
        case riskPct = "risk_pct"
    }
}

public struct TradeBreakdownStats: Decodable {
    public let totalTrades: Int
    public let closedTrades: Int
    public let overall: TradeBreakdownGroupStats
    public let bySetupTag: [TradeBreakdownGroup]
    public let byTimeframe: [TradeBreakdownGroup]
    public let bySession: [TradeBreakdownGroup]

    enum CodingKeys: String, CodingKey {
        case totalTrades = "total_trades"
        case closedTrades = "closed_trades"
        case overall
        case bySetupTag = "by_setup_tag"
        case byTimeframe = "by_timeframe"
        case bySession = "by_session"
    }
}
