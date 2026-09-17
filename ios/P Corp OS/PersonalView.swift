import SwiftUI
import PCorpKit

/// The "Personal" nav section -- iOS parity port (2026-08-27) of desktop's
/// own PersonalView.swift. Goals and habits, plus real inline "+Add"
/// forms and People contact-field editing (2026-09-17, Editability Pass
/// 1) -- previously display-only, creation/updates only reachable through
/// Frank in conversation; an audit found this the clearest case of a
/// section that never got a real UI write path even though its own
/// backend functions (add_goal/add_habit/add_person) already existed as
/// Frank tools. Near-verbatim copy of desktop, no AppKit dependency to
/// work around, and every type it depends on (PersonalClient,
/// PersonalGoal, PersonalHabit, PeopleClient) is already shared
/// cross-platform in PCorpKit.
/// Update (2026-08-27): gained a real "PEOPLE" section (backend/app/
/// people_db.py) -- ported from desktop's own PersonalView.swift, same
/// reasoning: this view's subtitle has read "Life & Relationships" since
/// it was first built, while its content was only ever goals/habits.
/// Sibling PeopleClient, not a merged dashboard call -- same independent-
/// fetch/fail pattern desktop uses.
struct PersonalView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = PersonalClient()
    @StateObject private var peopleClient = PeopleClient()

    // "+Add" inline forms (2026-09-17, Editability Pass 1) -- add_goal/
    // add_habit/add_person already existed as Frank chat tools; this is
    // just a direct UI path to the same calls, per the doc comment atop
    // this file's own now-stale "display-only... through Frank" claim.
    @State private var isAddingGoal = false
    @State private var newGoalTitle = ""
    @State private var newGoalTargetDate = ""
    @State private var isAddingHabit = false
    @State private var newHabitTitle = ""
    @State private var newHabitCadence = ""
    @State private var isAddingPerson = false
    @State private var newPersonName = ""
    @State private var newPersonEmail = ""
    @State private var newPersonPhone = ""
    @State private var newPersonCompany = ""

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
                        section(title: "GOALS", accessory: { addButton { isAddingGoal.toggle() } }) {
                            if isAddingGoal { goalAddForm }
                            if dashboard.goals.isEmpty && !isAddingGoal {
                                emptyRow("Nothing yet — tell Frank about a goal, or add one above.")
                            } else {
                                ForEach(dashboard.goals) { goal in
                                    GoalRow(goal: goal)
                                }
                            }
                        }
                        section(title: "HABITS", accessory: { addButton { isAddingHabit.toggle() } }) {
                            if isAddingHabit { habitAddForm }
                            if dashboard.habits.isEmpty && !isAddingHabit {
                                emptyRow("Nothing yet — tell Frank about a habit, or add one above.")
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
                        section(title: "PEOPLE", accessory: { addButton { isAddingPerson.toggle() } }) {
                            if isAddingPerson { personAddForm }
                            if peopleDashboard.people.isEmpty && !isAddingPerson {
                                emptyRow("Nothing yet — tell Frank about someone, or add one above.")
                            } else {
                                ForEach(peopleDashboard.people) { person in
                                    PersonRow(person: person, peopleClient: peopleClient)
                                }
                            }
                        }
                    }
                }
                .padding(24)
            }
            .refreshable {
                await client.fetch()
                await peopleClient.fetch()
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
            RefreshIconButton {
                await client.fetch()
                await peopleClient.fetch()
            }
        }
        .padding(24)
    }

    @ViewBuilder
    private func section<Content: View, Accessory: View>(
        title: String,
        @ViewBuilder accessory: () -> Accessory = { EmptyView() },
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title)
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.2)
                    .foregroundStyle(theme.textSecondary)
                Spacer()
                accessory()
            }
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

    private func addButton(action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "plus")
        }
        .buttonStyle(.icon)
    }

    private func addFormSurface<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }

    private func addFormButtons(canSave: Bool, onCancel: @escaping () -> Void, onSave: @escaping () -> Void) -> some View {
        HStack {
            Button("Cancel", action: onCancel)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
            Spacer()
            Button("Save", action: onSave)
                .buttonStyle(.actionFilled)
                .disabled(!canSave)
        }
    }

    private var goalAddForm: some View {
        addFormSurface {
            TextField("Goal title", text: $newGoalTitle)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(13.5))
            TextField("Target date (optional, e.g. 2026-12-31)", text: $newGoalTargetDate)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
            addFormButtons(
                canSave: !newGoalTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                onCancel: { isAddingGoal = false; newGoalTitle = ""; newGoalTargetDate = "" },
                onSave: {
                    let title = newGoalTitle
                    let targetDate = newGoalTargetDate.isEmpty ? nil : newGoalTargetDate
                    newGoalTitle = ""; newGoalTargetDate = ""; isAddingGoal = false
                    Task { await client.addGoal(title: title, targetDate: targetDate) }
                }
            )
        }
    }

    private var habitAddForm: some View {
        addFormSurface {
            TextField("Habit title", text: $newHabitTitle)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(13.5))
            TextField("Cadence (optional, e.g. daily, weekly)", text: $newHabitCadence)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
            addFormButtons(
                canSave: !newHabitTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                onCancel: { isAddingHabit = false; newHabitTitle = ""; newHabitCadence = "" },
                onSave: {
                    let title = newHabitTitle
                    let cadence = newHabitCadence.isEmpty ? nil : newHabitCadence
                    newHabitTitle = ""; newHabitCadence = ""; isAddingHabit = false
                    Task { await client.addHabit(title: title, cadence: cadence) }
                }
            )
        }
    }

    private var personAddForm: some View {
        addFormSurface {
            TextField("Name", text: $newPersonName)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(13.5))
            TextField("Company (optional)", text: $newPersonCompany)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
            TextField("Email (optional)", text: $newPersonEmail)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
            TextField("Phone (optional)", text: $newPersonPhone)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12))
            addFormButtons(
                canSave: !newPersonName.trimmingCharacters(in: .whitespaces).isEmpty,
                onCancel: {
                    isAddingPerson = false
                    newPersonName = ""; newPersonCompany = ""; newPersonEmail = ""; newPersonPhone = ""
                },
                onSave: {
                    let name = newPersonName
                    let company = newPersonCompany.isEmpty ? nil : newPersonCompany
                    let email = newPersonEmail.isEmpty ? nil : newPersonEmail
                    let phone = newPersonPhone.isEmpty ? nil : newPersonPhone
                    newPersonName = ""; newPersonCompany = ""; newPersonEmail = ""; newPersonPhone = ""
                    isAddingPerson = false
                    Task { await peopleClient.addPerson(name: name, company: company, email: email, phone: phone) }
                }
            )
        }
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
    @ObservedObject var peopleClient: PeopleClient
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
                // Real gap found in an audit (2026-09-17, Editability Pass
                // 1): these two used to be one concatenated, read-only
                // "email · phone" Text -- a joined string can't be
                // inline-edited as two separate fields, so this splits
                // into two InlineEditableText rows instead.
                InlineEditableText(value: person.email ?? "", placeholder: "Add email") { newValue in
                    await peopleClient.updatePerson(id: person.id, email: newValue)
                }
                .font(PCorpFont.body(10.5))
                InlineEditableText(value: person.phone ?? "", placeholder: "Add phone") { newValue in
                    await peopleClient.updatePerson(id: person.id, phone: newValue)
                }
                .font(PCorpFont.body(10.5))
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

}
