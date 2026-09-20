import SwiftUI
import PCorpKit
import UniformTypeIdentifiers

/// Trade Intelligence (2026-09-20) -- a genuinely separate, advisory
/// specialist agent living inside the Trading Division tab, opened via
/// TradeIntelligenceEntryCard (TradingDivisionView.swift). Structurally
/// distinct from TradingDivisionClient/the read-only Trading Division
/// Agent: its own client (TradeIntelligenceClient), its own backend
/// module (trade_intelligence_agent.py), never reachable from Frank's
/// chat loop. AdvisoryDisclaimerBanner is mounted exactly once here,
/// unconditionally, above the 4-way section switcher -- see that
/// component's own docstring for why.
struct TradeIntelligenceView: View {
    @StateObject private var client = TradeIntelligenceClient()
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    private enum Section: String, CaseIterable, Identifiable {
        case chart = "Chart"
        case signal = "Signal"
        case position = "Position"
        case breakdown = "Breakdown"
        var id: String { rawValue }
    }
    @State private var selectedSection: Section = .chart

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            AdvisoryDisclaimerBanner()
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
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
                    switch selectedSection {
                    case .chart: chartAnalysisSection
                    case .signal: signalSection
                    case .position: positionReviewSection
                    case .breakdown: breakdownSection
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 480, height: 640)
        .task { await client.fetchTrades() }
    }

    private var header: some View {
        Text("Trade Intelligence")
            .font(PCorpFont.display(20))
            .foregroundStyle(theme.textPrimary)
            .padding(16)
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

    // MARK: - Chart Analysis

    @State private var chartImageData: Data?
    @State private var chartImageFilename = ""
    @State private var chartImageMediaType = ""
    @State private var chartSymbol = "NDX"
    @State private var chartNote = ""

    @ViewBuilder
    private var chartAnalysisSection: some View {
        sectionLabel("CHART ANALYSIS")
        Text("Plain-language read of what's visually present — not a calibrated numeric TA engine.")
            .font(PCorpFont.body(11))
            .foregroundStyle(theme.textTertiary)

        if let chartImageData, let nsImage = NSImage(data: chartImageData) {
            Image(nsImage: nsImage)
                .resizable()
                .scaledToFit()
                .frame(maxHeight: 160)
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        Button(chartImageData == nil ? "Choose Chart Image…" : "Choose Different Image…") { pickChartImage() }
            .buttonStyle(.bordered)

        plainField("Symbol (optional)", text: $chartSymbol)
        plainField("Note (optional)", text: $chartNote)

        if client.isAnalyzingChart {
            inFlightRow("Analyzing chart…")
        } else if let analysis = client.chartAnalysis {
            resultText(analysis)
            Button("Analyze Again") { Task { await analyzeChart() } }
                .buttonStyle(.bordered)
                .disabled(chartImageData == nil)
        } else {
            if let error = client.chartAnalysisError { errorText(error) }
            Button("Analyze Chart") { Task { await analyzeChart() } }
                .buttonStyle(.actionFilled)
                .disabled(chartImageData == nil)
        }
    }

    private func pickChartImage() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.urls.first, let data = try? Data(contentsOf: url) else { return }
        chartImageData = data
        chartImageFilename = url.lastPathComponent
        chartImageMediaType = url.pathExtension.lowercased() == "png" ? "image/png" : "image/jpeg"
    }

    private func analyzeChart() async {
        guard let chartImageData else { return }
        await client.analyzeChart(
            imageData: chartImageData, mediaType: chartImageMediaType, filename: chartImageFilename,
            symbol: chartSymbol.isEmpty ? nil : chartSymbol, note: chartNote.isEmpty ? nil : chartNote
        )
    }

    // MARK: - Trading Signals

    @State private var signalSymbol = "NDX"

    @ViewBuilder
    private var signalSection: some View {
        sectionLabel("TRADING SIGNALS")
        plainField("Symbol", text: $signalSymbol)
        if client.isGeneratingSignal {
            inFlightRow("Generating signal…")
        } else if let signal = client.signal {
            resultText(signal)
            Button("Regenerate") { Task { await client.generateSignal(symbol: signalSymbol) } }
                .buttonStyle(.bordered)
        } else {
            if let error = client.signalError { errorText(error) }
            Button("Generate Signal") { Task { await client.generateSignal(symbol: signalSymbol) } }
                .buttonStyle(.actionFilled)
                .disabled(signalSymbol.trimmingCharacters(in: .whitespaces).isEmpty)
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

        if client.isReviewingPosition {
            inFlightRow("Reviewing position…")
        } else if let review = client.positionReview {
            resultText(review)
            Button("Review Again") { Task { await reviewPosition() } }
                .buttonStyle(.bordered)
                .disabled(!canReviewPosition)
        } else {
            if let error = client.positionReviewError { errorText(error) }
            Button("Review Position") { Task { await reviewPosition() } }
                .buttonStyle(.actionFilled)
                .disabled(!canReviewPosition)
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
        if client.isLoadingBreakdown {
            inFlightRow("Computing breakdown…")
        } else if let breakdown = client.breakdown {
            TradeBreakdownSummary(breakdown: breakdown)
            Button("Refresh Breakdown") { Task { await client.fetchBreakdown() } }
                .buttonStyle(.bordered)
        } else {
            if let error = client.breakdownError { errorText(error) }
            Button("View Breakdown") { Task { await client.fetchBreakdown() } }
                .buttonStyle(.actionFilled)
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
            .buttonStyle(.actionFilled)
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

    // MARK: - Shared row helpers

    private func inFlightRow(_ label: String) -> some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text(label).font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
        }
    }

    private func resultText(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.body(12.5))
            .foregroundStyle(theme.textPrimary)
            .textSelection(.enabled)
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

private struct TradeBreakdownSummary: View {
    let breakdown: TradeBreakdown
    @Environment(\.appTheme) private var theme

    private var summaryLine: String {
        let winRate = Int(breakdown.stats.overall.winRate * 100)
        let totalPnl = String(format: "%.2f", breakdown.stats.overall.totalPnl)
        return "\(breakdown.stats.closedTrades) closed trade(s) · \(winRate)% win rate · \(totalPnl) total P&L"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(summaryLine)
                .font(PCorpFont.body(12, weight: .semibold))
                .foregroundStyle(theme.textPrimary)

            Text(breakdown.narrative)
                .font(PCorpFont.body(12.5))
                .foregroundStyle(theme.textPrimary)
                .textSelection(.enabled)
        }
    }
}
