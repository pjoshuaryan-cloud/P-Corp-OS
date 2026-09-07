import PCorpKit
import SwiftUI

/// iOS port of desktop's own JoshxProjectDetailPopover.swift (2026-08-31)
/// -- same content, same JoshxClient (already shared via PCorpKit).
/// Presented as a `.sheet` from JoshxView rather than desktop's
/// `.popover`, same platform-idiomatic split TheBriefSheet already
/// documents (macOS popovers / iOS sheets are each the natural way to
/// show a dismissable secondary view here).
struct JoshxProjectDetailSheet: View {
    let project: JoshxProject
    @ObservedObject var client: JoshxClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var status: String
    @State private var paymentStatus: String

    private static let statusValues = [
        "brief", "pre_production", "production", "post_production",
        "client_review", "revision", "delivery", "paid", "archived",
    ]
    private static let paymentStatusValues = ["unpaid", "partially_paid", "paid"]

    init(project: JoshxProject, client: JoshxClient) {
        self.project = project
        self.client = client
        _status = State(initialValue: project.status)
        _paymentStatus = State(initialValue: project.paymentStatus)
    }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(project.projectName)
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
                Text(project.clientName)
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(theme.textSecondary)

                VStack(alignment: .leading, spacing: 12) {
                    Picker("Status", selection: $status) {
                        ForEach(Self.statusValues, id: \.self) { Text($0) }
                    }
                    .pickerStyle(.menu)
                    .onChange(of: status) { _, newValue in
                        Task { await client.updateProjectStatus(id: project.id, status: newValue) }
                    }

                    Picker("Payment", selection: $paymentStatus) {
                        ForEach(Self.paymentStatusValues, id: \.self) { Text($0) }
                    }
                    .pickerStyle(.menu)
                    .onChange(of: paymentStatus) { _, newValue in
                        Task { await client.updateProjectPaymentStatus(id: project.id, paymentStatus: newValue) }
                    }
                }
                .font(PCorpFont.body(12.5))

                detailSection

                invoicesSection

                expensesSection

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
                if let type = project.projectType { detailRow("Type", type) }
                if let budget = project.budget { detailRow("Budget", "R\(String(format: "%.2f", budget))") }
                if let start = project.startDate { detailRow("Start", start) }
                if let due = project.dueDate { detailRow("Due", due) }
                if let shoot = project.shootDate { detailRow("Shoot", shoot) }
                if let brief = project.brief, !brief.isEmpty { detailRow("Brief", brief) }
                if let deliverables = project.deliverables, !deliverables.isEmpty {
                    detailRow("Deliverables", deliverables)
                }
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

    /// Real invoice data (2026-09-03) -- backend has returned this in every
    /// dashboard fetch since 2026-08-31, but nothing on either platform
    /// ever rendered it until now (the exact gap the P Corp OS systems
    /// audit flagged as the cheapest real win available). Filtered
    /// client-side against `project.id`, same "no foreign-key join"
    /// pattern `matchedClient` below already uses -- a project can
    /// legitimately carry more than one invoice (deposit + final), so this
    /// is a list, not a single field/value row like `detailSection`.
    @ViewBuilder
    private var invoicesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("INVOICES")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if matchedInvoices.isEmpty {
                Text("No invoices yet for this project.")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(matchedInvoices) { invoice in
                        invoiceRow(invoice)
                    }
                }
            }
        }
    }

    private func invoiceRow(_ invoice: JoshxInvoice) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("R\(String(format: "%.2f", invoice.amount)) — \(invoice.status)")
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Text(invoicePaidLine(invoice))
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
        }
    }

    private func invoicePaidLine(_ invoice: JoshxInvoice) -> String {
        var parts = ["R\(String(format: "%.2f", invoice.amountPaid)) paid"]
        if let due = invoice.dueDate { parts.append("due \(due)") }
        return parts.joined(separator: " · ")
    }

    private var matchedInvoices: [JoshxInvoice] {
        client.dashboard?.invoices.filter { $0.projectId == project.id } ?? []
    }

    /// Real expense data (2026-09-03, per-project financials) -- same
    /// "no foreign-key join, plain filter" pattern as matchedInvoices
    /// above. A project accrues multiple real line items (props, fuel,
    /// crew meals), so this is a list with an explicit empty state,
    /// matching invoicesSection's own shape exactly.
    @ViewBuilder
    private var expensesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("EXPENSES")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            if let summary = profitSummaryLine {
                Text(summary)
                    .font(PCorpFont.body(11.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
            }
            if matchedExpenses.isEmpty {
                Text("No expenses logged yet for this project.")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(matchedExpenses) { expense in
                        expenseRow(expense)
                    }
                }
            }
        }
    }

    private func expenseRow(_ expense: JoshxExpense) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("R\(String(format: "%.2f", expense.amount))" + (expense.description.map { " — \($0)" } ?? ""))
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            if let date = expense.incurredDate {
                Text(date)
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }

    private var matchedExpenses: [JoshxExpense] {
        client.dashboard?.expenses.filter { $0.projectId == project.id } ?? []
    }

    /// Revenue = invoiced total once real invoices exist, falling back to
    /// the quoted `budget` if none do yet -- same "richer data wins once
    /// it exists, otherwise don't invent something" precedent as the
    /// backend's own _sync_project_payment_status_from_invoices. Purely a
    /// display computation, never persisted, so it can't drift from the
    /// invoice/expense rows behind it.
    private var revenue: Double {
        matchedInvoices.isEmpty ? (project.budget ?? 0) : matchedInvoices.reduce(0) { $0 + $1.amount }
    }

    private var totalExpenses: Double {
        matchedExpenses.reduce(0) { $0 + $1.amount }
    }

    private var profit: Double {
        revenue - totalExpenses
    }

    /// nil (not "0%") when there's nothing real logged yet -- same
    /// "don't fabricate a stat" discipline as summarize()'s own skip of a
    /// profit line for projects with no invoices/expenses.
    private var profitSummaryLine: String? {
        guard !matchedInvoices.isEmpty || !matchedExpenses.isEmpty else { return nil }
        let marginText = revenue != 0 ? ", \(String(format: "%.0f", profit / revenue * 100))% margin" : ""
        return "R\(String(format: "%.2f", revenue)) revenue · R\(String(format: "%.2f", totalExpenses)) expenses · "
            + "R\(String(format: "%.2f", profit)) profit\(marginText)"
    }

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
                    if let industry = record.industry, !industry.isEmpty { detailRow("Industry", industry) }
                }
            } else {
                Text("No client record on file for \"\(project.clientName)\".")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }

    private var matchedClient: JoshxClientRecord? {
        client.dashboard?.clients.first { $0.name.caseInsensitiveCompare(project.clientName) == .orderedSame }
    }
}
