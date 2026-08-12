import SwiftUI
import PCorpKit

/// The "Alpha Mode Media" nav section (2026-08-10) -- real data from the
/// actual Alpha Mode Media Admin Supabase database (open projects,
/// pending invoices, leads needing follow-up), not the generic unbuilt
/// placeholder this fell into before. Same GET-and-render pattern as
/// AutomationsView; reuses the same underlying data Insights/Situation
/// Room/Opportunity Radar already compute, just surfaced here as a real
/// browsable dashboard instead of only via conversation or the right rail.
struct AlphaModeDashboardView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = AlphaModeDashboardClient()

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
                        section(title: "OPEN PROJECTS") {
                            if dashboard.projects.isEmpty {
                                emptyRow("No projects right now.")
                            } else {
                                ForEach(dashboard.projects) { project in
                                    ProjectRow(project: project)
                                }
                            }
                        }
                        section(title: "PENDING INVOICES") {
                            if dashboard.invoices.isEmpty {
                                emptyRow("Nothing pending or overdue.")
                            } else {
                                ForEach(dashboard.invoices) { invoice in
                                    InvoiceRow(invoice: invoice)
                                }
                            }
                        }
                        section(title: "LEADS NEEDING FOLLOW-UP") {
                            if dashboard.leads.isEmpty {
                                emptyRow("Nothing warm/hot waiting on a follow-up.")
                            } else {
                                ForEach(dashboard.leads) { lead in
                                    LeadRow(lead: lead)
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
                Text("Alpha Mode Media")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Live from the real Alpha Mode Media Admin database")
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

private func titleCase(_ snake: String) -> String {
    snake.split(separator: "_").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: " ")
}

private struct ProjectRow: View {
    let project: AlphaModeProject
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(project.projectName ?? "(untitled)")
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(project.client + (project.dueDate.map { " — due \($0)" } ?? ""))
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Text(titleCase(project.stage))
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

private struct InvoiceRow: View {
    let invoice: AlphaModeInvoice
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(invoice.project.projectName ?? invoice.project.client)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(invoice.project.client + (invoice.dueDate.map { " — due \($0)" } ?? ""))
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 1) {
                Text(invoice.amount, format: .currency(code: "ZAR"))
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(titleCase(invoice.status))
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textSecondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}

private struct LeadRow: View {
    let lead: AlphaModeLead
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "flame")
                .font(.system(size: 13))
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 1) {
                Text(lead.client)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(titleCase(lead.temperature) + (lead.qualificationScore.map { " — qualification score \($0)" } ?? ""))
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}
