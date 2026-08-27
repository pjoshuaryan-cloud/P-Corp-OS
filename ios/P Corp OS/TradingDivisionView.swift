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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if client.isLoading && client.dashboard == nil {
                        Text("Loading…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let dashboard = client.dashboard {
                        section(title: "BACKTESTS") {
                            if dashboard.backtests.isEmpty {
                                emptyRow("No backtests recorded yet.")
                            } else {
                                ForEach(dashboard.backtests) { run in
                                    RunRow(run: run, kind: "Backtest")
                                }
                            }
                        }
                        section(title: "WALK-FORWARD RUNS") {
                            if dashboard.walkforwardRuns.isEmpty {
                                emptyRow("No walk-forward runs recorded yet.")
                            } else {
                                ForEach(dashboard.walkforwardRuns) { run in
                                    RunRow(run: run, kind: "Walk-forward")
                                }
                            }
                        }
                        section(title: "MONTE CARLO RUNS") {
                            if dashboard.montecarloRuns.isEmpty {
                                emptyRow("No Monte Carlo runs recorded yet.")
                            } else {
                                ForEach(dashboard.montecarloRuns) { run in
                                    MonteCarloRow(run: run)
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
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Trading Division")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Read-only: recorded backtest, walk-forward, and Monte Carlo results")
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Button {
                Task { await client.fetch() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.icon)
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
