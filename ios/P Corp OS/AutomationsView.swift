import PCorpKit
import SwiftUI

/// Close port of desktop's own AutomationsView.swift (2026-08-13) — third
/// of the deferred sidebar sections. Entirely built on PCorpKit's already-
/// cross-platform AutomationsClient/AutomationRule/AutomationRun, no
/// AppKit dependencies and no hover-only affordances to adapt (unlike
/// FrankView's forget button), so this is a direct, unmodified port.
struct AutomationsView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = AutomationsClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    ruleSection
                    runSection
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
                Text("Automations")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Rules Frank runs automatically when something happens")
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
    private var ruleSection: some View {
        if client.isLoading && client.rules.isEmpty {
            Text("Loading…")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if let error = client.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(client.rules) { rule in
                    RuleCard(rule: rule)
                }
            }
        }
    }

    @ViewBuilder
    private var runSection: some View {
        HStack(spacing: 8) {
            Text("RECENT ACTIVITY")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
            Spacer()
        }

        if client.runs.isEmpty && !client.isLoading {
            Text("Nothing's fired yet — automations run automatically when their trigger happens, nothing to do here.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            LazyVStack(alignment: .leading, spacing: 10) {
                ForEach(client.runs) { run in
                    RunRow(run: run)
                }
            }
        }
    }
}

private struct RuleCard: View {
    let rule: AutomationRule
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(.regularMaterial).frame(width: 40, height: 40)
                    Image(systemName: "bolt.fill")
                        .font(.system(size: 16))
                        .foregroundStyle(theme.textPrimary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(rule.name)
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text("Trigger: \(rule.triggerTool)")
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer()
                HStack(spacing: 6) {
                    Circle().fill(Color.green).frame(width: 6, height: 6)
                    Text("ACTIVE")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.2)
                        .foregroundStyle(theme.textSecondary)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
            }
            Text(rule.description)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 14).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(theme.surfaceBorder))
    }
}

private struct RunRow: View {
    let run: AutomationRun
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(run.ruleName)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Spacer()
                Text(run.createdAt)
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
            }
            if let summary = run.triggerSummary {
                Text(summary)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Text(run.result)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
                .lineLimit(4)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}
