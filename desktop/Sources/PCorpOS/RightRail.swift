import SwiftUI

struct RightRail: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                MissionStatusCard()
                AgendaCard()
                InsightsCard()
                QuickActionsCard()
            }
            .padding(22)
        }
        .frame(minWidth: 300, idealWidth: 320)
        .background(theme.surface)
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
                .fill(theme.background)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .strokeBorder(theme.surfaceBorder)
        )
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
                        .frame(width: proxy.size.width * progress)
                }
            }
            .frame(height: 5)

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
    @Environment(\.appTheme) private var theme

    var body: some View {
        CardContainer {
            SectionLabel(text: "TODAY'S AGENDA")
            VStack(alignment: .leading, spacing: 10) {
                ForEach(PlaceholderData.agenda) { item in
                    HStack(spacing: 10) {
                        Text(item.time)
                            .font(PCorpFont.body(12, weight: .semibold))
                            .foregroundStyle(theme.textSecondary)
                            .frame(width: 44, alignment: .leading)
                        Text(item.title)
                            .font(PCorpFont.body(12.5))
                            .foregroundStyle(theme.textPrimary)
                    }
                }
            }
            HStack {
                Spacer()
                Text("View full calendar")
                    .font(PCorpFont.body(11, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }
}

private struct InsightsCard: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "FRANK'S INSIGHTS")
                Spacer()
                Text("View all")
                    .font(PCorpFont.body(11, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
            }
            VStack(alignment: .leading, spacing: 12) {
                ForEach(PlaceholderData.insights) { insight in
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
                    }
                }
            }
        }
    }
}

private struct QuickActionsCard: View {
    private let columns = [GridItem(.flexible()), GridItem(.flexible())]

    var body: some View {
        CardContainer {
            SectionLabel(text: "QUICK ACTIONS")
            LazyVGrid(columns: columns, spacing: 10) {
                ForEach(PlaceholderData.quickActions) { action in
                    Button {
                        // no-op: shell only, not wired up yet
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
