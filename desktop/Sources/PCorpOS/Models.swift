import SwiftUI

/// Desktop-only navigation model -- the fixed 3-column sidebar layout is
/// specific to the desktop shell (2026-08-12, split out of PCorpKit's
/// Models.swift when a shared package was introduced for the iOS
/// companion app): mobile navigation will be tab-bar/stack-based with a
/// different structure entirely, not a port of this list.
struct NavItem: Identifiable {
    let id = UUID()
    let title: String
    let subtitle: String
    let systemImage: String
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
        NavItem(title: "Triggers", subtitle: "Proactive Alerts", systemImage: "bell.badge"),
        NavItem(title: "Joshx", subtitle: "Freelance Creative", systemImage: "camera.aperture"),
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
