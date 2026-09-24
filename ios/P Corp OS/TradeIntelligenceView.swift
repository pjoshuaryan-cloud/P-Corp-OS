import SwiftUI
import PCorpKit
import PhotosUI

/// iOS port of desktop's own TradeIntelligenceView.swift -- see that
/// file's docstring for the full reasoning. Same structural separation
/// from TradingDivisionClient/the read-only Trading Division Agent;
/// AdvisoryDisclaimerBanner mounted exactly once, unconditionally, above
/// the 4-way section switcher. Made conversational 2026-09-21 -- see
/// AdvisoryConversationThread.swift (PCorpKit, genuinely shared).
struct TradeIntelligenceView: View {
    @StateObject private var client = TradeIntelligenceClient()
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var toastCenter: ToastCenter

    private enum Section: String, CaseIterable, Identifiable {
        case setup = "Setup"
        case chart = "Chart"
        case signal = "Signal"
        case position = "Position"
        case breakdown = "Breakdown"
        case propose = "Propose"
        var id: String { rawValue }
    }
    @State private var selectedSection: Section = .setup

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Trade Intelligence")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .presentationDetents([.large])
        .task {
            await client.fetchTrades()
            await client.fetchProposals()
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            AdvisoryDisclaimerBanner()
                .padding(.horizontal, 16)
                .padding(.top, 12)
                .padding(.bottom, 8)
            Picker("", selection: $selectedSection) {
                ForEach(Section.allCases) { section in
                    Text(section.rawValue).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    switch selectedSection {
                    case .setup: tradeSetupSection
                    case .chart: chartAnalysisSection
                    case .signal: signalSection
                    case .position: positionReviewSection
                    case .breakdown: breakdownSection
                    case .propose: proposeSection
                    }
                }
                .padding(16)
            }
        }
        .background(theme.background)
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

    // MARK: - Trade Setup (the comprehensive "should I take this trade" flow)

    @State private var setupImages: [(data: Data, mediaType: String, filename: String)] = []
    @State private var setupSymbol = "NDX"
    @State private var setupQuestion = ""
    @State private var setupPhotoItems: [PhotosPickerItem] = []

    @ViewBuilder
    private var tradeSetupSection: some View {
        sectionLabel("TRADE SETUP")
        Text("The comprehensive one: drop in a chart (optional, up to 4) and ask anything. Grounded in your real account balance, your own logged trade history, and live price/news.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)

        if client.setupMessages.isEmpty {
            if !setupImages.isEmpty {
                HStack(spacing: 6) {
                    ForEach(Array(setupImages.enumerated()), id: \.offset) { index, image in
                        if let uiImage = UIImage(data: image.data) {
                            ZStack(alignment: .topTrailing) {
                                Image(uiImage: uiImage)
                                    .resizable()
                                    .scaledToFill()
                                    .frame(width: 64, height: 64)
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                Button { setupImages.remove(at: index) } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundStyle(theme.textPrimary)
                                        .background(Circle().fill(theme.background))
                                }
                                .buttonStyle(.plain)
                                .offset(x: 4, y: -4)
                            }
                        }
                    }
                }
            }
            PhotosPicker(selection: $setupPhotoItems, maxSelectionCount: 4, matching: .images) {
                Text(setupImages.isEmpty ? "Attach Chart (optional)…" : "Choose Different Images…")
            }
            .buttonStyle(.bordered)
            .onChange(of: setupPhotoItems) { _, newItems in
                guard !newItems.isEmpty else { return }
                Task {
                    var loaded: [(data: Data, mediaType: String, filename: String)] = []
                    for item in newItems.prefix(4) {
                        guard let data = try? await item.loadTransferable(type: Data.self), UIImage(data: data) != nil else { continue }
                        let mediaType = item.supportedContentTypes.first?.preferredMIMEType ?? "image/jpeg"
                        loaded.append((data: data, mediaType: mediaType, filename: "chart_\(loaded.count).\(mediaType == "image/png" ? "png" : "jpg")"))
                    }
                    await MainActor.run { setupImages = loaded }
                }
            }

            plainField("Symbol (optional)", text: $setupSymbol)
            plainField("Where should I buy or sell, and why? How long should I hold? Where should stops go?", text: $setupQuestion)

            if let error = client.setupError { errorText(error) }
            Button("Analyze Setup") { Task { await client.analyzeTradeSetup(images: setupImages, symbol: setupSymbol.isEmpty ? nil : setupSymbol, question: setupQuestion.isEmpty ? nil : setupQuestion) } }
                .buttonStyle(.borderedProminent)
                .disabled(client.isAnalyzingSetup)
            // Real gap found live (2026-09-22, "I want to know if it's
            // doing something") -- a disabled button alone gives no
            // signal that anything is happening, especially here where a
            // real call with an attached image + web search can
            // genuinely take upwards of a minute.
            if client.isAnalyzingSetup { inFlightRow("Analyzing…") }
        } else {
            AdvisoryConversationThread(
                messages: client.setupMessages, isSending: client.isAnalyzingSetup, errorMessage: client.setupError,
                onSend: { text in Task { await client.sendSetupFollowUp(text) } },
                onReset: { client.resetSetup(); setupImages = []; setupQuestion = ""; setupPhotoItems = [] }
            )
            proposeThisTradeButton(client.setupSuggestedTrade)
        }
    }

    // MARK: - Chart Analysis

    @State private var chartImages: [(data: Data, mediaType: String, filename: String)] = []
    @State private var chartSymbol = "NDX"
    @State private var chartNote = ""
    @State private var chartPhotoItems: [PhotosPickerItem] = []

    @ViewBuilder
    private var chartAnalysisSection: some View {
        sectionLabel("CHART ANALYSIS")
        if client.chartMessages.isEmpty {
            Text("Plain-language read of what's visually present — not a calibrated numeric TA engine. Attach up to 4 related charts (e.g. different timeframes) for one combined read.")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textTertiary)

            if !chartImages.isEmpty {
                HStack(spacing: 6) {
                    ForEach(Array(chartImages.enumerated()), id: \.offset) { index, image in
                        if let uiImage = UIImage(data: image.data) {
                            ZStack(alignment: .topTrailing) {
                                Image(uiImage: uiImage)
                                    .resizable()
                                    .scaledToFill()
                                    .frame(width: 64, height: 64)
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                Button { chartImages.remove(at: index) } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundStyle(theme.textPrimary)
                                        .background(Circle().fill(theme.background))
                                }
                                .buttonStyle(.plain)
                                .offset(x: 4, y: -4)
                            }
                        }
                    }
                }
            }
            PhotosPicker(selection: $chartPhotoItems, maxSelectionCount: 4, matching: .images) {
                Text(chartImages.isEmpty ? "Choose Chart Images…" : "Choose Different Images…")
            }
            .buttonStyle(.bordered)
            .onChange(of: chartPhotoItems) { _, newItems in
                guard !newItems.isEmpty else { return }
                Task {
                    var loaded: [(data: Data, mediaType: String, filename: String)] = []
                    for item in newItems.prefix(4) {
                        guard let data = try? await item.loadTransferable(type: Data.self), UIImage(data: data) != nil else { continue }
                        let mediaType = item.supportedContentTypes.first?.preferredMIMEType ?? "image/jpeg"
                        loaded.append((data: data, mediaType: mediaType, filename: "chart_\(loaded.count).\(mediaType == "image/png" ? "png" : "jpg")"))
                    }
                    await MainActor.run { chartImages = loaded }
                }
            }

            plainField("Symbol (optional)", text: $chartSymbol)
            plainField("Note (optional)", text: $chartNote)

            if let error = client.chartAnalysisError { errorText(error) }
            Button("Analyze Chart\(chartImages.count > 1 ? "s" : "")") { Task { await analyzeChart() } }
                .buttonStyle(.borderedProminent)
                .disabled(chartImages.isEmpty || client.isAnalyzingChart)
            if client.isAnalyzingChart { inFlightRow("Analyzing…") }
        } else {
            AdvisoryConversationThread(
                messages: client.chartMessages, isSending: client.isAnalyzingChart, errorMessage: client.chartAnalysisError,
                onSend: { text in Task { await client.sendChartFollowUp(text) } },
                onReset: { client.resetChart(); chartImages = []; chartNote = ""; chartPhotoItems = [] }
            )
            proposeThisTradeButton(client.chartSuggestedTrade)
        }
    }

    private func analyzeChart() async {
        guard !chartImages.isEmpty else { return }
        await client.analyzeChart(images: chartImages, symbol: chartSymbol.isEmpty ? nil : chartSymbol, note: chartNote.isEmpty ? nil : chartNote)
    }

    // MARK: - Trading Signals

    @State private var signalSymbol = "NDX"

    @ViewBuilder
    private var signalSection: some View {
        sectionLabel("TRADING SIGNALS")
        if client.signalMessages.isEmpty {
            plainField("Symbol", text: $signalSymbol)
            if let error = client.signalError { errorText(error) }
            Button("Generate Signal") { Task { await client.generateSignal(symbol: signalSymbol) } }
                .buttonStyle(.borderedProminent)
                .disabled(signalSymbol.trimmingCharacters(in: .whitespaces).isEmpty || client.isGeneratingSignal)
            if client.isGeneratingSignal { inFlightRow("Generating…") }
        } else {
            AdvisoryConversationThread(
                messages: client.signalMessages, isSending: client.isGeneratingSignal, errorMessage: client.signalError,
                onSend: { text in Task { await client.sendSignalFollowUp(text) } },
                onReset: { client.resetSignal() }
            )
            proposeThisTradeButton(client.signalSuggestedTrade)
        }
    }

    // MARK: - Position Review

    @State private var reviewSymbol = "NDX"
    @State private var reviewDirection = "long"
    @State private var reviewEntryPrice = ""
    @State private var reviewSize = ""
    @State private var reviewCurrentPrice = ""
    @State private var reviewStopLoss = ""
    @State private var reviewTakeProfit = ""

    private var canReviewPosition: Bool {
        !reviewSymbol.trimmingCharacters(in: .whitespaces).isEmpty
            && Double(reviewEntryPrice) != nil && Double(reviewSize) != nil && Double(reviewCurrentPrice) != nil
    }

    @ViewBuilder
    private var positionReviewSection: some View {
        sectionLabel("POSITION REVIEW")
        if client.positionMessages.isEmpty {
            plainField("Symbol", text: $reviewSymbol)
            Picker("Direction", selection: $reviewDirection) {
                Text("Long").tag("long")
                Text("Short").tag("short")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            plainField("Entry price", text: $reviewEntryPrice)
            plainField("Size", text: $reviewSize)
            plainField("Current price", text: $reviewCurrentPrice)
            plainField("Stop-loss (optional)", text: $reviewStopLoss)
            plainField("Take-profit (optional)", text: $reviewTakeProfit)

            if let error = client.positionReviewError { errorText(error) }
            Button("Review Position") { Task { await reviewPosition() } }
                .buttonStyle(.borderedProminent)
                .disabled(!canReviewPosition || client.isReviewingPosition)
            if client.isReviewingPosition { inFlightRow("Reviewing…") }
        } else {
            AdvisoryConversationThread(
                messages: client.positionMessages, isSending: client.isReviewingPosition, errorMessage: client.positionReviewError,
                onSend: { text in Task { await client.sendPositionFollowUp(text) } },
                onReset: { client.resetPosition() }
            )
        }
    }

    private func reviewPosition() async {
        guard let entry = Double(reviewEntryPrice), let size = Double(reviewSize), let current = Double(reviewCurrentPrice) else { return }
        await client.reviewPosition(
            symbol: reviewSymbol, direction: reviewDirection, entryPrice: entry, size: size, currentPrice: current,
            stopLoss: Double(reviewStopLoss), takeProfit: Double(reviewTakeProfit)
        )
    }

    // MARK: - Trade Breakdown

    @State private var isAddingTrade = false
    @State private var draftSymbol = "NDX"
    @State private var draftDirection = "long"
    @State private var draftEntryPrice = ""
    @State private var draftExitPrice = ""
    @State private var draftEntryDate = Date()
    @State private var draftExitDate = Date()
    @State private var draftHasExit = false
    @State private var draftSize = ""
    @State private var draftPnl = ""
    @State private var draftSetupTag = setupTagOptions[0]
    @State private var draftTimeframe = timeframeOptions[2]
    @State private var draftNotes = ""

    private static let isoFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        formatter.timeZone = .current
        return formatter
    }()

    private var canSaveTrade: Bool {
        !draftSymbol.trimmingCharacters(in: .whitespaces).isEmpty
            && Double(draftEntryPrice) != nil && Double(draftSize) != nil
    }

    @ViewBuilder
    private var breakdownSection: some View {
        sectionLabel("LOG A TRADE")
        Button(isAddingTrade ? "Cancel" : "+ Add Trade") { isAddingTrade.toggle() }
            .buttonStyle(.bordered)

        if isAddingTrade {
            addTradeForm
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("TRADE HISTORY")
        if client.isLoadingTrades && client.trades.isEmpty {
            SkeletonList(count: 2)
        } else if client.trades.isEmpty {
            Text("No trades logged yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(client.trades) { trade in
                    TradeHistoryRow(trade: trade) { Task { await client.deleteTrade(id: trade.id) } }
                }
            }
        }

        Divider().overlay(theme.divider).padding(.vertical, 4)

        sectionLabel("BREAKDOWN")
        if client.breakdownMessages.isEmpty {
            if client.isLoadingBreakdown {
                inFlightRow("Computing breakdown…")
            } else {
                if let error = client.breakdownError { errorText(error) }
                Button("View Breakdown") { Task { await client.fetchBreakdown() } }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            if let stats = client.breakdownStats {
                TradeBreakdownStatsLine(stats: stats)
            }
            AdvisoryConversationThread(
                messages: client.breakdownMessages, isSending: client.isLoadingBreakdown, errorMessage: client.breakdownError,
                onSend: { text in Task { await client.sendBreakdownFollowUp(text) } },
                onReset: { client.resetBreakdown() }
            )
        }
    }

    @ViewBuilder
    private var addTradeForm: some View {
        VStack(alignment: .leading, spacing: 8) {
            plainField("Symbol", text: $draftSymbol)
            Picker("Direction", selection: $draftDirection) {
                Text("Long").tag("long")
                Text("Short").tag("short")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            plainField("Entry price", text: $draftEntryPrice)
            DatePicker("Entry time", selection: $draftEntryDate)
                .font(PCorpFont.body(12))
            plainField("Size", text: $draftSize)
            Toggle("Trade is closed", isOn: $draftHasExit)
                .font(PCorpFont.body(12))
            if draftHasExit {
                plainField("Exit price", text: $draftExitPrice)
                DatePicker("Exit time", selection: $draftExitDate)
                    .font(PCorpFont.body(12))
                plainField("P&L", text: $draftPnl)
            }
            Picker("Setup", selection: $draftSetupTag) {
                ForEach(setupTagOptions, id: \.self) { Text($0).tag($0) }
            }
            Picker("Timeframe", selection: $draftTimeframe) {
                ForEach(timeframeOptions, id: \.self) { Text($0).tag($0) }
            }
            plainField("Notes (optional)", text: $draftNotes)

            AsyncButton(action: saveTrade) {
                Text("Save Trade")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canSaveTrade)

            if let error = client.tradesError { errorText(error) }
        }
        .padding(12)
        .cardSurface(radius: 10)
    }

    private func saveTrade() async {
        guard let entryPrice = Double(draftEntryPrice), let size = Double(draftSize) else { return }
        let draft = TradeDraft(
            symbol: draftSymbol,
            direction: draftDirection,
            entryPrice: entryPrice,
            entryTimestamp: Self.isoFormatter.string(from: draftEntryDate),
            size: size,
            setupTag: draftSetupTag,
            timeframe: draftTimeframe,
            exitPrice: draftHasExit ? Double(draftExitPrice) : nil,
            exitTimestamp: draftHasExit ? Self.isoFormatter.string(from: draftExitDate) : nil,
            pnl: draftHasExit ? Double(draftPnl) : nil,
            notes: draftNotes.isEmpty ? nil : draftNotes
        )
        let succeeded = await client.addTrade(draft)
        if succeeded {
            toastCenter.show("Trade logged", style: .success)
            draftSymbol = "NDX"; draftEntryPrice = ""; draftExitPrice = ""; draftSize = ""; draftPnl = ""
            draftNotes = ""; draftHasExit = false; isAddingTrade = false
        }
    }

    // MARK: - Trade Proposals (approval-gated execution, 2026-09-22)
    //
    // Josh fills this in himself from a Setup/Signal/Chart reply he's
    // already read -- no auto-parsing of numbers out of the LLM's own
    // prose, same "human decides what becomes a proposal" boundary the
    // whole feature exists to enforce. Approving here does NOT itself
    // place a trade: it only flips the row to 'approved', which a
    // Mac-only backend loop then hands to a separate MQL5 EA
    // (PCorpExecutionBridge.mq5) that re-validates everything against
    // real live broker state before ever executing anything.

    @State private var proposalSymbol = "USA100"
    @State private var proposalDirection = "long"
    @State private var proposalEntryPrice = ""
    @State private var proposalStopLoss = ""
    @State private var proposalTakeProfit = ""
    @State private var proposalRiskPct = "1.0"
    @State private var proposalReasoning = ""

    // "Propose This Trade" (2026-09-22) -- pre-fills the form above from
    // a real, structured suggestion the agent included in a Setup/Chart/
    // Signal reply (never parsed from free-form prose -- see
    // SuggestedTrade's own docstring). Still a fully editable draft,
    // switching to the Propose tab rather than submitting anything.
    @ViewBuilder
    private func proposeThisTradeButton(_ suggestion: SuggestedTrade?) -> some View {
        if let suggestion {
            Button("Propose This Trade") { prefillProposal(from: suggestion) }
                .buttonStyle(.bordered)
        }
    }

    private func prefillProposal(from suggestion: SuggestedTrade) {
        proposalSymbol = suggestion.symbol
        proposalDirection = suggestion.direction
        proposalEntryPrice = String(suggestion.entryPrice)
        proposalStopLoss = String(suggestion.stopLoss)
        proposalTakeProfit = String(suggestion.takeProfit)
        proposalRiskPct = String(suggestion.riskPct)
        proposalReasoning = "Suggested by the Trade Intelligence Agent -- reviewed and confirmed by Josh."
        selectedSection = .propose
    }

    private var canCreateProposal: Bool {
        guard !proposalSymbol.trimmingCharacters(in: .whitespaces).isEmpty,
              let entry = Double(proposalEntryPrice), let stop = Double(proposalStopLoss),
              Double(proposalTakeProfit) != nil, let risk = Double(proposalRiskPct)
        else { return false }
        return entry != stop && risk > 0 && risk <= 2.0 && !proposalReasoning.trimmingCharacters(in: .whitespaces).isEmpty
    }

    @ViewBuilder
    private var proposeSection: some View {
        sectionLabel("PROPOSE A TRADE")
        Text("Turns a trade you've already decided on into something you can approve for real execution. Nothing happens until you tap Approve below, and even then a separate safety check on the Mac re-verifies live price, market hours, and combined account risk before anything reaches the account. Max risk per proposal: 2%.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)

        VStack(alignment: .leading, spacing: 8) {
            plainField("Symbol", text: $proposalSymbol)
            Picker("Direction", selection: $proposalDirection) {
                Text("Long").tag("long")
                Text("Short").tag("short")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            plainField("Entry price", text: $proposalEntryPrice)
            plainField("Stop-loss", text: $proposalStopLoss)
            plainField("Take-profit", text: $proposalTakeProfit)
            plainField("Risk % (max 2.0)", text: $proposalRiskPct)
            plainField("Reasoning (why this trade)", text: $proposalReasoning)

            AsyncButton(action: submitProposal) {
                Text("Create Proposal")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canCreateProposal)

            if let error = client.proposalsError { errorText(error) }
        }
        .padding(12)
        .cardSurface(radius: 10)

        Divider().overlay(theme.divider).padding(.vertical, 4)

        // In-app banner for the automated hourly scan (2026-09-22) --
        // confirmed with Josh directly: no push notification (needs a
        // paid Apple Developer account), so this is the actual signal
        // that something new is ready to look at.
        if client.pendingScanProposalCount > 0 {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .foregroundStyle(theme.statusHot)
                Text(client.pendingScanProposalCount == 1
                     ? "1 new automated trade idea ready to review"
                     : "\(client.pendingScanProposalCount) new automated trade ideas ready to review")
                    .font(PCorpFont.body(12, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
            }
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(theme.statusHot.opacity(0.12)))
        }

        sectionLabel("PENDING & RECENT")
        if client.isLoadingProposals && client.proposals.isEmpty {
            SkeletonList(count: 2)
        } else if client.proposals.isEmpty {
            Text("No proposals yet.")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
        } else {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(client.proposals) { proposal in
                    TradeProposalRow(
                        proposal: proposal,
                        onApprove: { Task { await approveProposal(proposal.id) } },
                        onReject: { Task { await client.rejectProposal(id: proposal.id) } },
                        onDelete: { Task { await client.deleteProposal(id: proposal.id) } }
                    )
                }
            }
        }
    }

    private func submitProposal() async {
        guard let entry = Double(proposalEntryPrice), let stop = Double(proposalStopLoss),
              let target = Double(proposalTakeProfit), let risk = Double(proposalRiskPct)
        else { return }
        let draft = TradeProposalDraft(
            symbol: proposalSymbol, direction: proposalDirection, entryPrice: entry, stopLoss: stop,
            takeProfit: target, riskPct: risk, reasoning: proposalReasoning
        )
        if let _ = await client.createProposal(draft) {
            toastCenter.show("Proposal created", style: .success)
            proposalEntryPrice = ""; proposalStopLoss = ""; proposalTakeProfit = ""; proposalReasoning = ""
        }
    }

    private func approveProposal(_ id: Int) async {
        let localNodeOnline = await client.approveProposal(id: id)
        toastCenter.show(
            localNodeOnline ? "Approved — the Mac will pick this up shortly" : "Approved, but the Mac looks offline right now — it'll execute once it's back",
            style: localNodeOnline ? .success : .warning
        )
    }

    // MARK: - Shared row helpers

    private func inFlightRow(_ label: String) -> some View {
        HStack(spacing: 8) {
            ProgressView()
            Text(label).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
        }
    }

    private func errorText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.statusRisk)
    }
}

private struct TradeHistoryRow: View {
    let trade: Trade
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(trade.symbol)
                        .font(PCorpFont.body(13, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text(trade.direction.uppercased())
                        .font(PCorpFont.label(8.5))
                        .trackedLabel(0.8)
                        .foregroundStyle(trade.direction == "long" ? theme.statusGood : theme.statusRisk)
                }
                Text("\(trade.setupTag) · \(trade.timeframe) · \(trade.entryTimestamp)")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
            }
            Spacer()
            if let pnl = trade.pnl {
                Text("\(pnl >= 0 ? "+" : "")\(pnl, specifier: "%.2f")")
                    .font(PCorpFont.body(12, weight: .semibold))
                    .foregroundStyle(pnl >= 0 ? theme.statusGood : theme.statusRisk)
            }
            Button(action: onDelete) {
                Image(systemName: "trash")
                    .font(.system(size: 11))
                    .foregroundStyle(theme.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}

private struct TradeProposalRow: View {
    let proposal: TradeProposal
    let onApprove: () -> Void
    let onReject: () -> Void
    let onDelete: () -> Void
    @Environment(\.appTheme) private var theme

    private var statusColor: Color {
        switch proposal.status {
        case "executed": return theme.statusGood
        case "failed", "rejected": return theme.statusRisk
        case "approved": return theme.statusHot
        default: return theme.textSecondary
        }
    }

    private var isScanGenerated: Bool {
        proposal.reasoning.hasPrefix(TradeIntelligenceClient.scanProposalReasoningPrefix)
    }

    private var displayedReasoning: String {
        isScanGenerated
            ? String(proposal.reasoning.dropFirst(TradeIntelligenceClient.scanProposalReasoningPrefix.count))
            : proposal.reasoning
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text(proposal.symbol)
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(proposal.direction.uppercased())
                    .font(PCorpFont.label(8.5))
                    .trackedLabel(0.8)
                    .foregroundStyle(proposal.direction == "long" ? theme.statusGood : theme.statusRisk)
                if isScanGenerated {
                    Text("AUTO")
                        .font(PCorpFont.label(8.5))
                        .trackedLabel(0.8)
                        .foregroundStyle(theme.statusHot)
                }
                Spacer()
                Text(proposal.status.uppercased())
                    .font(PCorpFont.label(8.5))
                    .trackedLabel(0.8)
                    .foregroundStyle(statusColor)
            }
            Text("Entry \(proposal.entryPrice, specifier: "%.2f") · SL \(proposal.stopLoss, specifier: "%.2f") · TP \(proposal.takeProfit, specifier: "%.2f") · Risk \(proposal.riskPct, specifier: "%.2f")%")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
            Text(displayedReasoning)
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
            if let result = proposal.executedResult {
                Text(result)
                    .font(PCorpFont.body(10))
                    .foregroundStyle(theme.textTertiary)
            }
            if proposal.status == "pending" {
                HStack(spacing: 8) {
                    Button("Approve", action: onApprove)
                        .buttonStyle(.borderedProminent)
                    Button("Reject", action: onReject)
                        .buttonStyle(.bordered)
                }
            } else {
                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .font(.system(size: 11))
                        .foregroundStyle(theme.textTertiary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(10)
        .cardSurface(radius: 8)
    }
}

private struct TradeBreakdownStatsLine: View {
    let stats: TradeBreakdownStats
    @Environment(\.appTheme) private var theme

    private var summaryLine: String {
        let winRate = Int(stats.overall.winRate * 100)
        let totalPnl = String(format: "%.2f", stats.overall.totalPnl)
        return "\(stats.closedTrades) closed trade(s) · \(winRate)% win rate · \(totalPnl) total P&L"
    }

    var body: some View {
        Text(summaryLine)
            .font(PCorpFont.body(12, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
    }
}
