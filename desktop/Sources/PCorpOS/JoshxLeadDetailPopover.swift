import PCorpKit
import SwiftUI

/// Joshx lead detail (2026-09-18) -- real gap found live: LeadRow (in
/// JoshxView.swift) only ever showed clientName/service/estimatedValue/
/// budget/leadSource/a 2-line-truncated notes preview, with no tap
/// target at all. JoshxLead's own projectDescription/probability/
/// followUpDate/createdAt fields were genuinely invisible anywhere in
/// either app -- not a display choice, they were simply never wired up.
/// Read-only this pass, deliberately -- the ask was "let me see all the
/// details," not "let me edit a lead's stage from here too" (Frank's
/// own update_joshx_lead_stage tool already covers that via chat); a
/// stage-editing Picker here would be a natural, separate follow-up,
/// same shape as JoshxProjectDetailPopover's, not bundled into this.
///
/// Same "own file, presented as a popover" convention as
/// JoshxProjectDetailPopover.swift (iOS uses `.sheet` instead --
/// see JoshxLeadDetailSheet.swift).
struct JoshxLeadDetailPopover: View {
    let lead: JoshxLead
    @ObservedObject var client: JoshxClient
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("LEAD")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(lead.clientName)
                            .font(PCorpFont.body(15, weight: .semibold))
                            .foregroundStyle(theme.textPrimary)
                        Text(lead.stage)
                            .font(PCorpFont.label(9))
                            .trackedLabel(1.0)
                            .foregroundStyle(theme.accent)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(Capsule().fill(theme.accent.opacity(0.12)))
                    }

                    detailSection

                    if let notes = lead.notes, !notes.isEmpty {
                        notesSection(notes)
                    }

                    clientInfoSection
                }
                .padding(16)
            }
        }
        .frame(width: 380, height: 480)
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
                .frame(width: 76, alignment: .leading)
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
    /// JoshxProjectDetailPopover's own matchedClient -- a lead's
    /// clientName is plain text, no guaranteed join to a real client row.
    @ViewBuilder
    private var clientInfoSection: some View {
        if let record = matchedClient {
            VStack(alignment: .leading, spacing: 8) {
                Text("CLIENT")
                    .font(PCorpFont.label(9))
                    .trackedLabel(1.1)
                    .foregroundStyle(theme.textTertiary)
                VStack(alignment: .leading, spacing: 6) {
                    if let company = record.company, !company.isEmpty { detailRow("Company", company) }
                    if let email = record.email, !email.isEmpty { detailRow("Email", email) }
                    if let phone = record.phone, !phone.isEmpty { detailRow("Phone", phone) }
                    if let instagram = record.instagram, !instagram.isEmpty { detailRow("Instagram", "@\(instagram)") }
                }
            }
        }
    }

    private var matchedClient: JoshxClientRecord? {
        client.dashboard?.clients.first { $0.name.caseInsensitiveCompare(lead.clientName) == .orderedSame }
    }
}
