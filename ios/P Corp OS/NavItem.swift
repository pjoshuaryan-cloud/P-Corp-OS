import Foundation

/// Mobile's own copy of desktop's PlaceholderData.navItems (desktop/Sources/
/// PCorpOS/Models.swift) -- desktop's version is deliberately not in
/// PCorpKit (its own comment there says mobile nav would differ), but the
/// direct ask here is to port the sidebar as-is, so this mirrors that same
/// list by hand rather than restructuring desktop's file. Keep titles/
/// subtitles/systemImages in sync with desktop's list if that one changes.
struct NavItem: Identifiable {
    let id = UUID()
    let title: String
    let subtitle: String
    let systemImage: String

    static let items: [NavItem] = [
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
}
