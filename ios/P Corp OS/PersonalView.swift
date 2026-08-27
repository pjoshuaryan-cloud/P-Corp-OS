import SwiftUI
import PCorpKit

/// The "Personal" nav section -- iOS parity port (2026-08-27) of desktop's
/// own PersonalView.swift. Goals and habits only, display-only here --
/// creation/updates happen through Frank in conversation, same as
/// desktop. Near-verbatim copy, no AppKit dependency to work around, and
/// every type it depends on (PersonalClient, PersonalGoal, PersonalHabit)
/// was already shared cross-platform in PCorpKit.
struct PersonalView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = PersonalClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if client.isLoading && client.dashboard == nil {
                        Text("Loading…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let dashboard = client.dashboard {
                        section(title: "GOALS") {
                            if dashboard.goals.isEmpty {
                                emptyRow("Nothing yet — tell Frank about a goal and it'll show up here.")
                            } else {
                                ForEach(dashboard.goals) { goal in
                                    GoalRow(goal: goal)
                                }
                            }
                        }
                        section(title: "HABITS") {
                            if dashboard.habits.isEmpty {
                                emptyRow("Nothing yet — tell Frank about a habit to track and it'll show up here.")
                            } else {
                                ForEach(dashboard.habits) { habit in
                                    HabitRow(habit: habit)
                                }
                            }
                        }
                    }
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
                Text("Personal")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Goals and habits — tell Frank, they show up here")
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
    private func section<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
            VStack(alignment: .leading, spacing: 10) {
                content()
            }
        }
    }

    private func emptyRow(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.textSecondary)
    }
}

private struct GoalRow: View {
    let goal: PersonalGoal
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(goal.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                if let target = goal.targetDate {
                    Text("Target: \(target)")
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                if let notes = goal.notes {
                    Text(notes)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
            }
            Spacer()
            Text(goal.status.capitalized)
                .font(PCorpFont.label(9))
                .trackedLabel(1.0)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}

private struct HabitRow: View {
    let habit: PersonalHabit
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(habit.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                if let notes = habit.notes {
                    Text(notes)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
            }
            Spacer()
            if let cadence = habit.cadence {
                Text(cadence.capitalized)
                    .font(PCorpFont.label(9))
                    .trackedLabel(1.0)
                    .foregroundStyle(theme.textSecondary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}
