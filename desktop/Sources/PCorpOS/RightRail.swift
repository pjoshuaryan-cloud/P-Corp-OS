import SwiftUI
import PCorpKit

struct RightRail: View {
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                MissionStatusCard()
                AgendaCard(selectedID: $selectedID)
                InsightsCard(selectedID: $selectedID)
                QuickActionsCard(selectedID: $selectedID)
            }
            .padding(22)
        }
        .frame(minWidth: 300, idealWidth: 320)
        .background(.ultraThinMaterial)
        .background(theme.surface.opacity(0.3))
    }
}

private struct CardContainer<Content: View>: View {
    let content: Content
    @Environment(\.appTheme) private var theme
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            content
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.xl)
                .fill(.regularMaterial) // slightly more opaque than the rail behind it, so card text stays legible
        )
        .background(
            RoundedRectangle(cornerRadius: Radius.xl)
                .fill(theme.background.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.xl)
                .strokeBorder(theme.surfaceBorder)
        )
        // Shadow eased 12/y4 -> 8/y3 (2026-08-20, Face-Lift brief item 04:
        // "avoid excessive drop shadows") -- still reads as elevated, just
        // quieter, not a structural change to the material-based approach
        // UI_GUIDELINES.md already deliberately committed to.
        .shadow(color: theme.cardShadow, radius: 8, x: 0, y: 3)
    }
}

/// Shared navigation helper — honest routing to a real (if not-yet-built)
/// section, same pattern used by Quick Actions and Insights.
private func navigate(to title: String, selectedID: Binding<UUID?>) {
    if let target = PlaceholderData.navItems.first(where: { $0.title == title }) {
        withAnimation(.easeOut(duration: 0.22)) {
            selectedID.wrappedValue = target.id
        }
    }
}

/// A text-styled "link" with real hover feedback — for "View full calendar"
/// / "View all," which previously looked clickable but did nothing.
private struct LinkTextButton: View {
    let title: String
    let action: () -> Void
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(PCorpFont.body(11, weight: .semibold))
                .foregroundStyle(isHovering ? theme.textPrimary : theme.textSecondary)
                .underline(isHovering)
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
        }
    }
}

private struct SectionLabel: View {
    let text: String
    @Environment(\.appTheme) private var theme

    var body: some View {
        Text(text)
            .font(PCorpFont.label(9.5))
            .trackedLabel(1.6)
            .foregroundStyle(theme.textSecondary)
    }
}

private struct MissionStatusCard: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var focusClient = FocusClient()

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "MISSION STATUS")
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(Color.green).frame(width: 6, height: 6)
                    Text("Active").font(PCorpFont.body(11, weight: .semibold)).foregroundStyle(theme.textPrimary)
                }
            }
            Text("Create Leverage.\nFreedom Tomorrow.")
                .font(PCorpFont.display(19))
                .foregroundStyle(theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            // Real progress tracking doesn't exist yet -- a hardcoded 68%
            // bar used to sit here with nothing behind it (removed
            // 2026-08-20, Face-Lift brief's own "never fabricate metrics"
            // rule). Just the real Focus line remains until there's an
            // actual mission-progress source to show.
            Text("Focus: \(focusClient.objective ?? "Nothing set yet")")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
        }
        .task {
            await focusClient.fetch()
        }
    }
}

private struct AgendaCard: View {
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme
    @State private var todayEvents: [CalendarEvent] = []

    var body: some View {
        CardContainer {
            SectionLabel(text: "TODAY'S AGENDA")
            if todayEvents.isEmpty {
                // Smarter empty state (2026-08-20, Face-Lift brief item
                // 11) -- "Open day detected" plus a generic Deep Work
                // block, genuinely derived from the one real fact
                // available (today's calendar is empty), not a fabricated
                // per-context recommendation. Same fixed suggestion every
                // open day, honestly labeled as a suggestion, not a
                // second real calendar entry.
                VStack(alignment: .leading, spacing: 8) {
                    Text("No commitments. Open day detected.")
                        .font(PCorpFont.body(12))
                        .foregroundStyle(theme.textSecondary)
                    HStack(spacing: 10) {
                        Image(systemName: "bolt.circle")
                            .font(.system(size: 13))
                            .foregroundStyle(theme.accent)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Frank recommends: Deep Work")
                                .font(PCorpFont.body(12, weight: .semibold))
                                .foregroundStyle(theme.textPrimary)
                            Text("09:00 – 12:00")
                                .font(PCorpFont.mono(10.5))
                                .foregroundStyle(theme.textSecondary)
                        }
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(todayEvents) { event in
                        HStack(spacing: 10) {
                            Text(timeString(event.startDate))
                                .font(PCorpFont.body(12, weight: .semibold))
                                .foregroundStyle(theme.textSecondary)
                                .frame(width: 60, alignment: .leading)
                            Text(event.title)
                                .font(PCorpFont.body(12.5))
                                .foregroundStyle(theme.textPrimary)
                        }
                    }
                }
            }
            HStack {
                Spacer()
                LinkTextButton(title: "View full calendar") {
                    navigate(to: "Calendar", selectedID: $selectedID)
                }
            }
        }
        .task {
            // Real events from the macOS Calendar app (SystemCalendar.swift),
            // filtered to just today — replaces the earlier hardcoded
            // PlaceholderData.agenda now that Calendar is a real section.
            let events = await SystemCalendar.upcomingEvents(days: 1)
            todayEvents = events.filter { Calendar.current.isDateInToday($0.startDate) }
        }
    }

    private func timeString(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter.string(from: date)
    }
}

private struct InsightsCard: View {
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme
    @StateObject private var client = InsightsClient()

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "FRANK'S INSIGHTS")
                Spacer()
                LinkTextButton(title: "View all") {
                    navigate(to: "Frank", selectedID: $selectedID)
                }
            }
            if client.insights.isEmpty {
                // Honest, not fake -- real data checked and there's
                // genuinely nothing overdue, due soon, or worth following
                // up on right now, rather than always showing placeholder
                // rows regardless of whether anything's actually true.
                Text(client.isLoading ? "Checking…" : "Nothing overdue, due soon, or worth following up on.")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(client.insights) { insight in
                        InsightRow(insight: insight, selectedID: $selectedID)
                    }
                }
            }
        }
        .task {
            // RightRail is part of the persistent layout, not a per-tab
            // view recreated on navigation (unlike AgentsView/FrankView) --
            // a single one-shot fetch here would only ever reflect
            // whatever existed at launch. Real bug found immediately on
            // first live test: adding a task afterward never showed up
            // at all, since nothing ever triggered a refetch. Polling
            // every 30s is the simple fix -- genuinely proactive
            // shouldn't require remembering to hit a refresh button.
            while !Task.isCancelled {
                await client.fetch()
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
    }

    /// Real category -> color mapping (2026-08-20) -- three of the brief's
    /// five suggested indicator types actually come out of real data
    /// today (risk/follow_up/opportunity, see InsightItem.category's own
    /// doc comment); "decision"/generic "insight" aren't forced since
    /// nothing currently generates them honestly.
    fileprivate static func categoryColor(_ category: String, theme: AppTheme) -> Color {
        switch category {
        case "risk": .red
        case "opportunity": .green
        case "follow_up": theme.accent
        default: theme.textSecondary
        }
    }
}

private struct InsightRow: View {
    let insight: InsightItem
    @Binding var selectedID: UUID?
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    var body: some View {
        Button {
            navigate(to: insight.targetNavTitle, selectedID: $selectedID)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                ZStack {
                    Circle().fill(theme.textPrimary.opacity(0.06))
                    Image(systemName: insight.systemImage)
                        .font(.system(size: 13))
                        .foregroundStyle(theme.textPrimary)
                }
                .frame(width: 22, height: 22)
                .overlay(alignment: .topTrailing) {
                    // Small real category indicator (2026-08-20) -- risk/
                    // opportunity/follow-up, derived from which backend
                    // insights.py generator actually produced this row,
                    // not decoration.
                    Circle()
                        .fill(InsightsCard.categoryColor(insight.category, theme: theme))
                        .frame(width: 7, height: 7)
                        .overlay(Circle().strokeBorder(theme.surface, lineWidth: 1.5))
                        .offset(x: 2, y: -2)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(insight.title)
                        .font(PCorpFont.body(12.5, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text(insight.detail)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
                    .opacity(isHovering ? 1 : 0)
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(isHovering ? theme.textPrimary.opacity(0.04) : Color.clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) { isHovering = hovering }
        }
    }
}

private struct QuickActionsCard: View {
    @Binding var selectedID: UUID?
    private let columns = [GridItem(.flexible()), GridItem(.flexible())]

    var body: some View {
        CardContainer {
            SectionLabel(text: "QUICK ACTIONS")
            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(PlaceholderData.quickActions) { action in
                    Button {
                        // Honest navigation to a real (if not-yet-built)
                        // section — not faking functionality that isn't
                        // built. See targetNavTitle in Models.swift.
                        if let target = PlaceholderData.navItems.first(where: { $0.title == action.targetNavTitle }) {
                            withAnimation(.easeOut(duration: 0.22)) {
                                selectedID = target.id
                            }
                        }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: action.systemImage)
                                .font(.system(size: 11.5))
                            Text(action.title)
                            Spacer(minLength: 4)
                            // Real shortcut hints (2026-08-20), not
                            // decoration -- each one actually works, wired
                            // in ContentView.swift's own keyboard monitor.
                            // Mono, per the brief's own "machine
                            // information" typographic register.
                            if let key = Self.shortcutKey(for: action.title) {
                                Text("⌘\(key.uppercased())")
                                    .font(PCorpFont.mono(9.5))
                                    .opacity(0.5)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    // Swapped from .pillTinted (2026-08-20, Face-Lift brief
                    // item 04: "avoid excessive pills") -- a quieter,
                    // more architectural rectangular treatment specific
                    // to Quick Actions, not a change to PillButtonStyle
                    // itself, which is still used elsewhere (e.g. the
                    // War Room "+ Mission" button) where a pill is right.
                    .buttonStyle(QuickActionButtonStyle())
                }
            }
        }
    }

    /// Mirrors ContentView.swift's own quickActionForShortcut(_:) mapping,
    /// in reverse (title -> key here, key -> title there) -- small enough
    /// to keep as two local, independent lookups rather than introducing
    /// shared infrastructure for a 4-entry mapping.
    fileprivate static func shortcutKey(for title: String) -> String? {
        switch title {
        case "New Mission": "n"
        case "Start Deep Work": "d"
        case "Ask Frank": "k"
        case "Run Report": "r"
        default: nil
        }
    }
}

private struct QuickActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var theme
    @State private var isHovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(PCorpFont.body(12, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: Radius.sm)
                    .fill(configuration.isPressed ? theme.textPrimary.opacity(0.09) : (isHovering ? theme.textPrimary.opacity(0.06) : theme.textPrimary.opacity(0.04)))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.sm)
                    .strokeBorder(theme.surfaceBorder)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.easeOut(duration: AnimationTiming.instant), value: configuration.isPressed)
            .animation(.easeOut(duration: AnimationTiming.instant), value: isHovering)
            .onHover { isHovering = $0 }
    }
}
