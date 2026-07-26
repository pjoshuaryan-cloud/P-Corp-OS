import SwiftUI

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
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 18)
                .fill(.regularMaterial) // slightly more opaque than the rail behind it, so card text stays legible
        )
        .background(
            RoundedRectangle(cornerRadius: 18)
                .fill(theme.background.opacity(0.35))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .strokeBorder(theme.surfaceBorder)
        )
        .shadow(color: theme.cardShadow, radius: 12, x: 0, y: 4)
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
    // Placeholder value — not wired to anything real yet.
    private let progress: Double = 0.68
    @Environment(\.appTheme) private var theme
    @State private var animatedProgress: Double = 0

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "MISSION STATUS")
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(theme.textPrimary).frame(width: 6, height: 6)
                    Text("Active").font(PCorpFont.body(11, weight: .semibold)).foregroundStyle(theme.textPrimary)
                }
            }
            Text("Create Leverage.\nFreedom Tomorrow.")
                .font(PCorpFont.display(19))
                .foregroundStyle(theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(theme.textPrimary.opacity(0.1))
                    Capsule().fill(theme.textPrimary)
                        .frame(width: proxy.size.width * animatedProgress)
                }
            }
            .frame(height: 5)
            .onAppear {
                withAnimation(.easeOut(duration: 0.9).delay(0.15)) {
                    animatedProgress = progress
                }
            }

            HStack {
                Text("Focus: Build systems that scale")
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
                Spacer()
                Text("\(Int(progress * 100))%")
                    .font(PCorpFont.body(11, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
            }
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
                Text("Nothing on the calendar today.")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
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

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "FRANK'S INSIGHTS")
                Spacer()
                LinkTextButton(title: "View all") {
                    navigate(to: "Frank", selectedID: $selectedID)
                }
            }
            VStack(alignment: .leading, spacing: 12) {
                ForEach(PlaceholderData.insights) { insight in
                    InsightRow(insight: insight, selectedID: $selectedID)
                }
            }
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
                Image(systemName: insight.systemImage)
                    .font(.system(size: 13))
                    .foregroundStyle(theme.textPrimary)
                    .frame(width: 22, height: 22)
                    .background(Circle().fill(theme.textPrimary.opacity(0.06)))
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
            LazyVGrid(columns: columns, spacing: 10) {
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
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.pillTinted)
                }
            }
        }
    }
}
