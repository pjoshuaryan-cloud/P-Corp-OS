import SwiftUI

/// The "Agents" nav section — makes Frank's delegated specialists and
/// their real, persistent data actually visible, rather than only
/// existing as something Frank calls via tool-use during conversation
/// with no way to see it directly (the same gap the "Frank" nav section
/// closed for memory_records). The specialist list itself now comes from
/// GET /agents (backend/app/agents_registry.py) instead of one hardcoded
/// SwiftUI card per agent (fixed 2026-08-04) -- so it keeps showing every
/// real specialist as more get added, with no further UI changes needed.
/// Operations Agent's one piece of real persistent data, task tracking,
/// stays visible read-only below the agent cards.
struct AgentsView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var agentsClient = AgentsClient()
    @StateObject private var opsClient = OperationsClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    agentSection
                    taskSection
                }
                .padding(24)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task {
            await agentsClient.fetch()
            await opsClient.fetch()
        }
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
                Task {
                    await agentsClient.fetch()
                    await opsClient.fetch()
                }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.icon)
        }
        .padding(24)
    }

    @ViewBuilder
    private var agentSection: some View {
        if agentsClient.isLoading && agentsClient.agents.isEmpty {
            Text("Loading…")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if let error = agentsClient.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(agentsClient.agents) { agent in
                    AgentCard(agent: agent)
                }
            }
        }
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

        if opsClient.isLoading && opsClient.tasks.isEmpty {
            Text("Loading…")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if let error = opsClient.errorMessage {
            Text(error)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else if opsClient.tasks.isEmpty {
            Text("Nothing open — ask Frank to add a task, or delegate something to the Operations Agent.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            LazyVStack(alignment: .leading, spacing: 10) {
                ForEach(opsClient.tasks) { task in
                    TaskRow(task: task)
                }
            }
        }
    }
}

private struct AgentCard: View {
    let agent: Agent
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(.regularMaterial).frame(width: 40, height: 40)
                    Image(systemName: agent.icon)
                        .font(.system(size: 16))
                        .foregroundStyle(theme.textPrimary)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(agent.name)
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text(agent.tagline)
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer()
                HStack(spacing: 6) {
                    Circle().fill(agent.status == "active" ? Color.green : Color.gray).frame(width: 6, height: 6)
                    Text(agent.status.uppercased())
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.2)
                        .foregroundStyle(theme.textSecondary)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
            }
            Text(agent.detail)
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
