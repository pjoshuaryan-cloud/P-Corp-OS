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
    @State private var historyAccount: FinanceAccount?

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
                        if let concentration = client.concentration {
                            ConcentrationSection(concentration: concentration)
                        }
                        ForEach(dashboard.accounts) { account in
                            AccountCard(account: account) { historyAccount = account }
                        }
                    }
                }
                .padding(24)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
        .popover(item: $historyAccount) { account in
            FinanceAccountHistoryPopover(account: account, client: client)
        }
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
    let onTapHistory: () -> Void
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
                        Circle().fill(theme.statusGood).frame(width: 6, height: 6)
                        Text("AUTOMATIC")
                            .font(PCorpFont.label(9))
                            .trackedLabel(1.2)
                            .foregroundStyle(theme.textSecondary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Capsule().fill(theme.textPrimary.opacity(0.05)))
                }
                // History drill-down (2026-09-06, systems audit §4's
                // date-range filtering) -- every account, not just the
                // ones with enough history to look interesting yet; a
                // real, honest "not much logged" state is still a real
                // answer, same call made in FinanceAccountHistoryPopover.
                Button(action: onTapHistory) {
                    Image(systemName: "clock.arrow.circlepath")
                }
                .buttonStyle(.icon)
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
        .cardSurface(radius: 14)
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

/// Real-time HF Markets equity/floating P&L (2026-08-24), requested by
/// Joshua after realizing the balance figure alone doesn't reflect open
/// trades. Read live on every fetch, not stored -- see
/// backend/app/finance.py's get_hf_markets_live_status() docstring.
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

/// Concentration metrics (2026-09-06, systems audit §4) -- deliberately
/// TWO separate bar groups, never one blended "% of net worth" figure.
/// See backend/app/finance.py's compute_concentration_metrics() docstring
/// for why: the four ZAR accounts are real, same-currency balances (a
/// legitimate comparison); Luno's holdings are priced against a live
/// market feed, an estimate this app already discloses rather than
/// silently trusts -- combining the two would present a real number and
/// an estimate as equally certain.
private struct ConcentrationSection: View {
    let concentration: FinanceConcentration
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !concentration.zarAccounts.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("ZAR ACCOUNT CONCENTRATION")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.1)
                        .foregroundStyle(theme.textTertiary)
                    ForEach(concentration.zarAccounts.sorted(by: { $0.balance > $1.balance })) { row in
                        ConcentrationBar(
                            label: row.account,
                            valueLabel: "R\(String(format: "%.2f", row.balance))",
                            fraction: row.percentOfTotal ?? 0
                        )
                    }
                }
            }
            if !concentration.lunoHoldings.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("LUNO HOLDINGS CONCENTRATION")
                        .font(PCorpFont.label(9))
                        .trackedLabel(1.1)
                        .foregroundStyle(theme.textTertiary)
                    ForEach(concentration.lunoHoldings.prefix(6)) { holding in
                        ConcentrationBar(
                            label: holding.asset,
                            valueLabel: "R\(String(format: "%.2f", holding.estimatedZarValue))",
                            fraction: holding.percentOfTotal ?? 0
                        )
                    }
                    if !concentration.lunoUnpricedAssets.isEmpty {
                        Text("Excludes \(concentration.lunoUnpricedAssets.joined(separator: ", ")) — no live ZAR price available.")
                            .font(PCorpFont.body(10.5))
                            .foregroundStyle(theme.textTertiary)
                    }
                }
            }
        }
        .padding(18)
        .cardSurface(radius: 14)
    }
}

/// Plain Rectangle-width proportion bar -- no charting library added.
/// Zero SwiftUI charting exists anywhere in this codebase, and with as
/// few as 3-17 real data points behind any of these numbers, a real
/// chart isn't warranted yet (see the feature's own plan for why).
private struct ConcentrationBar: View {
    let label: String
    let valueLabel: String
    let fraction: Double
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(label)
                    .font(PCorpFont.body(12, weight: .medium))
                    .foregroundStyle(theme.textPrimary)
                Spacer()
                Text(valueLabel)
                    .font(PCorpFont.mono(11.5))
                    .foregroundStyle(theme.textSecondary)
                Text("\(Int((fraction * 100).rounded()))%")
                    .font(PCorpFont.mono(11.5, weight: .semibold))
                    .foregroundStyle(theme.textTertiary)
                    .frame(width: 34, alignment: .trailing)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle().fill(theme.divider).frame(height: 6)
                    Rectangle()
                        .fill(theme.accent)
                        .frame(width: geo.size.width * CGFloat(min(max(fraction, 0), 1)), height: 6)
                }
                .clipShape(RoundedRectangle(cornerRadius: 3))
            }
            .frame(height: 6)
        }
    }
}

/// Per-account balance history (2026-09-06, systems audit §4's date-range
/// filtering) -- reached by tapping an account's clock icon, same
/// popover-drill-down mechanism as JoshxProjectDetailPopover. A real,
/// filterable list of every logged snapshot, not a chart -- the entire
/// real history here spans about two weeks, with as few as 3-4 points
/// for the fully-manual accounts, so a chart would show noise, not a
/// trend. "All Time" is the default rather than a narrower preset for
/// exactly that reason.
private struct FinanceAccountHistoryPopover: View {
    let account: FinanceAccount
    @ObservedObject var client: FinanceClient
    @Environment(\.appTheme) private var theme
    @State private var period: Period = .allTime
    @State private var entries: [BalanceHistoryEntry] = []
    @State private var isLoading = true
    @State private var loadFailed = false

    private enum Period: String, CaseIterable, Identifiable {
        case week = "Week", month = "Month", quarter = "Quarter", allTime = "All Time"
        var id: String { rawValue }
        var days: Int? {
            switch self {
            case .week: 7
            case .month: 30
            case .quarter: 90
            case .allTime: nil
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(account.name.uppercased())
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            Picker("Period", selection: $period) {
                ForEach(Period.allCases) { p in
                    Text(p.rawValue).tag(p)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.bottom, 10)

            Divider().overlay(theme.divider)

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if isLoading {
                        Text("Loading…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                            .padding(16)
                    } else if loadFailed {
                        Text("Couldn't load history — is the backend running?")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                            .padding(16)
                    } else if entries.isEmpty {
                        Text("No snapshots logged in this period yet.")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                            .padding(16)
                    } else {
                        ForEach(entries) { entry in
                            HistoryRow(entry: entry)
                            Divider().overlay(theme.divider)
                        }
                    }
                }
            }
        }
        .frame(width: 360, height: 420)
        .background(theme.background)
        .task(id: period) { await load() }
    }

    private func load() async {
        isLoading = true
        loadFailed = false
        let from = period.days.map { days in
            ISO8601DateFormatter().string(from: Date().addingTimeInterval(-Double(days) * 86400)).prefix(10)
        }.map(String.init)
        do {
            entries = try await client.fetchHistory(accountId: account.id, from: from)
        } catch {
            loadFailed = true
        }
        isLoading = false
    }
}

private struct HistoryRow: View {
    let entry: BalanceHistoryEntry
    @Environment(\.appTheme) private var theme

    private var formattedBalance: String {
        entry.asset == "ZAR"
            ? "R\(String(format: "%.2f", entry.balance))"
            : String(format: "%.6f", entry.balance)
    }

    var body: some View {
        HStack(spacing: 10) {
            Text(entry.asset)
                .font(PCorpFont.mono(11, weight: .medium))
                .foregroundStyle(theme.textSecondary)
                .frame(width: 42, alignment: .leading)
            Text(formattedBalance)
                .font(PCorpFont.body(13, weight: .semibold))
                .foregroundStyle(theme.textPrimary)
            Spacer()
            Text(entry.recordedAt)
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textTertiary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }
}
