import SwiftUI

struct NavItem: Identifiable {
    let id = UUID()
    let title: String
    let subtitle: String
    let systemImage: String
}

struct InsightItem: Identifiable {
    let id = UUID()
    let systemImage: String
    let title: String
    let detail: String
    /// Which nav section this relates to — same honest-routing pattern as
    /// QuickAction, so clicking an insight isn't a dead end.
    let targetNavTitle: String
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

    static let insights: [InsightItem] = [
        InsightItem(systemImage: "target", title: "Placeholder Insight", detail: "Example of an opportunity Frank might surface here.", targetNavTitle: "Alpha Mode Media"),
        InsightItem(systemImage: "chart.line.uptrend.xyaxis", title: "Placeholder Signal", detail: "Example of a trading-related note Frank might surface here.", targetNavTitle: "Trading Division"),
        InsightItem(systemImage: "clock", title: "Placeholder Optimization", detail: "Example of a scheduling note Frank might surface here.", targetNavTitle: "Calendar"),
    ]

    static let quickActions: [QuickAction] = [
        QuickAction(title: "New Mission", systemImage: "plus", targetNavTitle: "War Room"),
        QuickAction(title: "Start Deep Work", systemImage: "timer", targetNavTitle: "Calendar"),
        QuickAction(title: "Ask Frank", systemImage: "waveform", targetNavTitle: "War Room"),
        QuickAction(title: "Run Report", systemImage: "chart.bar", targetNavTitle: "Trading Division"),
    ]
}
