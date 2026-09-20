import SwiftUI
import PCorpKit

/// The "Trading Division" nav section -- iOS parity port (2026-08-27) of
/// desktop's own TradingDivisionView.swift. Real, but strictly read-only
/// reporting over the trading robot's own recorded results; near-verbatim
/// copy, no AppKit dependency to work around, and every type it depends on
/// (TradingDivisionClient, TradingDivisionRun, TradingDivisionMonteCarloRun)
/// was already shared cross-platform in PCorpKit.
struct TradingDivisionView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = TradingDivisionClient()
    /// Tap targets (2026-09-18, "make the tab clickable... more detailed
    /// and interactive") -- see desktop's own TradingDivisionView.swift
    /// for the full reasoning, same additions mirrored here as `.sheet`
    /// instead of `.popover`.
    @State private var showLiveAccountDetail = false
    @State private var selectedRun: TradingDivisionRun?
    @State private var selectedMonteCarloRun: TradingDivisionMonteCarloRun?
    @State private var selectedMover: TradingDivisionStockMover?
    /// Trade Intelligence (2026-09-20) -- see desktop's own
    /// TradingDivisionView.swift and TradeIntelligenceView.swift for the
    /// full reasoning; same additions mirrored here as `.sheet`.
    @State private var showTradeIntelligence = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if client.isLoading && client.dashboard == nil {
                        SkeletonList()
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let dashboard = client.dashboard {
                        Button { showTradeIntelligence = true } label: {
                            TradeIntelligenceEntryCard()
                        }
                        .buttonStyle(.plain)
                        section(title: "LIVE ACCOUNT") {
                            if let liveAccount = dashboard.liveAccount {
                                Button { showLiveAccountDetail = true } label: {
                                    LiveAccountCard(status: liveAccount)
                                }
                                .buttonStyle(.plain)
                            } else {
                                emptyRow("No live account data right now — the Mac may be asleep/closed, or the EA isn't running.")
                            }
                        }
                        section(title: "STOCK MOVERS") {
                            if dashboard.stockMovers.isEmpty {
                                emptyRow("No stock moved more than the notable-move threshold in the last day.")
                            } else {
                                ForEach(dashboard.stockMovers) { mover in
                                    Button { selectedMover = mover } label: {
                                        StockMoverRow(mover: mover)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        section(title: "BACKTESTS") {
                            if dashboard.backtests.isEmpty {
                                emptyRow("No backtests recorded yet.")
                            } else {
                                ForEach(dashboard.backtests) { run in
                                    Button { selectedRun = run } label: {
                                        RunRow(run: run, kind: "Backtest")
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        section(title: "WALK-FORWARD RUNS") {
                            if dashboard.walkforwardRuns.isEmpty {
                                emptyRow("No walk-forward runs recorded yet.")
                            } else {
                                ForEach(dashboard.walkforwardRuns) { run in
                                    Button { selectedRun = run } label: {
                                        RunRow(run: run, kind: "Walk-forward")
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        section(title: "MONTE CARLO RUNS") {
                            if dashboard.montecarloRuns.isEmpty {
                                emptyRow("No Monte Carlo runs recorded yet.")
                            } else {
                                ForEach(dashboard.montecarloRuns) { run in
                                    Button { selectedMonteCarloRun = run } label: {
                                        MonteCarloRow(run: run)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
                .padding(24)
            }
            .refreshable { await client.fetch() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
        .sheet(isPresented: $showLiveAccountDetail) {
            if let liveAccount = client.dashboard?.liveAccount {
                LiveAccountDetailSheet(status: liveAccount, client: client)
            }
        }
        .sheet(item: $selectedRun) { run in
            RunDetailSheet(run: run)
        }
        .sheet(item: $selectedMonteCarloRun) { run in
            MonteCarloDetailSheet(run: run)
        }
        .sheet(isPresented: $showTradeIntelligence) {
            TradeIntelligenceView()
        }
        .sheet(item: $selectedMover) { mover in
            StockMoverDetailSheet(mover: mover, client: client)
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Trading Division")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Read-only: live account status, stock movers, and recorded backtest/walk-forward/Monte Carlo results")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            RefreshIconButton { await client.fetch() }
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

private struct RunRow: View {
    let run: TradingDivisionRun
    let kind: String
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text("\(kind) — \(run.symbol ?? "?") \(run.entryTimeframe ?? "")")
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text("\(run.totalTrades.map { "\($0) trades" } ?? "0 trades") — run \(run.runId)")
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            if let winRate = run.winRatePct, let profitFactor = run.profitFactor {
                VStack(alignment: .trailing, spacing: 1) {
                    Text("\(winRate, specifier: "%.1f")% win rate")
                        .font(PCorpFont.body(12, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text("PF \(profitFactor, specifier: "%.2f")")
                        .font(PCorpFont.body(10.5))
                        .foregroundStyle(theme.textSecondary)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}

private struct MonteCarloRow: View {
    let run: TradingDivisionMonteCarloRun
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text("\(run.numSimulations) simulations")
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text("Run \(run.runId)")
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Text("\(run.probabilityOfRuinPct, specifier: "%.2f")% probability of ruin")
                .font(PCorpFont.body(12, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}

/// iOS port of desktop's own LiveAccountCard -- see that file for the
/// full reasoning (2026-09-18, Josh's "how my open trades are doing"
/// ask, account-level only).
/// Entry point into Trade Intelligence -- see desktop's own
/// TradingDivisionView.swift for the full reasoning, identical styling.
private struct TradeIntelligenceEntryCard: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkles")
                .foregroundStyle(theme.statusHot)
            VStack(alignment: .leading, spacing: 1) {
                Text("Trade Intelligence")
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text("Chart analysis, signals, position review, trade breakdown — advisory")
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(theme.statusHot.opacity(0.7))
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(theme.statusHot.opacity(0.08))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.statusHot.opacity(0.25)))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

private struct LiveAccountCard: View {
    let status: HFMarketsLiveStatus
    @Environment(\.appTheme) private var theme

    private var isProfit: Bool { status.floatingPnl >= 0 }

    private var balanceLine: String {
        let base = "Balance \(status.currency) \(String(format: "%.2f", status.balance))"
        guard let updatedAt = status.updatedAt else { return base }
        return "\(base) · as of \(updatedAt)"
    }

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Equity \(status.currency) \(status.equity, specifier: "%.2f")")
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(balanceLine)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Text("\(isProfit ? "+" : "-")\(status.currency) \(abs(status.floatingPnl), specifier: "%.2f")")
                .font(PCorpFont.body(13, weight: .semibold))
                .foregroundStyle(isProfit ? theme.statusGood : theme.statusRisk)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }
}

/// iOS port of desktop's own StockMoverRow -- same objective,
/// non-advisory framing market_movers.py's own docstring establishes.
private struct StockMoverRow: View {
    let mover: TradingDivisionStockMover
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(mover.title)
                    .font(PCorpFont.body(13.5, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(mover.detail)
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

/// iOS port of desktop's own LiveAccountDetailPopover -- see that file
/// for the full reasoning (2026-09-18, manual "Get Live Update" action,
/// not auto-fetched on open).
private struct LiveAccountDetailSheet: View {
    let status: HFMarketsLiveStatus
    @ObservedObject var client: TradingDivisionClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var toastCenter: ToastCenter

    private var isProfit: Bool { status.floatingPnl >= 0 }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Live Account")
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
                VStack(alignment: .leading, spacing: 6) {
                    detailRow("Equity", "\(status.currency) \(String(format: "%.2f", status.equity))")
                    detailRow("Balance", "\(status.currency) \(String(format: "%.2f", status.balance))")
                    detailRow(
                        "Floating P&L",
                        "\(isProfit ? "+" : "-")\(status.currency) \(String(format: "%.2f", abs(status.floatingPnl)))"
                    )
                    if let updatedAt = status.updatedAt {
                        detailRow("As of", updatedAt)
                    }
                }

                Divider().overlay(theme.divider)

                VStack(alignment: .leading, spacing: 10) {
                    Text("NDX HOLDING — LIVE UPDATE")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.1)
                        .foregroundStyle(theme.textTertiary)

                    if client.isFetchingHoldingUpdate {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Checking live price and news…")
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.textSecondary)
                        }
                    } else if let update = client.holdingUpdate {
                        Text(update)
                            .font(PCorpFont.body(12.5))
                            .foregroundStyle(theme.textPrimary)
                            .textSelection(.enabled)
                        Button("Refresh") { Task {
                            await client.fetchHoldingUpdate()
                            if client.holdingUpdateError == nil { toastCenter.show("Live update ready", style: .success) }
                        } }
                            .buttonStyle(.bordered)
                    } else {
                        if let error = client.holdingUpdateError {
                            Text(error)
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.statusRisk)
                        }
                        Button("Get Live Update") { Task {
                            await client.fetchHoldingUpdate()
                            if client.holdingUpdateError == nil { toastCenter.show("Live update ready", style: .success) }
                        } }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 100, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// iOS port of desktop's own RunDetailPopover.
private struct RunDetailSheet: View {
    let run: TradingDivisionRun
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Run \(run.runId)")
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
            VStack(alignment: .leading, spacing: 6) {
                if let symbol = run.symbol { detailRow("Symbol", symbol) }
                if let timeframe = run.entryTimeframe { detailRow("Timeframe", timeframe) }
                if let start = run.startAt { detailRow("Start", start) }
                if let end = run.endAt { detailRow("End", end) }
                detailRow("Recorded", run.createdAt)
                if let totalTrades = run.totalTrades { detailRow("Total trades", "\(totalTrades)") }
                if let winRate = run.winRatePct { detailRow("Win rate", "\(String(format: "%.1f", winRate))%") }
                if let profitFactor = run.profitFactor { detailRow("Profit factor", String(format: "%.2f", profitFactor)) }
                if let drawdown = run.maxDrawdownPct { detailRow("Max drawdown", "\(String(format: "%.2f", drawdown))%") }
                if let totalPnl = run.totalPnl { detailRow("Total P&L", String(format: "%.2f", totalPnl)) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 100, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// iOS port of desktop's own MonteCarloDetailPopover.
private struct MonteCarloDetailSheet: View {
    let run: TradingDivisionMonteCarloRun
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Monte Carlo Run \(run.runId)")
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
            VStack(alignment: .leading, spacing: 6) {
                detailRow("Recorded", run.createdAt)
                detailRow("Simulations", "\(run.numSimulations)")
                detailRow("Probability of ruin", "\(String(format: "%.2f", run.probabilityOfRuinPct))%")
                if let p5 = run.finalBalanceP5 { detailRow("Final balance p5", String(format: "%.2f", p5)) }
                if let p50 = run.finalBalanceP50 { detailRow("Final balance p50", String(format: "%.2f", p50)) }
                if let p95 = run.finalBalanceP95 { detailRow("Final balance p95", String(format: "%.2f", p95)) }
                if let p50 = run.maxDrawdownP50 { detailRow("Max drawdown p50", "\(String(format: "%.2f", p50))%") }
                if let p95 = run.maxDrawdownP95 { detailRow("Max drawdown p95", "\(String(format: "%.2f", p95))%") }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 140, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// iOS port of desktop's own StockMoverDetailPopover -- see that file
/// for the full reasoning (2026-09-18, "make stock movers clickable and
/// interactive," per-symbol state, no account-context framing).
private struct StockMoverDetailSheet: View {
    let mover: TradingDivisionStockMover
    @ObservedObject var client: TradingDivisionClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var toastCenter: ToastCenter

    private var isFetching: Bool { client.fetchingStockUpdateSymbols.contains(mover.symbol) }
    private var update: String? { client.stockUpdates[mover.symbol] }
    private var error: String? { client.stockUpdateErrors[mover.symbol] }

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(mover.symbol)
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
                VStack(alignment: .leading, spacing: 2) {
                    Text(mover.title)
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    Text(mover.detail)
                        .font(PCorpFont.body(12.5))
                        .foregroundStyle(theme.textSecondary)
                }

                Divider().overlay(theme.divider)

                VStack(alignment: .leading, spacing: 10) {
                    Text("LIVE UPDATE")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.1)
                        .foregroundStyle(theme.textTertiary)

                    if isFetching {
                        HStack(spacing: 8) {
                            ProgressView()
                            Text("Checking live price and news…")
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.textSecondary)
                        }
                    } else if let update {
                        Text(update)
                            .font(PCorpFont.body(12.5))
                            .foregroundStyle(theme.textPrimary)
                            .textSelection(.enabled)
                        Button("Refresh") { Task {
                            await client.fetchStockUpdate(symbol: mover.symbol)
                            if client.stockUpdateErrors[mover.symbol] == nil { toastCenter.show("Live update ready", style: .success) }
                        } }
                            .buttonStyle(.bordered)
                    } else {
                        if let error {
                            Text(error)
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.statusRisk)
                        }
                        Button("Get Live Update") { Task {
                            await client.fetchStockUpdate(symbol: mover.symbol)
                            if client.stockUpdateErrors[mover.symbol] == nil { toastCenter.show("Live update ready", style: .success) }
                        } }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .background(theme.background)
    }
}
