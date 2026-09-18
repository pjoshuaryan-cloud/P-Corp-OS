import PCorpKit
import SwiftUI

/// iOS port of desktop's own JoshxLeadDetailPopover.swift (2026-09-18)
/// -- same content, same JoshxClient (already shared via PCorpKit).
/// Presented as a `.sheet` from JoshxView rather than desktop's
/// `.popover`, same platform-idiomatic split JoshxProjectDetailSheet
/// already documents.
///
/// Real gap found live: LeadRow only ever showed clientName/service/
/// estimatedValue/budget/leadSource/a 2-line-truncated notes preview,
/// with no tap target at all. JoshxLead's own projectDescription/
/// probability/followUpDate/createdAt fields were genuinely invisible
/// anywhere in either app. Read-only this pass, deliberately -- the ask
/// was "let me see all the details," not "let me edit a lead's stage
/// from here too" (Frank's own update_joshx_lead_stage tool already
/// covers that via chat).
struct JoshxLeadDetailSheet: View {
    let lead: JoshxLead
    @ObservedObject var client: JoshxClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(lead.clientName)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .presentationDetents([.medium, .large])
    }

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(lead.stage)
                    .font(PCorpFont.label(9))
                    .trackedLabel(1.0)
                    .foregroundStyle(theme.accent)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Capsule().fill(theme.accent.opacity(0.12)))

                detailSection

                if let notes = lead.notes, !notes.isEmpty {
                    notesSection(notes)
                }

                clientInfoSection
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
    }

    @ViewBuilder
    private var detailSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("DETAILS")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            VStack(alignment: .leading, spacing: 6) {
                if let description = lead.projectDescription, !description.isEmpty {
                    detailRow("Project", description)
                }
                if let service = lead.service { detailRow("Service", service) }
                if let value = lead.estimatedValue { detailRow("Est. value", "R\(String(format: "%.2f", value))") }
                if let budget = lead.budget { detailRow("Budget", "R\(String(format: "%.2f", budget))") }
                if let source = lead.leadSource { detailRow("Source", source) }
                if let probability = lead.probability { detailRow("Probability", "\(probability)%") }
                if let followUp = lead.followUpDate { detailRow("Follow up", followUp) }
                detailRow("Created", lead.createdAt)
            }
        }
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 84, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }

    private func notesSection(_ notes: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("NOTES")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            Text(notes)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
        }
    }

    /// Same best-effort, no-foreign-key name match as
    /// JoshxProjectDetailSheet's own matchedClient.
    @ViewBuilder
    private var clientInfoSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("CLIENT")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if let record = matchedClient {
                VStack(alignment: .leading, spacing: 6) {
                    if let company = record.company, !company.isEmpty { detailRow("Company", company) }
                    if let email = record.email, !email.isEmpty { detailRow("Email", email) }
                    if let phone = record.phone, !phone.isEmpty { detailRow("Phone", phone) }
                    if let instagram = record.instagram, !instagram.isEmpty { detailRow("Instagram", "@\(instagram)") }
                }
            } else {
                Text("No client record on file for \"\(lead.clientName)\".")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }

    private var matchedClient: JoshxClientRecord? {
        client.dashboard?.clients.first { $0.name.caseInsensitiveCompare(lead.clientName) == .orderedSame }
    }
}
