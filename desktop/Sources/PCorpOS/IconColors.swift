import SwiftUI

/// Per-item icon tinting for the sidebar and Agents tab (2026-08-10) --
/// every icon previously rendered in theme.textPrimary (monochrome),
/// matching the app's minimal black/white language but making icons
/// harder to scan at a glance. Deliberately restrained to standard
/// system colors, not custom bright/neon values -- same colors already
/// used sparingly elsewhere in this app (status dots, Situation Room's
/// red, Opportunity Radar's orange flame), matching Joshua's own stated
/// taste against loud color (Design Agent's PERSONAL TASTE MODEL).
enum IconColors {
    /// Keyed by NavItem.title. Alpha Mode Media is deliberately excluded
    /// -- its real brand logo mark stays theme-tinted rather than being
    /// recolored to an arbitrary app-palette color.
    static func forNavItem(_ title: String) -> Color? {
        switch title {
        case "War Room": .indigo
        case "Frank": .purple
        case "Trading Division": .green
        case "Personal": .pink
        case "Finance": .orange
        case "Knowledge": .blue
        case "Agents": .teal
        case "Automations": .yellow
        case "Calendar": .red
        case "Settings": .gray
        default: nil
        }
    }

    /// Keyed by the agent's own icon name (agents_registry.py's `icon`
    /// field) -- stable across agents since each specialist's SF Symbol
    /// is already unique, no backend change needed for this.
    static func forAgentIcon(_ icon: String) -> Color {
        switch icon {
        case "checklist": .teal
        case "briefcase": .orange
        case "paintpalette": .pink
        case "film": .purple
        case "envelope": .blue
        case "brain": .indigo
        case "magnifyingglass": .green
        default: .gray
        }
    }
}
