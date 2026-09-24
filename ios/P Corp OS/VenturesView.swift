import SwiftUI
import PCorpKit

/// iOS port of desktop's own VenturesView.swift -- see that file's
/// docstring for the full reasoning (2026-09-23, Phase 1). Same
/// structure ported to the plain top-level-screen shape every other
/// division uses on iOS (TradingDivisionView.swift/JoshxView.swift),
/// not the sheet-with-NavigationStack chrome TradeIntelligenceView.swift
/// uses -- Ventures is its own top-level nav destination, not a modal
/// launched from within another screen.
struct VenturesView: View {
    @StateObject private var client = VenturesClient()
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    private enum Section: String, CaseIterable, Identifiable {
        case overview = "Overview"
        case ventures = "Ventures"
        case opportunities = "Opportunities"
        var id: String { rawValue }
    }
    @State private var selectedSection: Section = .overview
    @State private var selectedVenture: Venture?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            if !client.deltaEvents.isEmpty {
                whatsNewBanner
            }
            Divider().overlay(theme.divider)
            Picker("", selection: $selectedSection) {
                ForEach(Section.allCases) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.top, 12)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    switch selectedSection {
                    case .overview: overviewSection
                    case .ventures: venturesSection
                    case .opportunities: opportunitiesSection
                    }
                }
                .padding(16)
            }
            .refreshable { await client.fetch() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task {
            await client.fetch()
            await client.fetchDelta()
        }
        .sheet(item: $selectedVenture) { venture in
            VentureDetailView(venture: venture, client: client)
        }
    }

    @State private var isWhatsNewExpanded = false

    private var whatsNewBanner: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                isWhatsNewExpanded.toggle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "sparkles")
                    Text("\(client.deltaEvents.count) update\(client.deltaEvents.count == 1 ? "" : "s") since you last checked")
                        .font(PCorpFont.body(11.5, weight: .medium))
                    Spacer()
                    Image(systemName: isWhatsNewExpanded ? "chevron.up" : "chevron.down")
                        .font(.system(size: 9))
                }
                .foregroundStyle(theme.statusHot)
            }
            .buttonStyle(.plain)
            if isWhatsNewExpanded {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(client.deltaEvents.prefix(10)) { event in
                        Text(deltaEventLabel(event.toolName))
                            .font(PCorpFont.body(11))
                            .foregroundStyle(theme.textSecondary)
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private func deltaEventLabel(_ toolName: String) -> String {
        toolName
            .replacingOccurrences(of: "venture_", with: "")
            .replacingOccurrences(of: "_ui", with: "")
            .replacingOccurrences(of: "_", with: " ")
            .capitalized
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Ventures")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Business creation: opportunity discovery and a simple venture pipeline")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            RefreshIconButton { await client.fetch() }
        }
        .padding(20)
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(10))
            .trackedLabel(1.1)
            .foregroundStyle(theme.textSecondary)
    }

    private func plainField(_ placeholder: String, text: Binding<String>) -> some View {
        TextField(placeholder, text: text)
            .textFieldStyle(.plain)
            .font(PCorpFont.body(12.5))
            .padding(10)
            .cardSurface(radius: 8)
    }

    private func errorText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.statusRisk)
    }

    // MARK: - Overview

    @ViewBuilder
    private var overviewSection: some View {
        if let error = client.errorMessage { errorText(error) }
        if client.isLoading && client.dashboard == nil {
            SkeletonList(count: 3)
        } else if let dashboard = client.dashboard {
            sectionLabel("AT A GLANCE")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                statCard("Total Ventures", "\(dashboard.totalVentures)")
                statCard("Active", "\(dashboard.activeVentures)")
                statCard("Validating", "\(dashboard.testingVentures)")
                statCard("Paused", "\(dashboard.pausedVentures)")
                statCard("Closed", "\(dashboard.closedVentures)")
                statCard("Monthly Revenue", "R\(String(format: "%.2f", dashboard.totalMonthlyRevenue))")
                statCard("Real Revenue (30d)", "R\(String(format: "%.2f", dashboard.totalRevenueLast30d))")
            }
            Text("Monthly revenue is Josh's own entered figure per venture, not real bookkeeping. Real Revenue (30d) is computed from actual logged customer revenue events, summed across ventures with any -- the two won't match until a venture has real sales.")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)

            Divider().overlay(theme.divider).padding(.vertical, 4)

            sectionLabel("PIPELINE")
            VStack(alignment: .leading, spacing: 6) {
                ForEach(ventureStatusOptions, id: \.self) { status in
                    HStack {
                        Text(status.capitalized)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textPrimary)
                        Spacer()
                        Text("\(dashboard.byStatus[status] ?? 0)")
                            .font(PCorpFont.body(12, weight: .semibold))
                            .foregroundStyle(theme.textSecondary)
                    }
                    .padding(8)
                    .cardSurface(radius: 6)
                }
            }
        } else {
            Text("No data yet.").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
        }
    }

    private func statCard(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(PCorpFont.label(8.5))
                .trackedLabel(0.8)
                .foregroundStyle(theme.textTertiary)
            Text(value)
                .font(PCorpFont.body(16, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .cardSurface(radius: 8)
    }

    // MARK: - Ventures

    @State private var isAddingVenture = false
    @State private var draftName = ""
    @State private var draftDescription = ""
    @State private var draftType = ""
    @State private var draftOwnerTime = "low"
    @State private var draftAutomationLevel = "medium"
    @State private var draftSetupCost = ""
    @State private var draftMonthlyRevenue = ""
    @State private var draftRiskLevel = "medium"
    @State private var draftConfidence = "medium"

    private var canSaveVenture: Bool { !draftName.trimmingCharacters(in: .whitespaces).isEmpty }

    @ViewBuilder
    private var venturesSection: some View {
        sectionLabel("ALL VENTURES")
        Button(isAddingVenture ? "Cancel" : "+ Add Venture") { isAddingVenture.toggle() }
            .buttonStyle(.bordered)

        if isAddingVenture {
            addVentureForm
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        if client.isLoading && (client.dashboard?.ventures.isEmpty ?? true) {
            SkeletonList(count: 2)
        } else if let ventures = client.dashboard?.ventures, !ventures.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(ventures) { venture in
                    Button { selectedVenture = venture } label: {
                        VentureRow(
                            venture: venture,
                            onStatusChange: { newStatus in Task { await client.updateVentureStatus(id: venture.id, status: newStatus) } },
                            onDelete: { Task { await client.deleteVenture(id: venture.id) } }
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        } else {
            Text("No ventures yet -- add one manually, or promote an opportunity from the Opportunities tab.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        }
    }

    @ViewBuilder
    private var addVentureForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            plainField("Name", text: $draftName)
            plainField("Description (optional)", text: $draftDescription)
            plainField("Type (optional, e.g. Subscription)", text: $draftType)
            Picker("Owner time", selection: $draftOwnerTime) {
                ForEach(ventureLevelOptions, id: \.self) { Text($0.capitalized).tag($0) }
            }
            Picker("Automation", selection: $draftAutomationLevel) {
                ForEach(ventureLevelOptions, id: \.self) { Text($0.capitalized).tag($0) }
            }
            Picker("Risk", selection: $draftRiskLevel) {
                ForEach(ventureLevelOptions, id: \.self) { Text($0.capitalized).tag($0) }
            }
            Picker("Confidence", selection: $draftConfidence) {
                ForEach(ventureConfidenceOptions, id: \.self) { Text($0.capitalized).tag($0) }
            }
            plainField("Setup cost (optional)", text: $draftSetupCost)
            plainField("Monthly revenue (optional)", text: $draftMonthlyRevenue)

            AsyncButton(action: saveVenture) {
                Text("Save Venture")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canSaveVenture)
        }
        .padding(12)
        .cardSurface(radius: 10)
    }

    private func saveVenture() async {
        let draft = VentureDraft(
            name: draftName, description: draftDescription.isEmpty ? nil : draftDescription, status: "idea",
            type: draftType.isEmpty ? nil : draftType, ownerTime: draftOwnerTime, automationLevel: draftAutomationLevel,
            setupCost: Double(draftSetupCost), monthlyRevenue: Double(draftMonthlyRevenue) ?? 0,
            riskLevel: draftRiskLevel, confidence: draftConfidence
        )
        let succeeded = await client.createVenture(draft)
        if succeeded {
            toastCenter.show("Venture created", style: .success)
            draftName = ""; draftDescription = ""; draftType = ""; draftSetupCost = ""; draftMonthlyRevenue = ""
            isAddingVenture = false
        }
    }

    // MARK: - Opportunities

    @ViewBuilder
    private var opportunitiesSection: some View {
        sectionLabel("OPPORTUNITY RADAR")
        Text("Scans daily in the background for real, concrete opportunities grounded in Josh's own context. Never spends money, launches anything, or contacts anyone -- promoting one to a real venture is your own explicit action.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)

        AsyncButton(action: { await client.scanNow() }) {
            Text("Scan Now")
        }
        .buttonStyle(.bordered)
        .disabled(client.isScanning)
        if client.isScanning {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Scanning the market…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
            }
        }
        if let error = client.errorMessage { errorText(error) }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("PENDING REVIEW")
        if client.opportunities.isEmpty {
            Text("No opportunities waiting for review.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(client.opportunities) { opportunity in
                    OpportunityRow(
                        opportunity: opportunity,
                        onPromote: { Task { await client.promoteOpportunity(id: opportunity.id) } },
                        onDismiss: { Task { await client.dismissOpportunity(id: opportunity.id) } }
                    )
                }
            }
        }
    }
}

private struct VentureRow: View {
    let venture: Venture
    let onStatusChange: (String) -> Void
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    private var scoreColor: Color {
        switch venture.scoreLabel {
        case "healthy": return theme.statusGood
        case "watch": return theme.statusHot
        case "experimental": return theme.textSecondary
        default: return theme.textTertiary
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text(venture.name)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                if let scoreLabel = venture.scoreLabel {
                    Text(scoreLabel.uppercased())
                        .font(PCorpFont.label(8.5))
                        .trackedLabel(0.8)
                        .foregroundStyle(scoreColor)
                }
                Spacer()
                Menu(venture.status.capitalized) {
                    ForEach(ventureStatusOptions, id: \.self) { status in
                        Button(status.capitalized) { onStatusChange(status) }
                    }
                }
                .font(PCorpFont.body(11))
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(.system(size: 11))
                        .foregroundStyle(theme.textTertiary)
                }
                .buttonStyle(.plain)
            }
            if let description = venture.description, !description.isEmpty {
                Text(description)
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
            }
            HStack(spacing: 10) {
                if let automation = venture.automationLevel {
                    Text("Automation: \(automation.capitalized)")
                }
                if let ownerTime = venture.ownerTime {
                    Text("Owner time: \(ownerTime.capitalized)")
                }
                Text("R\(String(format: "%.2f", venture.monthlyRevenue))/mo")
            }
            .font(PCorpFont.body(10.5))
            .foregroundStyle(theme.textTertiary)
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}

private struct OpportunityRow: View {
    let opportunity: Opportunity
    let onPromote: () -> Void
    let onDismiss: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(opportunity.name)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Spacer()
                if opportunity.source == "radar" {
                    Text("RADAR")
                        .font(PCorpFont.label(8.5))
                        .trackedLabel(0.8)
                        .foregroundStyle(theme.statusHot)
                }
            }
            Text(opportunity.description)
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
            HStack(spacing: 10) {
                if let automation = opportunity.automationPotential {
                    Text("Automation: \(automation.capitalized)")
                }
                if let ownerTime = opportunity.ownerTimeRequired {
                    Text("Owner time: \(ownerTime.capitalized)")
                }
                if let confidence = opportunity.confidence {
                    Text("Confidence: \(confidence.capitalized)")
                }
            }
            .font(PCorpFont.body(10.5))
            .foregroundStyle(theme.textTertiary)
            if let risks = opportunity.risks {
                Text("Risks: \(risks)")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
            }
            if let nextStep = opportunity.recommendedNextStep {
                Text("Next step: \(nextStep)")
                    .font(PCorpFont.body(11, weight: .medium))
                    .foregroundStyle(theme.textPrimary)
            }
            HStack(spacing: 8) {
                Button("Promote to Venture", action: onPromote)
                    .buttonStyle(.borderedProminent)
                Button("Dismiss", action: onDismiss)
                    .buttonStyle(.bordered)
            }
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}
