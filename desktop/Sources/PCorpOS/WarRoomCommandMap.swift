import PCorpKit
import SwiftUI

/// War Room's command stats row (2026-08-20, Face-Lift brief item 18).
/// Started as both this row and a radial "JOSH connected to..." node
/// map, per the brief's own literal ask -- the map was removed the same
/// day after Joshua saw it live ("looks very busy & cluttered"), keeping
/// just this row since that specific feedback was about the map's nodes/
/// lines, not the stats.
///
/// Every number here is real, not the brief's own illustrative example
/// values (it suggests "ACTIVE MISSIONS 04 / AGENTS ONLINE 07 /
/// OPPORTUNITIES 12 / RISKS 03"). Active Missions is deliberately
/// **omitted** -- there is no real missions-tracking system anywhere in
/// this app today (Mission Status shows one fixed, hardcoded mission
/// text, and the "+ Mission" button is a documented no-op), so there's
/// nothing honest to count. Agents Online, Opportunities, and Risks are
/// all real counts from data already fetched elsewhere in this app
/// (GET /agents, GET /insights's category field).
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
