import SwiftUI
import PCorpKit

/// Close port of desktop's own JoshxView.swift (2026-08-25 iOS parity
/// pass) -- entirely built on PCorpKit's already-cross-platform
/// JoshxClient/JoshxDashboard/JoshxProject/JoshxLead/JoshxClientRecord,
/// no AppKit dependencies, so this is a direct, unmodified port,
/// including the same theme.accent visual-identity marker desktop uses
/// (see Sidebar.swift's own iOS port of that same choice).
struct JoshxView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = JoshxClient()
    @State private var selectedProject: JoshxProject?
    @State private var leadPendingDelete: JoshxLead?
    @State private var projectPendingDelete: JoshxProject?
    @State private var clientPendingDelete: JoshxClientRecord?

    // Mirrors backend/app/joshx_db.py's _CLOSED_LEAD_STAGES -- a booked
    // or lost lead is done, and (2026-08-31) shouldn't clutter the
    // active leads list just because nothing auto-closed/deleted it.
    private static let closedLeadStages: Set<String> = ["booked", "lost"]

    private func openLeads(_ dashboard: JoshxDashboard) -> [JoshxLead] {
        dashboard.leads.filter { !Self.closedLeadStages.contains($0.stage) }
    }

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
                    } else if let dashboard = client.dashboard {
                        // See desktop's own JoshxView.swift for why a
                        // loaded dashboard wins over errorMessage here
                        // (systems audit §18 sweep, 2026-09-06) -- a
                        // write failure shouldn't hide an already-loaded
                        // dashboard behind a bare error screen.
                        if let error = client.errorMessage {
                            Text(error)
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.statusRisk)
                        }
                        statsRow(dashboard: dashboard, analytics: client.analytics)
                        section(title: "PROJECTS") {
                            if dashboard.projects.isEmpty {
                                emptyRow("No projects yet — tell Frank about a Joshx booking to get started.")
                            } else {
                                ForEach(dashboard.projects) { project in
                                    Button {
                                        selectedProject = project
                                    } label: {
                                        ProjectRow(project: project)
                                    }
                                    .buttonStyle(.plain)
                                    .contextMenu {
                                        Button("Delete Project", role: .destructive) {
                                            projectPendingDelete = project
                                        }
                                    }
                                }
                            }
                        }
                        section(title: "LEADS") {
                            if dashboard.leads.isEmpty {
                                emptyRow("No leads yet — tell Frank about a Joshx opportunity to get started.")
                            } else if openLeads(dashboard).isEmpty {
                                emptyRow("No leads currently open — booked/lost ones are hidden here.")
                            } else {
                                ForEach(openLeads(dashboard)) { lead in
                                    LeadRow(lead: lead)
                                        .contextMenu {
                                            Button("Delete Lead", role: .destructive) {
                                                leadPendingDelete = lead
                                            }
                                        }
                                }
                            }
                        }
                        section(title: "CLIENTS") {
                            if dashboard.clients.isEmpty {
                                emptyRow("No clients yet — tell Frank about a Joshx client to get started.")
                            } else {
                                ForEach(dashboard.clients) { record in
                                    ClientRow(record: record)
                                        .contextMenu {
                                            Button("Delete Client", role: .destructive) {
                                                clientPendingDelete = record
                                            }
                                        }
                                }
                            }
                        }
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                .padding(20)
            }
            .refreshable { await client.fetch() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
        .sheet(item: $selectedProject) { project in
            JoshxProjectDetailSheet(project: project, client: client)
        }
        .confirmationDialog(
            "Delete lead for \(leadPendingDelete?.clientName ?? "")?",
            isPresented: Binding(get: { leadPendingDelete != nil }, set: { if !$0 { leadPendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let lead = leadPendingDelete {
                    Task { await client.deleteLead(id: lead.id) }
                }
                leadPendingDelete = nil
            }
            Button("Cancel", role: .cancel) { leadPendingDelete = nil }
        }
        .confirmationDialog(
            "Delete project \"\(projectPendingDelete?.projectName ?? "")\"?",
            isPresented: Binding(get: { projectPendingDelete != nil }, set: { if !$0 { projectPendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let project = projectPendingDelete {
                    Task { await client.deleteProject(id: project.id) }
                }
                projectPendingDelete = nil
            }
            Button("Cancel", role: .cancel) { projectPendingDelete = nil }
        }
        .confirmationDialog(
            "Delete client \"\(clientPendingDelete?.name ?? "")\"?",
            isPresented: Binding(get: { clientPendingDelete != nil }, set: { if !$0 { clientPendingDelete = nil } }),
            titleVisibility: .visible
        ) {
            Button("Delete", role: .destructive) {
                if let record = clientPendingDelete {
                    Task { await client.deleteClient(id: record.id) }
                }
                clientPendingDelete = nil
            }
            Button("Cancel", role: .cancel) { clientPendingDelete = nil }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text("JOSHX")
                    .font(PCorpFont.label(11))
                    .trackedLabel(1.6)
                    .foregroundStyle(theme.accent)
                Text("Joshua Peters")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Freelance Filmmaker / Video Editor / Photographer")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            RefreshIconButton { await client.fetch() }
        }
        .padding(20)
    }

    @ViewBuilder
    private func statsRow(dashboard: JoshxDashboard, analytics: JoshxAnalytics?) -> some View {
        HStack(spacing: 0) {
            statItem(label: "ACTIVE PROJECTS", value: dashboard.activeProjects)
            statDivider
            statItem(label: "OPEN LEADS", value: dashboard.openLeads)
            statDivider
            statItem(label: "UPCOMING SHOOTS", value: dashboard.upcomingShoots)
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))

        // Performance metrics (2026-09-06, systems audit §3) -- replaces
        // the old "arrives in a later phase" disclaimer, factually stale
        // since invoices/expenses shipped weeks earlier. Real sample
        // sizes are small today, so every tile shows its own `n` rather
        // than a bare rate/average, matching the desktop port of this
        // same change and compute_performance_metrics()'s own discipline.
        if let analytics {
            HStack(spacing: 0) {
                metricStatItem(
                    label: "REPEAT CLIENTS",
                    value: analytics.repeatClientRate.map { "\(Int(($0 * 100).rounded()))%" } ?? "—",
                    caption: "\(analytics.repeatClients) of \(analytics.distinctClients) clients"
                )
                statDivider
                metricStatItem(
                    label: "AVG PROJECT VALUE",
                    value: analytics.avgProjectValue.map { "R\(Int($0.rounded()))" } ?? "—",
                    caption: analytics.pricedProjects == 0 ? "no priced projects yet" : "across \(analytics.pricedProjects) project(s)"
                )
                statDivider
                metricStatItem(
                    label: "LEAD CONVERSION",
                    value: analytics.leadConversionRate.map { "\(Int(($0 * 100).rounded()))%" } ?? "—",
                    caption: analytics.totalLeads == 0 ? "no leads yet" : "\(analytics.convertedLeads) of \(analytics.totalLeads) leads"
                )
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
            .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))

            Text("\(analytics.projectsCreatedThisMonth) project(s) created this month, \(analytics.projectsCreatedLastMonth) last month.")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textTertiary)
        }
    }

    private var statDivider: some View {
        Rectangle()
            .fill(theme.divider)
            .frame(width: 1, height: 28)
    }

    private func statItem(label: String, value: Int) -> some View {
        VStack(spacing: 4) {
            Text("\(value)")
                .font(PCorpFont.mono(20, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(label)
                .font(PCorpFont.label(8.5))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
        }
        .frame(maxWidth: .infinity)
    }

    private func metricStatItem(label: String, value: String, caption: String) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(PCorpFont.mono(20, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(label)
                .font(PCorpFont.label(8.5))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            Text(caption)
                .font(PCorpFont.body(9.5))
                .foregroundStyle(theme.textTertiary)
        }
        .frame(maxWidth: .infinity)
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

private struct ProjectRow: View {
    let project: JoshxProject
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(project.projectName)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(subtitle)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
                if let detailLine {
                    Text(detailLine)
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                        .lineLimit(2)
                }
            }
            Spacer()
            Text(project.status)
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
        var parts = [project.clientName]
        if let type = project.projectType { parts.append(type) }
        if let due = project.dueDate { parts.append("due \(due)") }
        return parts.joined(separator: " — ")
    }

    // Real bug found live (2026-08-27): brief/deliverables were already
    // stored (add_joshx_project writes both) but never shown anywhere on
    // either platform -- the gap was in the backend's own dashboard
    // SELECT, not here; this line just renders what's now actually
    // returned.
    private var detailLine: String? {
        var parts: [String] = []
        if let brief = project.brief, !brief.isEmpty { parts.append(brief) }
        if let deliverables = project.deliverables, !deliverables.isEmpty { parts.append("Deliverables: \(deliverables)") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

private struct LeadRow: View {
    let lead: JoshxLead
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(lead.clientName)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(subtitle)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
                if let notes = lead.notes, !notes.isEmpty {
                    Text(notes)
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                        .lineLimit(2)
                }
            }
            Spacer()
            Text(lead.stage)
                .font(PCorpFont.label(9))
                .trackedLabel(1.0)
                .foregroundStyle(theme.accent)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(theme.accent.opacity(0.12)))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }

    private var subtitle: String {
        var parts: [String] = []
        if let service = lead.service { parts.append(service) }
        if let value = lead.estimatedValue { parts.append("est. R\(String(format: "%.2f", value))") }
        // Real bug found live (2026-08-27): budget/lead_source were
        // already stored but never shown -- see joshx_db.py's own
        // dashboard_snapshot() SELECT for where the gap actually was.
        if let budget = lead.budget { parts.append("budget R\(String(format: "%.2f", budget))") }
        if let source = lead.leadSource { parts.append("via \(source)") }
        return parts.isEmpty ? "No details yet" : parts.joined(separator: " — ")
    }
}

private struct ClientRow: View {
    let record: JoshxClientRecord
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(record.name)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(record.company ?? "No company on file")
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
            Text(record.status)
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

    // Real bug found live (2026-08-27): email/phone/instagram were
    // already stored (add_joshx_client writes all three) but never shown
    // -- see joshx_db.py's own dashboard_snapshot() SELECT for where the
    // gap actually was.
    private var contactLine: String? {
        var parts: [String] = []
        if let email = record.email, !email.isEmpty { parts.append(email) }
        if let phone = record.phone, !phone.isEmpty { parts.append(phone) }
        if let instagram = record.instagram, !instagram.isEmpty { parts.append("@\(instagram)") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
