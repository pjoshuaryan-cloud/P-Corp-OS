import SwiftUI
import PCorpKit

/// VENTURES Phase 2 (2026-09-24) -- the per-venture detail surface Phase 1
/// never had: tapping a VentureRow in VenturesView opens this, hosting the
/// Validation Engine, Venture Builder, and the Launch Engine's checklist +
/// gate. Shares the parent's VenturesClient instance (not a new one) so a
/// write here (status change, launch) updates the same dashboard data the
/// list view reads from.
struct VentureDetailView: View {
    let venture: Venture
    @ObservedObject var client: VenturesClient
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    private enum Section: String, CaseIterable, Identifiable {
        case overview = "Overview"
        case validation = "Validation"
        case checklist = "Checklist & Launch"
        case customers = "Customers"
        case marketing = "Marketing"
        case automation = "Automation"
        var id: String { rawValue }
    }
    @State private var selectedSection: Section = .overview
    @State private var selectedCustomer: Customer?

    /// The freshest data once fetchVentureDetail lands; falls back to the
    /// row's own venture while that first load is still in flight.
    private var current: Venture { client.ventureDetail?.id == venture.id ? client.ventureDetail! : venture }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Picker("", selection: $selectedSection) {
                ForEach(Section.allCases) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = client.errorMessage { errorText(error) }
                    switch selectedSection {
                    case .overview: overviewSection
                    case .validation: validationSection
                    case .checklist: checklistSection
                    case .customers: customersSection
                    case .marketing: marketingSection
                    case .automation: automationSection
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 520, height: 680)
        .task { await client.fetchVentureDetail(id: venture.id) }
        .popover(item: $selectedCustomer) { customer in
            CustomerDetailView(venture: venture, customer: customer, client: client)
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(current.name)
                    .font(PCorpFont.display(18))
                    .foregroundStyle(theme.textPrimary)
                Menu(current.status.capitalized) {
                    ForEach(ventureStatusOptions, id: \.self) { status in
                        Button(status.capitalized) { Task { await client.updateVentureStatus(id: venture.id, status: status) } }
                    }
                }
                .font(PCorpFont.body(11))
            }
            Spacer()
            RefreshIconButton { await client.fetchVentureDetail(id: venture.id) }
        }
        .padding(16)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
    }

    private func errorText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.statusRisk)
    }

    private func labeledBlock(_ label: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased())
                .font(PCorpFont.label(8.5))
                .trackedLabel(0.8)
                .foregroundStyle(theme.textTertiary)
            Text(text)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
        }
    }

    // MARK: - Overview

    @ViewBuilder
    private var overviewSection: some View {
        if let description = current.description, !description.isEmpty {
            Text(description)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
        HStack(spacing: 10) {
            if let type = current.type { Text(type) }
            if let automation = current.automationLevel { Text("Automation: \(automation.capitalized)") }
            if let ownerTime = current.ownerTime { Text("Owner time: \(ownerTime.capitalized)") }
        }
        .font(PCorpFont.body(10.5))
        .foregroundStyle(theme.textTertiary)

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("CONCEPT & POSITIONING")
        if let concept = current.conceptSummary, !concept.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                labeledBlock("Concept", concept)
                if let positioning = current.positioningCopy, !positioning.isEmpty {
                    labeledBlock("Positioning copy", positioning)
                }
            }
            .padding(10)
            .cardSurface(radius: 8)
        } else {
            Text("No concept drafted yet -- run Venture Builder to generate a concept summary, positioning copy, and a suggested first checklist.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
        AsyncButton(action: { await client.runBuilder(ventureId: venture.id) }) {
            Text(current.conceptSummary == nil ? "Run Venture Builder" : "Regenerate with Venture Builder")
        }
        .buttonStyle(.actionFilled)
        .disabled(client.isRunningBuilder)
        if client.isRunningBuilder {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Drafting concept and checklist…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("CUSTOMER METRICS")
        if let metrics = client.customerMetrics {
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                metricCard("Active", "\(metrics.activeCustomers)")
                metricCard("Churned", "\(metrics.churnedCustomers)")
                metricCard("Churn Rate", metrics.churnRate.map { "\(Int($0 * 100))%" } ?? "Not enough data yet")
                metricCard("Revenue (30d)", "R\(String(format: "%.2f", metrics.revenueLast30d))")
                metricCard("Avg. LTV", metrics.averageLtv.map { "R\(String(format: "%.2f", $0))" } ?? "Not enough data yet")
                metricCard("Avg. CAC", metrics.averageCac.map { "R\(String(format: "%.2f", $0)) (\(metrics.customersWithRecordedCac) of \(metrics.totalCustomers))" } ?? "Not enough data yet")
            }
        } else {
            Text("No customer data yet.").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
        }
        if client.customerMetrics != nil {
            AsyncButton(action: { await client.analyzeFinancials(ventureId: venture.id) }) {
                Text("Analyze Financials")
            }
            .buttonStyle(.bordered)
            .disabled(client.isAnalyzingFinancials)
            if client.isAnalyzingFinancials {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Analyzing…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }
            }
            if let analysis = client.financialAnalysis {
                Text(analysis)
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textPrimary)
                    .padding(10)
                    .cardSurface(radius: 8)
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("OPERATING PROCEDURES")
        if let sop = current.operationsSop, !sop.isEmpty {
            Text(sop)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
                .padding(10)
                .cardSurface(radius: 8)
        } else {
            Text("No operating procedure drafted yet -- generate one to get the ongoing, day-to-day steps for running this venture.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
        AsyncButton(action: { await client.generateOperationsSop(ventureId: venture.id) }) {
            Text(current.operationsSop == nil ? "Generate Operations SOP" : "Regenerate Operations SOP")
        }
        .buttonStyle(.actionFilled)
        .disabled(client.isGeneratingOperationsSop)
        if client.isGeneratingOperationsSop {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Drafting operating procedure…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }

        if !client.ventureDecisions.isEmpty {
            Divider().overlay(theme.divider).padding(.vertical, 4)
            sectionLabel("WHY THIS WAS LAUNCHED")
            VStack(alignment: .leading, spacing: 8) {
                ForEach(client.ventureDecisions) { decision in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(decision.decision)
                            .font(PCorpFont.body(12, weight: .semibold))
                            .foregroundStyle(theme.textPrimary)
                        if let reasoning = decision.reasoning {
                            Text(reasoning)
                                .font(PCorpFont.body(11))
                                .foregroundStyle(theme.textSecondary)
                        }
                        Text(decision.createdAt)
                            .font(PCorpFont.body(10))
                            .foregroundStyle(theme.textTertiary)
                    }
                    .padding(10)
                    .cardSurface(radius: 8)
                }
            }
        }
    }

    private func metricCard(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(PCorpFont.label(8))
                .trackedLabel(0.7)
                .foregroundStyle(theme.textTertiary)
            Text(value)
                .font(PCorpFont.body(13, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .cardSurface(radius: 6)
    }

    // MARK: - Validation

    @ViewBuilder
    private var validationSection: some View {
        Text("Runs a real, evidence-grounded check on this specific venture -- what supports it, what's assumed, what's unknown, what could kill it. Re-run any time for a fresh take; every run is kept, never overwritten.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)
        AsyncButton(action: { await client.runValidation(ventureId: venture.id) }) {
            Text("Run Validation")
        }
        .buttonStyle(.actionFilled)
        .disabled(client.isRunningValidation)
        if client.isRunningValidation {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Researching and validating…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        if client.validationReports.isEmpty {
            Text("No validation reports yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(client.validationReports) { report in
                    ValidationReportCard(report: report)
                }
            }
        }
    }

    // MARK: - Checklist & Launch

    @State private var newItemTitle = ""

    @ViewBuilder
    private var checklistSection: some View {
        sectionLabel("CHECKLIST")
        if client.checklistItems.isEmpty {
            Text("No checklist items yet -- add one manually, or run Venture Builder from Overview to draft a suggested first checklist.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(client.checklistItems) { item in
                    ChecklistItemRow(
                        item: item,
                        onStatusChange: { newStatus in
                            Task { await client.updateChecklistItemStatus(ventureId: venture.id, itemId: item.id, status: newStatus) }
                        },
                        onDelete: { Task { await client.deleteChecklistItem(ventureId: venture.id, itemId: item.id) } }
                    )
                }
            }
        }
        HStack(spacing: 8) {
            TextField("Add a checklist item", text: $newItemTitle)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(12.5))
                .padding(10)
                .cardSurface(radius: 8)
            AsyncButton(action: addItem) {
                Text("Add")
            }
            .buttonStyle(.bordered)
            .disabled(newItemTitle.trimmingCharacters(in: .whitespaces).isEmpty)
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("LAUNCH")
        let pendingCount = client.checklistItems.filter { $0.status == "pending" }.count
        Text(current.status == "build"
             ? "\(pendingCount) checklist item(s) still pending. Launching moves this venture to the growth pipeline stage."
             : "Launching is only available once a venture is in the 'Build' stage (currently \(current.status.capitalized)).")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)
        AsyncButton(action: launchVenture) {
            Text("Launch Venture")
        }
        .buttonStyle(.actionFilled)
        .disabled(current.status != "build")
    }

    private func addItem() async {
        let title = newItemTitle.trimmingCharacters(in: .whitespaces)
        guard !title.isEmpty else { return }
        await client.addChecklistItem(ventureId: venture.id, title: title)
        newItemTitle = ""
    }

    private func launchVenture() async {
        let succeeded = await client.launchVenture(ventureId: venture.id)
        if succeeded {
            toastCenter.show("Venture launched", style: .success)
        }
    }

    // MARK: - Customers

    @State private var isAddingCustomer = false
    @State private var newCustomerName = ""
    @State private var newCustomerSource = ""
    @State private var newCustomerCost = ""

    @ViewBuilder
    private var customersSection: some View {
        sectionLabel("CUSTOMERS")
        Button(isAddingCustomer ? "Cancel" : "+ Add Customer") { isAddingCustomer.toggle() }
            .buttonStyle(.bordered)

        if isAddingCustomer {
            VStack(alignment: .leading, spacing: 8) {
                TextField("Name", text: $newCustomerName)
                    .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
                TextField("Acquisition source (optional)", text: $newCustomerSource)
                    .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
                TextField("Acquisition cost (optional)", text: $newCustomerCost)
                    .textFieldStyle(.plain).font(PCorpFont.body(12.5)).padding(10).cardSurface(radius: 8)
                AsyncButton(action: addCustomer) {
                    Text("Save Customer")
                }
                .buttonStyle(.actionFilled)
                .disabled(newCustomerName.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(12)
            .cardSurface(radius: 10)
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        if client.customers.isEmpty {
            Text("No customers yet -- add one manually as sales come in.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(client.customers) { customer in
                    Button { selectedCustomer = customer } label: {
                        CustomerRow(customer: customer)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func addCustomer() async {
        let name = newCustomerName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        await client.createCustomer(
            ventureId: venture.id, name: name,
            acquisitionSource: newCustomerSource.isEmpty ? nil : newCustomerSource,
            acquisitionCost: Double(newCustomerCost)
        )
        newCustomerName = ""; newCustomerSource = ""; newCustomerCost = ""
        isAddingCustomer = false
    }

    // MARK: - Marketing

    @State private var selectedContentType = "social_post"

    @ViewBuilder
    private var marketingSection: some View {
        sectionLabel("GENERATE CONTENT")
        Picker("Content type", selection: $selectedContentType) {
            ForEach(marketingContentTypeOptions, id: \.self) { Text($0.replacingOccurrences(of: "_", with: " ").capitalized).tag($0) }
        }
        AsyncButton(action: { await client.generateMarketingContent(ventureId: venture.id, contentType: selectedContentType) }) {
            Text("Generate Content")
        }
        .buttonStyle(.actionFilled)
        .disabled(client.isGeneratingMarketingContent)
        if client.isGeneratingMarketingContent {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Drafting content…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("PAST DRAFTS")
        if client.marketingContent.isEmpty {
            Text("No content drafted yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(client.marketingContent) { item in
                    MarketingContentCard(item: item)
                }
            }
        }
    }

    // MARK: - Automation

    @ViewBuilder
    private var automationSection: some View {
        sectionLabel("AUTOMATION SCOUT")
        Text("Reviews this venture and suggests concrete steps that could realistically be automated. Never sets anything up automatically -- every suggestion is yours to review and act on.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)
        AsyncButton(action: { await client.scanForAutomation(ventureId: venture.id) }) {
            Text("Scan for Automation Opportunities")
        }
        .buttonStyle(.actionFilled)
        .disabled(client.isScanningAutomation)
        if client.isScanningAutomation {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Scanning…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("SUGGESTIONS")
        if client.automationSuggestions.isEmpty {
            Text("No automation suggestions yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(client.automationSuggestions) { suggestion in
                    AutomationSuggestionCard(
                        suggestion: suggestion,
                        onImplement: { Task { await client.updateAutomationSuggestionStatus(ventureId: venture.id, suggestionId: suggestion.id, status: "implemented") } },
                        onDismiss: { Task { await client.updateAutomationSuggestionStatus(ventureId: venture.id, suggestionId: suggestion.id, status: "dismissed") } }
                    )
                }
            }
        }
    }
}

private struct CustomerRow: View {
    let customer: Customer
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(customer.name)
                    .font(PCorpFont.body(12.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                if let source = customer.acquisitionSource {
                    Text("via \(source)")
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textTertiary)
                }
            }
            Spacer()
            Text(customer.status.uppercased())
                .font(PCorpFont.label(8))
                .trackedLabel(0.7)
                .foregroundStyle(customer.status == "active" ? theme.statusGood : theme.textTertiary)
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}

private struct ValidationReportCard: View {
    let report: ValidationReport
    @Environment(\.appTheme) private var theme

    private var confidenceColor: Color {
        switch report.confidence {
        case "high": return theme.statusGood
        case "medium": return theme.statusHot
        default: return theme.textTertiary
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(report.createdAt)
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
                Spacer()
                if let confidence = report.confidence {
                    Text(confidence.uppercased())
                        .font(PCorpFont.label(8.5))
                        .trackedLabel(0.8)
                        .foregroundStyle(confidenceColor)
                }
            }
            if let verdict = report.verdict {
                Text(verdict)
                    .font(PCorpFont.body(12, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
            }
            if let evidence = report.evidence { block("Evidence", evidence) }
            if let assumptions = report.assumptions { block("Assumptions", assumptions) }
            if let unknowns = report.unknowns { block("Unknowns", unknowns) }
            if let risks = report.risks { block("Risks", risks) }
        }
        .padding(10)
        .cardSurface(radius: 8)
    }

    private func block(_ label: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(PCorpFont.label(8))
                .trackedLabel(0.8)
                .foregroundStyle(theme.textTertiary)
            Text(text)
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
        }
    }
}

private struct ChecklistItemRow: View {
    let item: ChecklistItem
    let onStatusChange: (String) -> Void
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    private var statusColor: Color {
        switch item.status {
        case "done": return theme.statusGood
        case "skipped": return theme.textTertiary
        default: return theme.statusHot
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textPrimary)
                if item.source == "builder" {
                    Text("SUGGESTED BY BUILDER")
                        .font(PCorpFont.label(7.5))
                        .trackedLabel(0.6)
                        .foregroundStyle(theme.textTertiary)
                }
            }
            Spacer()
            Menu(item.status.capitalized) {
                ForEach(checklistItemStatusOptions, id: \.self) { status in
                    Button(status.capitalized) { onStatusChange(status) }
                }
            }
            .font(PCorpFont.body(10.5))
            .foregroundStyle(statusColor)
            Button(action: onDelete) {
                Image(systemName: "trash")
                    .font(.system(size: 10))
                    .foregroundStyle(theme.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(8)
        .cardSurface(radius: 6)
    }
}

private struct MarketingContentCard: View {
    let item: MarketingContent
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(item.contentType.replacingOccurrences(of: "_", with: " ").capitalized)
                    .font(PCorpFont.label(8.5))
                    .trackedLabel(0.8)
                    .foregroundStyle(theme.statusHot)
                Spacer()
                Text(item.createdAt)
                    .font(PCorpFont.body(10))
                    .foregroundStyle(theme.textTertiary)
            }
            Text(item.content)
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textPrimary)
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}

private struct AutomationSuggestionCard: View {
    let suggestion: AutomationSuggestion
    let onImplement: () -> Void
    let onDismiss: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(suggestion.title)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Spacer()
                if suggestion.status != "new" {
                    Text(suggestion.status.uppercased())
                        .font(PCorpFont.label(8))
                        .trackedLabel(0.7)
                        .foregroundStyle(suggestion.status == "implemented" ? theme.statusGood : theme.textTertiary)
                }
            }
            Text(suggestion.description)
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
            if let approach = suggestion.suggestedApproach {
                Text("Approach: \(approach)")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
            }
            if suggestion.status == "new" {
                HStack(spacing: 8) {
                    Button("Mark Implemented", action: onImplement)
                        .buttonStyle(.actionFilled)
                    Button("Dismiss", action: onDismiss)
                        .buttonStyle(.bordered)
                }
            }
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}
