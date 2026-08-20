import PCorpKit
import SwiftUI

/// Direct port of desktop's own WarRoomCommandMap.swift (2026-08-20,
/// Face-Lift iOS parity pass, fourth) -- identical logic, since this is
/// pure PCorpKit-shared state (AgentsClient/InsightsClient, PCorpFont.mono,
/// theme tokens), no AppKit dependency to work around.
///
/// Every number here is real, not the brief's own illustrative example
/// values. Active Missions is deliberately **omitted** -- there is no real
/// missions-tracking system anywhere in this app today, so there's
/// nothing honest to count. Agents Online, Opportunities, and Risks are
/// all real counts from data already fetched elsewhere (GET /agents,
/// GET /insights's category field). Desktop's radial "JOSH connected
/// to..." node map was built and removed the same day after Joshua saw
/// it live ("looks very busy & cluttered") -- only this stats row ever
/// shipped on desktop, so only this row is being ported here.
struct WarRoomCommandMap: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var agentsClient = AgentsClient()
    @StateObject private var insightsClient = InsightsClient()

    private var opportunityCount: Int {
        insightsClient.insights.filter { $0.category == "opportunity" }.count
    }

    private var riskCount: Int {
        insightsClient.insights.filter { $0.category == "risk" }.count
    }

    var body: some View {
        HStack(spacing: 0) {
            statItem(label: "AGENTS ONLINE", value: agentsClient.agents.count)
            statDivider
            statItem(label: "OPPORTUNITIES", value: opportunityCount)
            statDivider
            statItem(label: "RISKS", value: riskCount)
        }
        .task {
            await agentsClient.fetch()
            await insightsClient.fetch()
        }
    }

    private var statDivider: some View {
        Rectangle()
            .fill(theme.divider)
            .frame(width: 1, height: 28)
    }

    private func statItem(label: String, value: Int) -> some View {
        VStack(spacing: 4) {
            Text("\(value)")
                .font(PCorpFont.mono(22, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(label)
                .font(PCorpFont.label(9))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textTertiary)
        }
        .frame(maxWidth: .infinity)
    }
}
