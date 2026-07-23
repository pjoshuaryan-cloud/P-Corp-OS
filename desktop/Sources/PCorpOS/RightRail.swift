import SwiftUI

struct RightRail: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                MissionStatusCard()
                AgendaCard()
                InsightsCard()
                QuickActionsCard()
            }
            .padding(16)
        }
        .frame(minWidth: 300, idealWidth: 320)
        .background(Color(white: 0.98))
    }
}

private struct CardContainer<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.white)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.black.opacity(0.06))
        )
    }
}

private struct SectionLabel: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .tracking(1.0)
            .foregroundStyle(.secondary)
    }
}

private struct MissionStatusCard: View {
    // Placeholder value — not wired to anything real yet.
    private let progress: Double = 0.68

    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "MISSION STATUS")
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(Color.black).frame(width: 6, height: 6)
                    Text("Active").font(.system(size: 11, weight: .medium))
                }
            }
            Text("Create Leverage.\nFreedom Tomorrow.")
                .font(.system(size: 18, weight: .semibold))
                .fixedSize(horizontal: false, vertical: true)

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3).fill(Color.black.opacity(0.08))
                    RoundedRectangle(cornerRadius: 3).fill(Color.black)
                        .frame(width: proxy.size.width * progress)
                }
            }
            .frame(height: 5)

            HStack {
                Text("Focus: Build systems that scale")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(progress * 100))%")
                    .font(.system(size: 11, weight: .medium))
            }
        }
    }
}

private struct AgendaCard: View {
    var body: some View {
        CardContainer {
            SectionLabel(text: "TODAY'S AGENDA")
            VStack(alignment: .leading, spacing: 10) {
                ForEach(PlaceholderData.agenda) { item in
                    HStack(spacing: 10) {
                        Text(item.time)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.secondary)
                            .frame(width: 44, alignment: .leading)
                        Text(item.title)
                            .font(.system(size: 12.5))
                    }
                }
            }
            HStack {
                Spacer()
                Text("View full calendar")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct InsightsCard: View {
    var body: some View {
        CardContainer {
            HStack {
                SectionLabel(text: "FRANK'S INSIGHTS")
                Spacer()
                Text("View all").font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 12) {
                ForEach(PlaceholderData.insights) { insight in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: insight.systemImage)
                            .font(.system(size: 13))
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(Color.black.opacity(0.06)))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(insight.title).font(.system(size: 12.5, weight: .medium))
                            Text(insight.detail)
                                .font(.system(size: 11.5))
                                .foregroundStyle(.secondary)
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
                                .font(.system(size: 12))
                            Text(action.title)
                                .font(.system(size: 12))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}
