import PCorpKit
import SwiftUI

/// Joshx lead detail (2026-09-18) -- real gap found live: LeadRow (in
/// JoshxView.swift) only ever showed clientName/service/estimatedValue/
/// budget/leadSource/a 2-line-truncated notes preview, with no tap
/// target at all. JoshxLead's own projectDescription/probability/
/// followUpDate/createdAt fields were genuinely invisible anywhere in
/// either app -- not a display choice, they were simply never wired up.
///
/// Same "own file, presented as a popover" convention as
/// JoshxProjectDetailPopover.swift (iOS uses `.sheet` instead --
/// see JoshxLeadDetailSheet.swift).
///
/// Update (2026-09-18, same day): "Convert to Project" added -- direct
/// follow-up ("what if they graduate from a lead to a client i want to
/// be able to update that"). Confirmed directly which of two real
/// behaviors he meant (a plain client-status flip vs. a full lead-
/// >project conversion) rather than guessing -- he chose the latter,
/// reusing joshx_db.py's existing convert_lead_to_project transaction
/// (real project created, lead marked 'booked', matching client flipped
/// to 'active') via a new id-based `lead_id` path on that same function,
/// same "id-based sibling of the fuzzy-matched original" shape
/// delete_lead_by_id already established. Only asks for a project name
/// -- everything else convert_lead_to_project can carry forward
/// (budget/brief/notes) it already does automatically from the lead's
/// own fields.
struct JoshxLeadDetailPopover: View {
    let lead: JoshxLead
    @ObservedObject var client: JoshxClient
    /// Called after a successful conversion so the parent can clear
    /// `selectedLead` -- the lead flips to 'booked' and drops out of the
    /// open-leads list, so there's nothing left here worth looking at.
    var onConverted: () -> Void = {}
    @Environment(\.appTheme) private var theme
    @State private var isConverting = false
    @State private var newProjectName = ""
    @State private var isSubmitting = false

    private static let closedStages: Set<String> = ["booked", "lost"]

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

                    if !Self.closedStages.contains(lead.stage) {
                        convertSection
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 380, height: 480)
    }

    @ViewBuilder
    private var convertSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("GRADUATE THIS LEAD")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if isConverting {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Project name", text: $newProjectName)
                        .textFieldStyle(.plain)
                        .font(PCorpFont.body(13))
                    HStack {
                        Button("Cancel") {
                            isConverting = false
                            newProjectName = ""
                        }
                        .font(PCorpFont.body(12))
                        .foregroundStyle(theme.textSecondary)
                        Spacer()
                        Button("Convert", action: submitConversion)
                            .buttonStyle(.actionFilled)
                            .disabled(newProjectName.trimmingCharacters(in: .whitespaces).isEmpty || isSubmitting)
                    }
                }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .cardSurface(radius: 12)
            } else {
                Button("Convert to Project") { isConverting = true }
                    .buttonStyle(.actionFilled)
            }
        }
    }

    private func submitConversion() {
        let projectName = newProjectName
        isSubmitting = true
        Task {
            await client.convertLeadToProject(leadId: lead.id, projectName: projectName)
            isSubmitting = false
            onConverted()
        }
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
