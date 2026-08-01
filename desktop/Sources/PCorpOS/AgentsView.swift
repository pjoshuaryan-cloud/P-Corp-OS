import SwiftUI

/// The "Agents" nav section — makes Frank's delegated specialists and
/// their real, persistent data actually visible, rather than only
/// existing as something Frank calls via tool-use during conversation
/// with no way to see it directly (the same gap the "Frank" nav section
/// closed for memory_records). Operations Agent is the only specialist
/// so far (backend/app/operations_agent.py) — its advisory output (SOPs,
/// workflow suggestions) stays conversational, but its one piece of real
/// persistent data, task tracking, is made visible here read-only.
struct AgentsView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = OperationsClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    OperationsAgentCard()
                    taskSection
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
                Text("Agents")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Specialists Frank can delegate to")
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
    private var taskSection: some View {
        HStack(spacing: 8) {
            Text("OPEN TASKS")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
            Spacer()
        }

        if client.isLoading && client.tasks.isEmpty {
            Text("Loading…")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if let error = client.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if client.tasks.isEmpty {
            Text("Nothing open — ask Frank to add a task, or delegate something to the Operations Agent.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            LazyVStack(alignment: .leading, spacing: 10) {
                ForEach(client.tasks) { task in
                    TaskRow(task: task)
                }
            }
        }
    }
}

private struct OperationsAgentCard: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(.regularMaterial).frame(width: 40, height: 40)
                    Image(systemName: "checklist")
                        .font(.system(size: 16))
                        .foregroundStyle(theme.textPrimary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text("Operations Agent")
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text("SOPs, workflows, project planning, bottlenecks, automation")
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
            Text("Ask Frank to draft an SOP, plan a project, spot a bottleneck, or suggest an automation — he decides when to consult this agent rather than answering directly.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 14).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(theme.surfaceBorder))
    }
}

private struct TaskRow: View {
    let task: OperationsTask
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    if let area = task.area {
                        Text(area.uppercased())
                            .font(PCorpFont.label(9))
                            .trackedLabel(1.0)
                            .foregroundStyle(.blue)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(Capsule().fill(Color.blue.opacity(0.12)))
                    }
                    Spacer()
                    if let due = task.dueDate {
                        Text("Due \(due)")
                            .font(PCorpFont.body(10.5))
                            .foregroundStyle(theme.textTertiary)
                    }
                }
                Text(task.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                if let notes = task.notes {
                    Text(notes)
                        .font(PCorpFont.body(12))
                        .foregroundStyle(theme.textSecondary)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}
