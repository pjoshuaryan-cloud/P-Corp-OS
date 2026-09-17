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
///
/// Update (2026-09-17, Editability Pass 1): the "display-only... through
/// Frank" note above is now stale -- an audit found this the clearest
/// case of a section whose backend writes (add_goal/add_habit/add_person)
/// already existed as Frank chat tools with no direct UI path to the same
/// calls. Gained real "+Add" inline forms for all three, plus inline
/// editing of People's email/phone via PCorpKit's new InlineEditableText.
struct PersonalView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = PersonalClient()
    @StateObject private var peopleClient = PeopleClient()

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
        .cardSurface(radius: 12)
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
        .cardSurface(radius: 12)
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
        .cardSurface(radius: 12)
    }
}

private struct PersonRow: View {
    let person: Person
    @ObservedObject var peopleClient: PeopleClient
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                // Real gap found live (2026-09-17, same day as the two
                // fixes right below): Josh asked to edit name itself too,
                // not just the fields under it -- update_person already
                // accepted it via its generic **fields, just needed a
                // pre-write uniqueness check (people_db.py) so renaming
                // to a name someone else already has surfaces as a real
                // error instead of a raw database constraint violation.
                InlineEditableText(value: person.name) { newValue in
                    guard !newValue.isEmpty else { return }
                    await peopleClient.updatePerson(id: person.id, name: newValue)
                }
                .font(PCorpFont.body(13.5, weight: .semibold))
                // Real gap found live (2026-09-17, same day as the
                // original Editability Pass 1): relationship_type/company/
                // notes used to be folded into one read-only "subtitle"
                // string -- fine for display, but meant an existing
                // record with real gaps (Josh's own "Robin," relationship_
                // type already "spouse," company/notes genuinely empty)
                // had no way to fill those in, only email/phone were
                // wired up at first. Split into individually editable
                // rows, same InlineEditableText primitive as email/phone
                // below. linkedClientName stays read-only -- it's a
                // cross-reference into Joshx/Alpha Mode Media clients,
                // not free text, out of scope here.
                InlineEditableText(value: person.relationshipType ?? "", placeholder: "Add relationship") { newValue in
                    await peopleClient.updatePerson(id: person.id, relationshipType: newValue)
                }
                .font(PCorpFont.body(11.5))
                InlineEditableText(value: person.company ?? "", placeholder: "Add company") { newValue in
                    await peopleClient.updatePerson(id: person.id, company: newValue)
                }
                .font(PCorpFont.body(11.5))
                if let linked = person.linkedClientName {
                    Text("linked to \(linked)")
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                InlineEditableText(value: person.email ?? "", placeholder: "Add email") { newValue in
                    await peopleClient.updatePerson(id: person.id, email: newValue)
                }
                .font(PCorpFont.body(10.5))
                InlineEditableText(value: person.phone ?? "", placeholder: "Add phone") { newValue in
                    await peopleClient.updatePerson(id: person.id, phone: newValue)
                }
                .font(PCorpFont.body(10.5))
                InlineEditableText(value: person.notes ?? "", placeholder: "Add notes") { newValue in
                    await peopleClient.updatePerson(id: person.id, notes: newValue)
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
        .cardSurface(radius: 12)
    }
}
