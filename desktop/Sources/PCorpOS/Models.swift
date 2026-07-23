import SwiftUI

struct NavItem: Identifiable {
    let id = UUID()
    let title: String
    let subtitle: String
    let systemImage: String
}

struct AgendaItem: Identifiable {
    let id = UUID()
    let time: String
    let title: String
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

    static let agenda: [AgendaItem] = [
        AgendaItem(time: "08:30", title: "Morning Brief with Frank"),
        AgendaItem(time: "09:00", title: "Alpha Mode Leadership Call"),
        AgendaItem(time: "10:30", title: "Client Presentation"),
        AgendaItem(time: "13:00", title: "Deep Work Block"),
        AgendaItem(time: "15:30", title: "Trading Strategy Review"),
        AgendaItem(time: "17:30", title: "Workout"),
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
