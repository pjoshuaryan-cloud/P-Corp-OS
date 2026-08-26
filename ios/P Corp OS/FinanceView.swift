import SwiftUI
import PCorpKit

/// Close port of desktop's own FinanceView.swift (2026-08-25 iOS parity
/// pass) -- entirely built on PCorpKit's already-cross-platform
/// FinanceClient/FinanceAccount/FinanceHolding/LunoZarValue/
/// HFMarketsLiveStatus, no AppKit dependencies, so this is a direct,
/// unmodified port, same as AlphaModeDashboardView's own port. "Finance"
/// already had a NavItem/Sidebar slot on iOS (it just fell through to
/// SectionPlaceholderView with no case in RootView's switch) -- this is
/// what actually fills it in.
struct FinanceView: View {
    @Environment(\.appTheme) private var theme
    @StateObject private var client = FinanceClient()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(theme.divider)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if client.isLoading && client.dashboard == nil {
                        Text("Loading…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let error = client.errorMessage {
                        Text(error)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    } else if let dashboard = client.dashboard {
                        ForEach(dashboard.accounts) { account in
                            AccountCard(account: account)
                        }
                    }
                }
                .padding(20)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Finance")
                    .font(PCorpFont.display(24))
                    .foregroundStyle(theme.textPrimary)
                Text("Personal investments — tracked and displayed, never advised on")
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
        .padding(20)
    }
}

private struct AccountCard: View {
    let account: FinanceAccount
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(account.name)
                        .font(PCorpFont.body(15, weight: .semibold))
                        .foregroundStyle(theme.textPrimary)
                    if let type = account.accountType {
                        Text(type.replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(PCorpFont.body(11.5))
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                Spacer()
                if account.isAutomatic {
                    HStack(spacing: 6) {
                        Circle().fill(Color.green).frame(width: 6, height: 6)
                        Text("AUTOMATIC")
                            .font(PCorpFont.label(9))
                            .trackedLabel(1.2)
                            .foregroundStyle(theme.textSecondary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
                }
            }

            if account.holdings.isEmpty {
                Text(
                    account.isAutomatic
                        ? "No balance yet — arrives with the first automatic snapshot."
                        : "No balance logged yet — tell Frank a figure to get started."
                )
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
            } else {
                if let lunoValue = account.lunoValue {
                    LunoValueSummary(value: lunoValue)
                }
                if let live = account.hfMarketsLive {
                    HFMarketsLiveSummary(status: live)
                }
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(account.holdings) { holding in
                        HoldingRow(holding: holding)
                    }
                }
            }
        }
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 14).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(theme.surfaceBorder))
    }
}

private struct LunoValueSummary: View {
    let value: LunoZarValue
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("ESTIMATED VALUE")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            Text("R\(String(format: "%.2f", value.estimatedZarValue))")
                .font(PCorpFont.mono(22, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            if !value.unpricedAssets.isEmpty {
                Text("Excludes \(value.unpricedAssets.joined(separator: ", ")) — no live ZAR price available for these on Luno.")
                    .font(PCorpFont.body(10.5))
                    .foregroundStyle(theme.textTertiary)
            }
        }
        .padding(.bottom, 4)
    }
}

private struct HFMarketsLiveSummary: View {
    let status: HFMarketsLiveStatus
    @Environment(\.appTheme) private var theme

    private var pnlColor: Color {
        if status.floatingPnl > 0 { return .green }
        if status.floatingPnl < 0 { return .red }
        return theme.textTertiary
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("LIVE EQUITY")
                .font(PCorpFont.label(9))
                .trackedLabel(1.1)
                .foregroundStyle(theme.textTertiary)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("R\(String(format: "%.2f", status.equity))")
                    .font(PCorpFont.mono(22, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text("\(status.floatingPnl >= 0 ? "+" : "")R\(String(format: "%.2f", status.floatingPnl))")
                    .font(PCorpFont.mono(13, weight: .semibold))
                    .foregroundStyle(pnlColor)
            }
            Text("Balance R\(String(format: "%.2f", status.balance)) while trades are open" + (status.updatedAt.map { " — updated \($0)" } ?? ""))
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
        }
        .padding(.bottom, 4)
    }
}

private struct HoldingRow: View {
    let holding: FinanceHolding
    @Environment(\.appTheme) private var theme

    private var trendColor: Color {
        switch holding.trend {
        case "up": .green
        case "down": .red
        default: theme.textTertiary
        }
    }

    private var trendSymbol: String {
        switch holding.trend {
        case "up": "arrow.up.right"
        case "down": "arrow.down.right"
        default: "minus"
        }
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: trendSymbol)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(trendColor)
                .frame(width: 14)
            Text(holding.asset)
                .font(PCorpFont.mono(11.5, weight: .medium))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 42, alignment: .leading)
            Text(formattedBalance)
                .font(PCorpFont.body(13.5, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Spacer()
            Text("as of \(holding.recordedAt)")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
        }
    }

    private var formattedBalance: String {
        holding.asset == "ZAR"
            ? "R\(String(format: "%.2f", holding.balance))"
            : String(format: "%.6f", holding.balance)
    }
}
