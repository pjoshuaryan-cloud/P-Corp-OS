import Foundation

/// Backs GET /insights — real, computed insights (overdue/upcoming
/// tasks and invoices, app/insights.py), not the hardcoded placeholder
/// text this used to be. `id` is a local UUID, not part of the decoded
/// JSON (excluded from CodingKeys, Swift's synthesized decoder falls
/// back to its default-value initializer) — this list is ephemeral,
/// recomputed on every fetch, nothing to reference by a stable ID.
public struct InsightItem: Identifiable, Decodable {
    public let id = UUID()
    public let systemImage: String
    public let title: String
    public let detail: String
    /// Which nav section this relates to — same honest-routing pattern as
    /// QuickAction, so clicking an insight isn't a dead end.
    public let targetNavTitle: String
    /// "risk" / "follow_up" / "opportunity" (2026-08-20, Face-Lift brief's
    /// insight-type indicators) — a real classification of which existing
    /// backend.app.insights.py generator produced this row (overdue =
    /// risk, due-soon/outreach = follow_up, leads/quotes = opportunity),
    /// not an invented category layered on top of real data.
    public let category: String

    enum CodingKeys: String, CodingKey {
        case systemImage = "icon"
        case title, detail, category
        case targetNavTitle = "target_nav_title"
    }
}

/// "The Brief" (2026-08-20, Face-Lift item 09) -- GET /brief. Same shape
/// as InsightItem in spirit, but a distinct type rather than reusing it:
/// backend/app/brief.py normalizes Situation Room alerts into this same
/// shape for "What Matters," and those don't carry a real target section
/// (situation_room.py's own alerts never did), so targetNavTitle has to
/// be optional here where InsightItem's isn't.
public struct BriefItem: Identifiable, Decodable {
    public let id = UUID()
    public let systemImage: String
    public let title: String
    public let detail: String
    public let targetNavTitle: String?
    public let category: String

    enum CodingKeys: String, CodingKey {
        case systemImage = "icon"
        case title, detail, category
        case targetNavTitle = "target_nav_title"
    }
}

/// A single real, already-logged tool call (backend/app/audit_db.py) --
/// "What Changed" is literally this, not a separate invented activity
/// feed. `result` is already the human-readable summary
/// (record_tool_call's own callers write it that way, e.g. "Added goal:
/// Read more books") -- the raw tool input JSON isn't decoded here since
/// nothing in the UI needs to show it.
public struct BriefActivity: Identifiable, Decodable {
    public let id: Int
    public let toolName: String
    public let result: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, result
        case toolName = "tool_name"
        case createdAt = "created_at"
    }
}

public struct Brief: Decodable {
    public let whatMatters: [BriefItem]
    public let whatChanged: [BriefActivity]
    public let whatFrankRecommends: [BriefItem]
    public let whatCanWait: [BriefItem]

    enum CodingKeys: String, CodingKey {
        case whatMatters = "what_matters"
        case whatChanged = "what_changed"
        case whatFrankRecommends = "what_frank_recommends"
        case whatCanWait = "what_can_wait"
    }
}

/// Backs GET /situation-room (app/situation_room.py) — a stricter tier
/// than InsightItem above, deliberately no icon field since these render
/// as a single banner, not individual iconed rows like the Insights card.
public struct SituationRoomAlert: Identifiable, Decodable {
    public let id = UUID()
    public let title: String
    public let detail: String
    public let targetNavTitle: String

    enum CodingKeys: String, CodingKey {
        case title, detail
        case targetNavTitle = "target_nav_title"
    }
}

/// A row in the conversation switcher — backs GET /conversations. `id`
/// matches the real backend conversation_id (not a client-generated UUID)
/// since it has to round-trip to POST /conversations/{id}/activate.
public struct ConversationSummary: Identifiable, Decodable {
    public let id: Int
    public let createdAt: String
    public let firstMessage: String?
    public let messageCount: Int
    /// When this conversation was last actually used, not just created —
    /// what the history browser sorts/groups by, so a conversation reopened
    /// and continued today surfaces above one merely created earlier but
    /// untouched since.
    public let lastMessageAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case createdAt = "created_at"
        case firstMessage = "first_message"
        case messageCount = "message_count"
        case lastMessageAt = "last_message_at"
    }
}

/// Mirrors backend/app/db.py's `memory_records` table — durable facts Frank
/// has saved via the `save_memory` tool, distinct from raw conversation
/// history. Fetched read-only from GET /memory.
public struct MemoryRecord: Identifiable, Decodable {
    public let id: Int
    public let type: String
    public let title: String
    public let content: String
    public let sensitive: Bool
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, type, title, content, sensitive
        case createdAt = "created_at"
    }
}

/// Mirrors backend/app/operations_db.py's `tasks` table (excluding done
/// ones) — general, cross-business tasks Frank creates via add_task,
/// made visible read-only from GET /operations/tasks, same pattern as
/// MemoryRecord/GET /memory.
public struct OperationsTask: Identifiable, Decodable {
    public let id: Int
    public let title: String
    public let status: String
    public let area: String?
    public let dueDate: String?
    public let notes: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, status, area, notes
        case dueDate = "due_date"
        case createdAt = "created_at"
    }
}

/// Mirrors backend/app/agents_registry.py's AGENTS list -- the single
/// source of truth for which specialist agents exist, fetched from
/// GET /agents so the Agents section stays current as new agent modules
/// are added, without hand-editing a SwiftUI card per agent.
public struct Agent: Identifiable, Decodable {
    public let id: String
    public let name: String
    public let icon: String
    public let tagline: String
    public let detail: String
    public let status: String
}

/// Backs GET /alpha-mode/dashboard (app/alpha_mode_supabase.py's
/// dashboard_snapshot) -- real data from the actual Alpha Mode Media
/// Admin Supabase database, not placeholder content. `id` is a local
/// UUID, same reasoning as InsightItem: this list is recomputed on
/// every fetch, nothing to reference by a stable ID client-side.
public struct AlphaModeProject: Identifiable, Decodable {
    public let id = UUID()
    public let client: String
    public let projectName: String?
    public let stage: String
    public let dueDate: String?

    enum CodingKeys: String, CodingKey {
        case client
        case projectName = "project_name"
        case stage
        case dueDate = "due_date"
    }
}

public struct AlphaModeInvoiceProject: Decodable {
    public let client: String
    public let projectName: String?

    enum CodingKeys: String, CodingKey {
        case client
        case projectName = "project_name"
    }
}

public struct AlphaModeInvoice: Identifiable, Decodable {
    public let id = UUID()
    public let amount: Double
    public let status: String
    public let dueDate: String?
    public let project: AlphaModeInvoiceProject

    enum CodingKeys: String, CodingKey {
        case amount, status
        case dueDate = "due_date"
        case project = "projects"
    }
}

public struct AlphaModeLead: Identifiable, Decodable {
    public let id = UUID()
    public let client: String
    public let temperature: String
    public let qualificationScore: Int?

    enum CodingKeys: String, CodingKey {
        case client, temperature
        case qualificationScore = "qualification_score"
    }
}

public struct AlphaModeDashboard: Decodable {
    public let projects: [AlphaModeProject]
    public let invoices: [AlphaModeInvoice]
    public let leads: [AlphaModeLead]
}

/// A backtest or walk-forward run from the trading robot's own real
/// results database (research.sqlite, a completely separate repo -- see
/// backend/app/trading_division.py's docstring for the read-only
/// boundary). Both run types share the same shape, differentiated only
/// by which GET /trading-division/dashboard array they arrive in.
public struct TradingDivisionRun: Identifiable, Decodable {
    public let id = UUID()
    public let runId: Int
    public let symbol: String?
    public let entryTimeframe: String?
    public let startAt: String?
    public let endAt: String?
    public let createdAt: String
    public let totalTrades: Int?
    public let winRatePct: Double?
    public let profitFactor: Double?
    public let maxDrawdownPct: Double?
    public let totalPnl: Double?

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case symbol
        case entryTimeframe = "entry_timeframe"
        case startAt = "start_at"
        case endAt = "end_at"
        case createdAt = "created_at"
        case totalTrades = "total_trades"
        case winRatePct = "win_rate_pct"
        case profitFactor = "profit_factor"
        case maxDrawdownPct = "max_drawdown_pct"
        case totalPnl = "total_pnl"
    }
}

public struct TradingDivisionMonteCarloRun: Identifiable, Decodable {
    public let id = UUID()
    public let runId: Int
    public let createdAt: String
    public let numSimulations: Int
    public let probabilityOfRuinPct: Double
    public let finalBalanceP5: Double?
    public let finalBalanceP50: Double?
    public let finalBalanceP95: Double?
    public let maxDrawdownP50: Double?
    public let maxDrawdownP95: Double?

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case createdAt = "created_at"
        case numSimulations = "num_simulations"
        case probabilityOfRuinPct = "probability_of_ruin_pct"
        case finalBalanceP5 = "final_balance_p5"
        case finalBalanceP50 = "final_balance_p50"
        case finalBalanceP95 = "final_balance_p95"
        case maxDrawdownP50 = "max_drawdown_p50"
        case maxDrawdownP95 = "max_drawdown_p95"
    }
}

public struct TradingDivisionDashboard: Decodable {
    public let backtests: [TradingDivisionRun]
    public let walkforwardRuns: [TradingDivisionRun]
    public let montecarloRuns: [TradingDivisionMonteCarloRun]

    enum CodingKeys: String, CodingKey {
        case backtests
        case walkforwardRuns = "walkforward_runs"
        case montecarloRuns = "montecarlo_runs"
    }
}

/// A personal goal (backend/app/personal_db.py) -- deliberately narrow
/// scope (goals/habits only, no marriage/health/family), see that
/// file's own docstring for why.
public struct PersonalGoal: Identifiable, Decodable {
    public let id: Int
    public let title: String
    public let status: String
    public let targetDate: String?
    public let notes: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, status, notes
        case targetDate = "target_date"
        case createdAt = "created_at"
    }
}

public struct PersonalHabit: Identifiable, Decodable {
    public let id: Int
    public let title: String
    public let cadence: String?
    public let notes: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, title, cadence, notes
        case createdAt = "created_at"
    }
}

public struct PersonalDashboard: Decodable {
    public let goals: [PersonalGoal]
    public let habits: [PersonalHabit]
}

/// Mirrors backend/app/db.py's get_focus_objective() -- the War Room's
/// Mission Status "Focus: ..." line, fetched from GET /focus. Both
/// fields are nullable: no objective set yet is a real, honest state,
/// not an error.
public struct FocusObjective: Decodable {
    public let objective: String?
    public let setAt: String?

    enum CodingKeys: String, CodingKey {
        case objective
        case setAt = "set_at"
    }
}

/// Mirrors backend/app/automations_registry.py's AGENTS list -- the
/// configured automation rules, fetched from GET /automations/rules.
public struct AutomationRule: Identifiable, Decodable {
    public let id: String
    public let triggerTool: String
    public let name: String
    public let description: String
    public let agent: String

    enum CodingKeys: String, CodingKey {
        case id, name, description, agent
        case triggerTool = "trigger_tool"
    }
}

/// Mirrors backend/app/automations_db.py's automation_runs table -- real
/// firing history, fetched from GET /automations/runs.
public struct AutomationRun: Identifiable, Decodable {
    public let id: Int
    public let ruleId: String
    public let ruleName: String
    public let triggerSummary: String?
    public let result: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, result
        case ruleId = "rule_id"
        case ruleName = "rule_name"
        case triggerSummary = "trigger_summary"
        case createdAt = "created_at"
    }
}

/// Proactive Triggers Layer (2026-08-21, backend/app/triggers.py) -- one
/// currently-matching item under a rule, e.g. one specific overdue
/// invoice. `due` reflects the decaying-cadence check (day 1/3/7 then
/// weekly) -- true means this item would actually be in *today's*
/// digest, false means it's real and still open but already notified on
/// recently, so it's suppressed rather than re-flagged. `id` is a local
/// UUID for List/ForEach identity, not decoded — `itemKey` is the real
/// stable identity from the backend.
public struct TriggerItem: Identifiable, Decodable {
    public let id = UUID()
    public let itemKey: String
    public let title: String
    public let detail: String
    public let due: Bool

    enum CodingKeys: String, CodingKey {
        case title, detail, due
        case itemKey = "item_key"
    }
}

/// One rule (invoice_overdue / client_contact_gap / project_stage_stall /
/// deliverable_overdue), its enabled/threshold data-row state
/// (backend/app/triggers_db.py's trigger_rules table), and every item it's
/// currently matching against live data — even when disabled, so the UI
/// can show "this would still be flagging N things" rather than going
/// blank the moment a rule's toggled off.
public struct TriggerRuleSection: Identifiable, Decodable {
    public var id: String { ruleType }
    public let ruleType: String
    public let label: String
    public let enabled: Bool
    public let thresholdDays: Int?
    public let items: [TriggerItem]

    enum CodingKeys: String, CodingKey {
        case label, enabled, items
        case ruleType = "rule_type"
        case thresholdDays = "threshold_days"
    }
}

/// Fetched from GET /triggers/status -- backs the whole Triggers UI.
public struct TriggerStatus: Decodable {
    public let rules: [TriggerRuleSection]
    public let lastSentDate: String?
    public let sendHour: Int

    enum CodingKeys: String, CodingKey {
        case rules
        case lastSentDate = "last_sent_date"
        case sendHour = "send_hour"
    }
}

/// Result of POST /triggers/run-now -- a manual digest send outside the
/// schedule, for testing/confirming the email path actually works.
public struct TriggerRunResult: Decodable {
    public let sent: Bool
    public let itemCount: Int

    enum CodingKeys: String, CodingKey {
        case sent
        case itemCount = "item_count"
    }
}

/// Joshx (2026-08-21) -- Josh's independent freelance creative business
/// (video editing, videography, photography), completely separate from
/// Alpha Mode Media. Phase 1 scope only: clients/leads/projects, backed
/// by their own local joshx.db (backend/app/joshx_db.py). Amounts are
/// rands, matching the currency fix applied across the app the same day.
public struct JoshxClientRecord: Identifiable, Decodable {
    public let id: Int
    public let name: String
    public let company: String?
    public let status: String
    public let lastContactDate: String?
    public let nextFollowUpDate: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, name, company, status
        case lastContactDate = "last_contact_date"
        case nextFollowUpDate = "next_follow_up_date"
        case createdAt = "created_at"
    }
}

public struct JoshxLead: Identifiable, Decodable {
    public let id: Int
    public let clientName: String
    public let projectDescription: String?
    public let service: String?
    public let estimatedValue: Double?
    public let stage: String
    public let probability: Int?
    public let followUpDate: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, service, stage, probability
        case clientName = "client_name"
        case projectDescription = "project_description"
        case estimatedValue = "estimated_value"
        case followUpDate = "follow_up_date"
        case createdAt = "created_at"
    }
}

public struct JoshxProject: Identifiable, Decodable {
    public let id: Int
    public let clientName: String
    public let projectName: String
    public let projectType: String?
    public let dueDate: String?
    public let shootDate: String?
    public let budget: Double?
    public let priority: String?
    public let status: String
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, budget, priority, status
        case clientName = "client_name"
        case projectName = "project_name"
        case projectType = "project_type"
        case dueDate = "due_date"
        case shootDate = "shoot_date"
        case createdAt = "created_at"
    }
}

/// Finance (2026-08-21) -- Josh's personal investment tracking, backed by
/// backend/app/finance_db.py's own joshx.db-style local file. One holding
/// per asset an account has ever held (Luno especially can carry ZAR cash
/// *and* crypto assets at once) -- deliberately no blended cross-currency
/// total, same "never fabricate" reasoning as everywhere else here.
public struct FinanceHolding: Identifiable, Decodable {
    public let id = UUID()
    public let asset: String
    public let balance: Double
    public let recordedAt: String
    public let trend: String
    public let previousBalance: Double?

    enum CodingKeys: String, CodingKey {
        case asset, balance, trend
        case recordedAt = "recorded_at"
        case previousBalance = "previous_balance"
    }
}

/// Luno's real overall rand value (2026-08-24), computed live against
/// Luno's own price feed -- see backend/app/finance.py's
/// compute_luno_zar_value() docstring for why some holdings can't be
/// priced (Luno's tokenized-stock products and a couple of assets have
/// no direct ZAR pair) and are reported rather than silently dropped.
public struct LunoZarValue: Decodable {
    public let estimatedZarValue: Double
    public let pricedAssets: [String]
    public let unpricedAssets: [String]

    enum CodingKeys: String, CodingKey {
        case estimatedZarValue = "estimated_zar_value"
        case pricedAssets = "priced_assets"
        case unpricedAssets = "unpriced_assets"
    }
}

/// Real-time HF Markets equity/floating P&L (2026-08-24), read live from
/// the local MT5 file bridge on every fetch -- never stored/snapshotted,
/// since a cached number would go stale the moment the market moves.
/// `balance` is the settled figure the daily snapshot tracks; `equity`
/// reflects open positions; `floatingPnl` is the difference -- positive
/// means currently in profit, negative means currently in loss.
public struct HFMarketsLiveStatus: Decodable {
    public let balance: Double
    public let equity: Double
    public let floatingPnl: Double
    public let currency: String
    public let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case balance, equity, currency
        case floatingPnl = "floating_pnl"
        case updatedAt = "updated_at"
    }
}

public struct FinanceAccount: Identifiable, Decodable {
    public let id: Int
    public let name: String
    public let accountType: String?
    public let isAutomatic: Bool
    public let holdings: [FinanceHolding]
    public let lunoValue: LunoZarValue?
    public let hfMarketsLive: HFMarketsLiveStatus?

    enum CodingKeys: String, CodingKey {
        case id, name, holdings
        case accountType = "account_type"
        case isAutomatic = "is_automatic"
        case lunoValue = "luno_value"
        case hfMarketsLive = "hf_markets_live"
    }
}

/// Fetched from GET /finance/dashboard.
public struct FinanceDashboard: Decodable {
    public let accounts: [FinanceAccount]
}

/// Fetched from GET /joshx/dashboard. Deliberately no revenue/outstanding/
/// available-days fields -- Phase 1 has no invoices or availability data
/// model, and this app never shows a stat without real data behind it
/// (Mission Status's fake progress bar, removed 2026-08-20, is the
/// standing example of what NOT to do).
public struct JoshxDashboard: Decodable {
    public let activeProjects: Int
    public let openLeads: Int
    public let upcomingShoots: Int
    public let clients: [JoshxClientRecord]
    public let leads: [JoshxLead]
    public let projects: [JoshxProject]

    enum CodingKeys: String, CodingKey {
        case clients, leads, projects
        case activeProjects = "active_projects"
        case openLeads = "open_leads"
        case upcomingShoots = "upcoming_shoots"
    }
}
