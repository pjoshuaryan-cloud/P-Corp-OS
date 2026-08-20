import PCorpKit
import SwiftUI

/// "The Brief" (2026-08-20, Face-Lift item 09) -- Frank's daily executive
/// briefing. Reached via a new top-bar icon button in WarRoomView's
/// topBar, opened as a popover -- same mechanism as the existing
/// "Previous conversations" button, deliberately not a permanent new
/// section of the War Room home screen. Direct lesson from the same
/// day's command-map feedback ("looks very busy & cluttered"): War
/// Room's idle screen already grew once this round (the stats row);
/// adding a whole second, richer module permanently on-screen risked the
/// same complaint. A popover keeps it available without competing with
/// Frank's own greeting/orb for space by default.
///
/// "Keep this visually minimal... should feel like intelligence, not a
/// news feed" (the brief's own words) -- plain section labels and rows,
/// no card boxes, matching ConversationListPopover's own already-minimal
/// style rather than RightRail's boxed-card language.
struct TheBriefPopover: View {
    @StateObject private var client = BriefClient()
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("THE BRIEF")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

            ScrollView {
                if client.isLoading && client.brief == nil {
                    ProgressView()
                        .padding(20)
                        .frame(maxWidth: .infinity)
                } else if let error = client.errorMessage {
                    Text(error)
                        .font(PCorpFont.body(12))
                        .foregroundStyle(theme.textSecondary)
                        .padding(20)
                } else if let brief = client.brief {
                    VStack(alignment: .leading, spacing: 18) {
                        section(title: "WHAT MATTERS", items: brief.whatMatters, empty: "Nothing urgent right now.")
                        activitySection(title: "WHAT CHANGED", activities: brief.whatChanged, empty: "Nothing since you last checked.")
                        section(title: "WHAT FRANK RECOMMENDS", items: brief.whatFrankRecommends, empty: "Nothing worth flagging right now.")
                        section(title: "WHAT CAN WAIT", items: brief.whatCanWait, empty: "Nothing sitting on the back burner.")
                    }
                    .padding(16)
                }
            }
        }
        .frame(width: 380, height: 480)
        .task {
            await client.fetch()
        }
    }

    @ViewBuilder
    private func section(title: String, items: [BriefItem], empty: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if items.isEmpty {
                Text(empty)
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(items) { item in
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: item.systemImage)
                                .font(.system(size: 11))
                                .foregroundStyle(theme.textSecondary)
                                .frame(width: 14)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(item.title)
                                    .font(PCorpFont.body(12.5, weight: .semibold))
                                    .foregroundStyle(theme.textPrimary)
                                Text(item.detail)
                                    .font(PCorpFont.body(11.5))
                                    .foregroundStyle(theme.textSecondary)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func activitySection(title: String, activities: [BriefActivity], empty: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if activities.isEmpty {
                Text(empty)
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(activities) { activity in
                        Text(activity.result)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textPrimary)
                            .lineLimit(2)
                    }
                }
            }
        }
    }
}
