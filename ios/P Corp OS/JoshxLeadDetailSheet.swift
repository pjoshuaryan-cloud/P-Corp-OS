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
/// anywhere in either app.
///
/// Update (2026-09-18, same day): "Convert to Project" added -- direct
/// follow-up ("what if they graduate from a lead to a client i want to
/// be able to update that"). See desktop's own JoshxLeadDetailPopover.swift
/// for the full reasoning (confirmed which of two real behaviors he
/// meant rather than guessing; reuses joshx_db.py's existing
/// convert_lead_to_project transaction via a new id-based path).
struct JoshxLeadDetailSheet: View {
    let lead: JoshxLead
    @ObservedObject var client: JoshxClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var isConverting = false
    @State private var newProjectName = ""
    @State private var isSubmitting = false

    private static let closedStages: Set<String> = ["booked", "lost"]

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

                if !Self.closedStages.contains(lead.stage) {
                    convertSection
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
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
            dismiss()
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
