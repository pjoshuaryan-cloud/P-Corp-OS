import SwiftUI
import PCorpKit

/// Close port of desktop's own TriggersView.swift (2026-08-25 iOS parity
/// pass) -- entirely built on PCorpKit's already-cross-platform
/// TriggersClient/TriggerStatus/TriggerRuleSection/TriggerItem, no
/// AppKit dependencies, so this is a direct, unmodified port. Includes
/// the same per-rule enable/disable Toggle as desktop -- the first
/// section on iOS too where the UI itself writes state directly rather
/// than routing through Frank.
struct TriggersView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = TriggersClient()
    @State private var isRunningNow = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if client.isLoading && client.status == nil {
                        Text("Loading…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let status = client.status {
                        scheduleRow(status: status)
                        ForEach(status.rules) { section in
                            RuleSectionCard(
                                section: section,
                                onToggle: { enabled in
                                    Task { await client.toggleRule(ruleType: section.ruleType, enabled: enabled) }
                                }
                            )
                        }
                    }
                }
                .padding(20)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Triggers")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Scheduled checks against real data — flags, never acts")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                Task { await client.fetch() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.icon)
        }
        .padding(20)
    }

    @ViewBuilder
    private func scheduleRow(status: TriggerStatus) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("DAILY DIGEST")
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.2)
                    .foregroundStyle(theme.textSecondary)
                Text(scheduleDetail(status: status))
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                isRunningNow = true
                Task {
                    await client.runNow()
                    isRunningNow = false
                }
            } label: {
                Text(isRunningNow ? "Sending…" : "Send Digest Now")
            }
            .buttonStyle(.pillTinted)
            .disabled(isRunningNow)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))

        if let result = client.lastRunResult {
            Text(result.sent ? "Sent — \(result.itemCount) item(s) in the digest." : "Nothing due to send right now.")
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textSecondary)
        }
    }

    private func scheduleDetail(status: TriggerStatus) -> String {
        let last = status.lastSentDate.map { "last sent \($0)" } ?? "never sent yet"
        return "Runs automatically after \(status.sendHour):00 each day — \(last)."
    }
}

private struct RuleSectionCard: View {
    let section: TriggerRuleSection
    let onToggle: (Bool) -> Void
    @Environment(\.appTheme) private var theme

    private var dueCount: Int { section.items.filter(\.due).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(.regularMaterial).frame(width: 40, height: 40)
                    Image(systemName: "bell.badge")
                        .font(.system(size: 15))
                        .foregroundStyle(theme.textPrimary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(section.label)
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text(subtitle)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer()
                Toggle("", isOn: Binding(get: { section.enabled }, set: onToggle))
                    .labelsHidden()
                    .toggleStyle(.switch)
                    .tint(theme.textPrimary)
            }

            if section.items.isEmpty {
                Text(section.enabled ? "Nothing currently matching this rule." : "Rule is off.")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(section.items) { item in
                        TriggerItemRow(item: item)
                    }
                }
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 14).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(theme.surfaceBorder))
    }

    private var subtitle: String {
        var parts: [String] = []
        if let threshold = section.thresholdDays {
            parts.append("\(threshold)-day threshold")
        }
        if !section.items.isEmpty {
            parts.append("\(section.items.count) matching, \(dueCount) due today")
        }
        return parts.isEmpty ? (section.enabled ? "Active" : "Off") : parts.joined(separator: " · ")
    }
}

private struct TriggerItemRow: View {
    let item: TriggerItem
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Circle()
                .fill(item.due ? Color.orange : theme.textTertiary)
                .frame(width: 6, height: 6)
                .padding(.top, 5)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title)
                    .font(PCorpFont.body(12.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(item.detail)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            if !item.due {
                Text("SUPPRESSED")
                    .font(PCorpFont.label(8.5))
                    .trackedLabel(1.0)
                    .foregroundStyle(theme.textTertiary)
            }
        }
    }
}
