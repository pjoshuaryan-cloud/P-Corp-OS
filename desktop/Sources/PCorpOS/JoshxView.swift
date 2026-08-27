import SwiftUI
import PCorpKit

/// The "Joshx" nav section (2026-08-21) -- Josh's independent freelance
/// creative business (video editing, videography, photography), a
/// completely separate division from Alpha Mode Media per Josh's own
/// spec: no switcher, no shared dashboard, no "current division"
/// selector, own local data store (backend/app/joshx_db.py's joshx.db).
/// Phase 1 scope only, confirmed directly before building anything: the
/// full 28-section vision (quote builder, invoicing, finance/analytics,
/// rate card, availability, equipment, crew, portfolio, creative lab,
/// content pipeline, documents, morning brief/weekly review, and a wholly
/// bespoke "cinematic dark UI" visual identity) is real future scope, not
/// silently dropped -- see backend/app/joshx_db.py's own docstring.
///
/// Visual identity is the shared theme plus `theme.accent` as the one
/// distinguishing marker (Sidebar.swift's icon color, and this view's
/// header) -- Josh chose this over building the full bespoke redesign now,
/// same "foundation before finish" call already made on every other large
/// brief in this app (Face-Lift, Trading Division, Personal).
///
/// Same GET-and-render pattern as PersonalView/TradingDivisionView. Data
/// entry is Frank-only for now (app/joshx_tools.py), same "regular"
/// permission-tier, no-dedicated-UI-yet call already made for Personal
/// and Alpha Mode Media's own early days.
struct JoshxView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = JoshxClient()

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
                        statsRow(dashboard: dashboard)
                        section(title: "PROJECTS") {
                            if dashboard.projects.isEmpty {
                                emptyRow("No projects yet — tell Frank about a Joshx booking to get started.")
                            } else {
                                ForEach(dashboard.projects) { project in
                                    ProjectRow(project: project)
                                }
                            }
                        }
                        section(title: "LEADS") {
                            if dashboard.leads.isEmpty {
                                emptyRow("No leads yet — tell Frank about a Joshx opportunity to get started.")
                            } else {
                                ForEach(dashboard.leads) { lead in
                                    LeadRow(lead: lead)
                                }
                            }
                        }
                        section(title: "CLIENTS") {
                            if dashboard.clients.isEmpty {
                                emptyRow("No clients yet — tell Frank about a Joshx client to get started.")
                            } else {
                                ForEach(dashboard.clients) { record in
                                    ClientRow(record: record)
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
    private func statsRow(dashboard: JoshxDashboard) -> some View {
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

        Text("Revenue, outstanding invoices, and availability tracking arrive in a later phase — not shown until there's a real Money/Availability system behind them.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)
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
