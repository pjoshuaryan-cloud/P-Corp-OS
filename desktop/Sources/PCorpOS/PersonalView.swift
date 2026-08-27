import SwiftUI
import PCorpKit

/// The "Personal" nav section (2026-08-17) -- second of the three
/// deliberately-blocked sections to become real, and deliberately much
/// narrower than AGENTS_VISION.md's full Life Agent vision (which also
/// covers marriage, health, family, journal, reflection -- all still
/// fenced off, per ROADMAP.md's "sensitive-material policy" note).
/// Confirmed directly with Joshua (2026-08-17): goals and habits only,
/// display-only here -- creation/updates happen through Frank in
/// conversation (add_goal/update_goal_status/delete_goal/add_habit/
/// delete_habit, backend/app/personal_tools.py), same as memory_records.
/// No agent commentary or advice anywhere in this screen, on purpose.
///
/// Same GET-and-render pattern as TradingDivisionView/AlphaModeDashboardView.
///
/// Update (2026-08-27): gained a real "PEOPLE" section (backend/app/
/// people_db.py) -- this view's own subtitle has read "Life &
/// Relationships" since it was first built, while its actual content was
/// only ever goals/habits; People/Relationships closes that gap rather
/// than opening a fourth "personal" nav destination. Deliberately a
/// sibling PeopleClient, not a merged dashboard call -- same "each data
/// source independently fetchable/failable" pattern WarRoomView already
/// uses for focusClient/insightsClient, so a failure in one section never
/// blanks the other.
struct PersonalView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = PersonalClient()
    @StateObject private var peopleClient = PeopleClient()

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

                    if peopleClient.isLoading && peopleClient.dashboard == nil {
                        section(title: "PEOPLE") {
                            Text("Loading…")
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.textSecondary)
                        }
                    } else if let error = peopleClient.errorMessage {
                        section(title: "PEOPLE") {
                            Text(error)
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.textSecondary)
                        }
                    } else if let peopleDashboard = peopleClient.dashboard {
                        section(title: "PEOPLE") {
                            if peopleDashboard.people.isEmpty {
                                emptyRow("Nothing yet — tell Frank about someone to track and it'll show up here.")
                            } else {
                                ForEach(peopleDashboard.people) { person in
                                    PersonRow(person: person)
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
        .task {
            await client.fetch()
            await peopleClient.fetch()
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Personal")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Goals, habits, and relationships — tell Frank, they show up here")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                Task {
                    await client.fetch()
                    await peopleClient.fetch()
                }
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

private struct PersonRow: View {
    let person: Person
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(person.name)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(subtitle)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
                if let contactLine {
                    Text(contactLine)
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                        .lineLimit(1)
                }
            }
            Spacer()
            Text("Last contact: \(person.lastContactDate ?? "never")")
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

    private var subtitle: String {
        var parts: [String] = []
        if let type = person.relationshipType { parts.append(type) }
        if let company = person.company { parts.append(company) }
        if let linked = person.linkedClientName { parts.append("linked to \(linked)") }
        return parts.isEmpty ? "No details on file" : parts.joined(separator: " — ")
    }

    private var contactLine: String? {
        var parts: [String] = []
        if let email = person.email, !email.isEmpty { parts.append(email) }
        if let phone = person.phone, !phone.isEmpty { parts.append(phone) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
