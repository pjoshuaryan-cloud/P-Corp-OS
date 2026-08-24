import SwiftUI
import PCorpKit

/// The "Finance" nav section (2026-08-21) -- Josh's personal investment
/// tracking across five real accounts (Liberty Stash, EasyEquities,
/// Luno, Ashburton Stable Income Fund, Nasdaq / Markets). Scoped down
/// directly with Josh before building anything real, given the honest
/// technical constraint investigated first: only Luno has a real public
/// API (a scoped read-only key, not his account password); the other
/// four have none at all, so they're tracked the same honest way Joshx/
/// Personal track anything with no external API -- Josh tells Frank a
/// balance, Frank logs it. "Always look for lucrative investment
/// opportunities" is explicitly deferred, its own separate real build --
/// see backend/app/finance_db.py's docstring for the full reasoning.
///
/// Same GET-and-render pattern as JoshxView/TradingDivisionView. No
/// blended cross-currency total anywhere here -- an account (especially
/// Luno) can hold multiple assets at once, and summing ZAR + XBT + ETH
/// into one number would misrepresent the real portfolio.
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
                .padding(24)
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
        .padding(24)
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

/// Real overall Luno value in rand (2026-08-24), computed live against
/// Luno's own price feed -- requested by Joshua after noticing the
/// Finance tab only showed per-asset lines, no total. Honestly notes
/// what isn't included rather than silently understating the real
/// portfolio -- Luno has no direct ZAR price for its tokenized-stock
/// products or a couple of other assets, so those stay excluded from the
/// number and named explicitly instead of hidden.
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
