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
