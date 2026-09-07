import SwiftUI
import PCorpKit

/// The "Automations" nav section — real event-triggered rules (Frank
/// consults an agent automatically when a matching tool call happens,
/// e.g. a new Alpha Mode project triggers a Design Agent folder-structure
/// suggestion), plus a real firing history, not a placeholder. GET
/// /automations/rules backs the rule cards -- rules are real, persisted,
/// user-created data since 2026-09-06 (Frank creates one conversationally
/// via propose_create_automation, approval-gated), not a hardcoded Python
/// list a developer had to edit and redeploy.
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
                .padding(24)
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
        .padding(24)
    }

    @ViewBuilder
    private var ruleSection: some View {
        if client.isLoading && client.rules.isEmpty {
            Text("Loading…")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if client.rules.isEmpty, let error = client.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            // Real gap found live (2026-09-06, systems audit §18 sweep):
            // errorMessage used to be checked before the rules list, so a
            // failed toggle/delete (now surfaced honestly instead of
            // silently discarded) would hide an already-loaded rule list
            // behind a bare error screen. Shown as a small inline banner
            // above the list instead, whenever rules did load.
            if let error = client.errorMessage {
                Text(error)
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.statusRisk)
            }
            VStack(alignment: .leading, spacing: 14) {
                ForEach(client.rules) { rule in
                    // runs is already ORDER BY id DESC (automations_db.py),
                    // so .first is genuinely the most recent firing.
                    RuleCard(
                        rule: rule,
                        lastRun: client.runs.first(where: { $0.ruleId == rule.id }),
                        onToggle: { enabled in Task { await client.toggleRule(id: rule.id, enabled: enabled) } },
                        onDelete: { Task { await client.deleteRule(id: rule.id) } }
                    )
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
    /// Most recent automation_runs row for this rule, if any -- nil means
    /// genuinely never fired yet, not an error.
    let lastRun: AutomationRun?
    let onToggle: (Bool) -> Void
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(theme.surfaceElevated).frame(width: 40, height: 40)
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
                // Real, persisted enabled state (2026-09-06) -- was a
                // hardcoded "ACTIVE" Circle+Text with no backing field at
                // all before this; pause/resume is UI-driven (a PATCH),
                // not a Frank tool, same reasoning Triggers' own toggle
                // already established.
                Toggle("", isOn: Binding(get: { rule.enabled }, set: onToggle))
                    .labelsHidden()
                    .toggleStyle(.switch)
                    .tint(theme.textPrimary)
                Menu {
                    Button("Delete", role: .destructive, action: onDelete)
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .foregroundStyle(theme.textSecondary)
                }
                .menuStyle(.borderlessButton)
                .frame(width: 20)
            }
            Text(rule.description)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)

            // Closes the audit's own "no failure tracking" gap using data
            // that already existed in automation_runs, just never
            // surfaced per-rule until now.
            HStack(spacing: 6) {
                if let lastRun {
                    let failed = lastRun.result.hasPrefix("FAILED")
                    Circle()
                        .fill(failed ? theme.statusRisk : theme.statusGood)
                        .frame(width: 6, height: 6)
                    Text(failed ? "LAST RUN FAILED" : "LAST RUN OK")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.2)
                        .foregroundStyle(theme.textSecondary)
                    Text(lastRun.createdAt)
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                } else {
                    Text("Never run yet")
                        .font(PCorpFont.body(11))
                        .foregroundStyle(theme.textTertiary)
                }
            }
        }
        .padding(18)
        .cardSurface(radius: 14)
        .opacity(rule.enabled ? 1.0 : 0.55)
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
        .cardSurface(radius: 12)
    }
}
