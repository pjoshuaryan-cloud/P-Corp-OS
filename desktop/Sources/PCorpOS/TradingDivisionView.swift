import SwiftUI
import PCorpKit

/// The "Trading Division" nav section (2026-08-17) -- real, but strictly
/// read-only reporting over the trading robot's own recorded results
/// (research.sqlite, a completely separate repo), never a rebuild of the
/// trading robot itself. Built despite TRADING_DIVISION.md's own "not
/// until the trading robot is stable" timing note, on Joshua's explicit
/// instruction to override that gate now (see backend/app/
/// trading_division.py's docstring for the full reasoning) -- the robot
/// itself is genuinely still early (its own README calls itself "Phase 1:
/// Scaffolding"), so this correctly shows a mostly-empty state today and
/// will pick up more automatically as real backtest/walk-forward/Monte
/// Carlo runs get recorded, no further changes needed here.
///
/// Same GET-and-render pattern as AlphaModeDashboardView/AutomationsView.
struct TradingDivisionView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = TradingDivisionClient()
    /// Tap targets (2026-09-18, "make the tab clickable... more detailed
    /// and interactive") -- every row here already had more real data
    /// fetched than it displayed (max_drawdown_pct/total_pnl/exact dates
    /// for runs, the full Monte Carlo percentile spread), so "more
    /// detailed" is real data already in hand, not new fields to add.
    @State private var showLiveAccountDetail = false
    @State private var selectedRun: TradingDivisionRun?
    @State private var selectedMonteCarloRun: TradingDivisionMonteCarloRun?
    @State private var selectedMover: TradingDivisionStockMover?

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
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
        .popover(isPresented: $showLiveAccountDetail) {
            if let liveAccount = client.dashboard?.liveAccount {
                LiveAccountDetailPopover(status: liveAccount, client: client)
            }
        }
        .popover(item: $selectedRun) { run in
            RunDetailPopover(run: run)
        }
        .popover(item: $selectedMonteCarloRun) { run in
            MonteCarloDetailPopover(run: run)
        }
        .popover(item: $selectedMover) { mover in
            StockMoverDetailPopover(mover: mover, client: client)
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
            RefreshIconButton(action: client.fetch)
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
        .cardSurface(radius: 12)
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
        .cardSurface(radius: 12)
    }
}

/// Live account status (2026-09-18, Josh's direct "how my open trades
/// are doing" ask) -- account-level only (balance/equity/floating P&L),
/// same live HF Markets bridge Finance's own dashboard already shows,
/// just surfaced here too. theme.statusGood/statusRisk reused for the
/// profit/loss color, same semantic tokens Finance already uses for the
/// same real signal, not a new color invented for this card.
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
        .cardSurface(radius: 12)
    }
}

/// One factual stock-movement fact (2026-09-18, "stocks doing well" ask)
/// -- same objective, non-advisory framing market_movers.py's own
/// docstring establishes, never a recommendation.
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
        .cardSurface(radius: 12)
    }
}

/// Detail view behind LiveAccountCard's tap (2026-09-18, "report on how
/// my holdings are doing... relevant live news" ask) -- shows the same
/// real account numbers plus, on request, a genuinely live web_search/
/// web_fetch report on NDX (Josh's confirmed real holding/traded
/// instrument, see trading_division_agent.py's HOLDING_SYMBOL) --
/// deliberately a manual "Get Live Update" action, not auto-fetched on
/// open, since this is a real live call (10-20+ seconds, a real API
/// cost) every time, not a cached number -- matches this app's own
/// established manual-refresh convention (RefreshIconButton etc.)
/// rather than surprising Josh with a slow load every time he taps in.
private struct LiveAccountDetailPopover: View {
    let status: HFMarketsLiveStatus
    @ObservedObject var client: TradingDivisionClient
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    private var isProfit: Bool { status.floatingPnl >= 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("LIVE ACCOUNT")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

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
                                ProgressView().controlSize(.small)
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
                                .buttonStyle(.actionFilled)
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 420, height: 480)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 90, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// Detail view behind RunRow's tap (2026-09-18, "more detailed") --
/// surfaces real fields already fetched from research.sqlite but never
/// shown in the compact row (start/end/created dates, max drawdown,
/// total P&L).
private struct RunDetailPopover: View {
    let run: TradingDivisionRun
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("RUN \(run.runId)")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

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
                .padding(16)
            }
        }
        .frame(width: 360, height: 380)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 96, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// Detail view behind MonteCarloRow's tap (2026-09-18, "more detailed")
/// -- the compact row only ever showed simulations count + probability
/// of ruin; the real percentile spread (p5/p50/p95 for both final
/// balance and max drawdown) was already fetched and never shown at all.
private struct MonteCarloDetailPopover: View {
    let run: TradingDivisionMonteCarloRun
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("MONTE CARLO RUN \(run.runId)")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

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
                .padding(16)
            }
        }
        .frame(width: 360, height: 380)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label)
                .font(PCorpFont.body(11.5, weight: .semibold))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 120, alignment: .leading)
            Text(value)
                .font(PCorpFont.body(11.5))
                .foregroundStyle(theme.textPrimary)
        }
    }
}

/// Detail view behind StockMoverRow's tap (2026-09-18, "make stock
/// movers clickable and interactive") -- same manual "Get Live Update"
/// shape as LiveAccountDetailPopover, keyed by this mover's own symbol
/// (client.stockUpdates/fetchingStockUpdateSymbols/stockUpdateErrors are
/// all per-symbol dictionaries, so multiple movers' fetches never
/// clobber each other). Deliberately no account-context framing here --
/// see get_stock_update()'s own docstring for why that would be wrong
/// for a mover Josh may not actually hold.
private struct StockMoverDetailPopover: View {
    let mover: TradingDivisionStockMover
    @ObservedObject var client: TradingDivisionClient
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var toastCenter: ToastCenter

    private var isFetching: Bool { client.fetchingStockUpdateSymbols.contains(mover.symbol) }
    private var update: String? { client.stockUpdates[mover.symbol] }
    private var error: String? { client.stockUpdateErrors[mover.symbol] }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(mover.symbol)
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Divider().overlay(theme.divider)

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
                                ProgressView().controlSize(.small)
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
                                .buttonStyle(.actionFilled)
                        }
                    }
                }
                .padding(16)
            }
        }
        .frame(width: 420, height: 480)
    }
}
