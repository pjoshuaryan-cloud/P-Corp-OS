import SwiftUI

struct NavItem: Identifiable {
    let id = UUID()
    let title: String
    let subtitle: String
    let systemImage: String
}

/// Backs GET /insights — real, computed insights (overdue/upcoming
/// tasks and invoices, app/insights.py), not the hardcoded placeholder
/// text this used to be. `id` is a local UUID, not part of the decoded
/// JSON (excluded from CodingKeys, Swift's synthesized decoder falls
/// back to its default-value initializer) — this list is ephemeral,
/// recomputed on every fetch, nothing to reference by a stable ID.
struct InsightItem: Identifiable, Decodable {
    let id = UUID()
    let systemImage: String
    let title: String
    let detail: String
    /// Which nav section this relates to — same honest-routing pattern as
    /// QuickAction, so clicking an insight isn't a dead end.
    let targetNavTitle: String

    enum CodingKeys: String, CodingKey {
        case systemImage = "icon"
        case title, detail
        case targetNavTitle = "target_nav_title"
    }
}

/// A row in the conversation switcher — backs GET /conversations. `id`
/// matches the real backend conversation_id (not a client-generated UUID)
/// since it has to round-trip to POST /conversations/{id}/activate.
struct ConversationSummary: Identifiable, Decodable {
    let id: Int
    let createdAt: String
    let firstMessage: String?
    let messageCount: Int
    /// When this conversation was last actually used, not just created —
    /// what the history browser sorts/groups by, so a conversation reopened
    /// and continued today surfaces above one merely created earlier but
    /// untouched since.
    let lastMessageAt: String

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
struct MemoryRecord: Identifiable, Decodable {
    let id: Int
    let type: String
    let title: String
    let content: String
    let sensitive: Bool
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, type, title, content, sensitive
        case createdAt = "created_at"
    }
}

/// Mirrors backend/app/operations_db.py's `tasks` table (excluding done
/// ones) — general, cross-business tasks Frank creates via add_task,
/// made visible read-only from GET /operations/tasks, same pattern as
/// MemoryRecord/GET /memory.
struct OperationsTask: Identifiable, Decodable {
    let id: Int
    let title: String
    let status: String
    let area: String?
    let dueDate: String?
    let notes: String?
    let createdAt: String

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
struct Agent: Identifiable, Decodable {
    let id: String
    let name: String
    let icon: String
    let tagline: String
    let detail: String
    let status: String
}

/// Mirrors backend/app/db.py's get_focus_objective() -- the War Room's
/// Mission Status "Focus: ..." line, fetched from GET /focus. Both
/// fields are nullable: no objective set yet is a real, honest state,
/// not an error.
struct FocusObjective: Decodable {
    let objective: String?
    let setAt: String?

    enum CodingKeys: String, CodingKey {
        case objective
        case setAt = "set_at"
    }
}

/// Mirrors backend/app/automations_registry.py's AGENTS list -- the
/// configured automation rules, fetched from GET /automations/rules.
struct AutomationRule: Identifiable, Decodable {
    let id: String
    let triggerTool: String
    let name: String
    let description: String
    let agent: String

    enum CodingKeys: String, CodingKey {
        case id, name, description, agent
        case triggerTool = "trigger_tool"
    }
}

/// Mirrors backend/app/automations_db.py's automation_runs table -- real
/// firing history, fetched from GET /automations/runs.
struct AutomationRun: Identifiable, Decodable {
    let id: Int
    let ruleId: String
    let ruleName: String
    let triggerSummary: String?
    let result: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, result
        case ruleId = "rule_id"
        case ruleName = "rule_name"
        case triggerSummary = "trigger_summary"
        case createdAt = "created_at"
    }
}

struct QuickAction: Identifiable {
    let id = UUID()
    let title: String
    let systemImage: String
    /// Which nav section this navigates to when clicked — honest routing to
    /// a real (if not-yet-built) section, not a fake action.
    let targetNavTitle: String
}

enum PlaceholderData {
    static let navItems: [NavItem] = [
        NavItem(title: "War Room", subtitle: "Mission Control", systemImage: "square.grid.2x2"),
        NavItem(title: "Frank", subtitle: "Executive Intelligence", systemImage: "brain"),
        NavItem(title: "Alpha Mode Media", subtitle: "Business Operations", systemImage: "briefcase"),
        NavItem(title: "Trading Division", subtitle: "Markets & Strategies", systemImage: "chart.line.uptrend.xyaxis"),
        NavItem(title: "Personal", subtitle: "Life & Relationships", systemImage: "person"),
        NavItem(title: "Finance", subtitle: "Wealth & Investments", systemImage: "banknote"),
        NavItem(title: "Knowledge", subtitle: "Files & Insights", systemImage: "books.vertical"),
        NavItem(title: "Agents", subtitle: "AI Team", systemImage: "person.3"),
        NavItem(title: "Automations", subtitle: "Workflows", systemImage: "bolt"),
        NavItem(title: "Calendar", subtitle: "Schedule & Events", systemImage: "calendar"),
        NavItem(title: "Settings", subtitle: "Preferences", systemImage: "gearshape"),
    ]

    static let quickActions: [QuickAction] = [
        QuickAction(title: "New Mission", systemImage: "plus", targetNavTitle: "War Room"),
        QuickAction(title: "Start Deep Work", systemImage: "timer", targetNavTitle: "Calendar"),
        QuickAction(title: "Ask Frank", systemImage: "waveform", targetNavTitle: "War Room"),
        QuickAction(title: "Run Report", systemImage: "chart.bar", targetNavTitle: "Trading Division"),
    ]
}
