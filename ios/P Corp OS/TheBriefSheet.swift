import PCorpKit
import SwiftUI

/// iOS port of desktop's own TheBriefPopover.swift (2026-08-20, Face-Lift
/// iOS parity pass, fifth) -- same content, same `BriefClient` (already
/// shared via PCorpKit, no changes needed), same "plain section labels
/// and rows, no card boxes... should feel like intelligence, not a news
/// feed" restraint the brief itself asks for.
///
/// Presented as a `.sheet` from RootView's top bar rather than desktop's
/// `.popover` -- macOS popovers and iOS sheets are each the natural,
/// platform-idiomatic way to show a dismissable secondary view anchored
/// to a button; forcing iOS to use `.popover` here would just become an
/// auto-adapted sheet anyway on iPhone's compact width, so this is
/// explicit about that rather than relying on the adaptation. Same
/// "reached via a button, not a permanent screen" placement reasoning as
/// desktop -- War Room's idle screen already grew once this round (the
/// stats row), so this stays opt-in.
struct TheBriefSheet: View {
    @StateObject private var client = BriefClient()
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("The Brief")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .presentationDetents([.medium, .large])
        .task {
            await client.fetch()
        }
    }

    @ViewBuilder
    private var content: some View {
        if client.isLoading && client.brief == nil {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if let error = client.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.background)
        } else if let brief = client.brief {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    section(title: "WHAT MATTERS", items: brief.whatMatters, empty: "Nothing urgent right now.")
                    activitySection(title: "WHAT CHANGED", activities: brief.whatChanged, empty: "Nothing since you last checked.")
                    section(title: "WHAT FRANK RECOMMENDS", items: brief.whatFrankRecommends, empty: "Nothing worth flagging right now.")
                    section(title: "WHAT CAN WAIT", items: brief.whatCanWait, empty: "Nothing sitting on the back burner.")
                }
                // Real bug found live (2026-08-20): without this, the
                // VStack sized itself to its own content's intrinsic
                // width instead of stretching to fill the ScrollView, so
                // the whole Brief rendered as a narrow centered column
                // with empty space on both sides instead of edge-to-edge
                // -- much more visible on a full-width iOS sheet than it
                // would be in desktop's own fixed-width popover.
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
            }
            .background(theme.background)
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
