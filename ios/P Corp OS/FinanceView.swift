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
                .padding(20)
            }
            .refreshable { await client.fetch() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .task { await client.fetch() }
        .sheet(item: $historyAccount) { account in
            FinanceAccountHistorySheet(account: account, client: client)
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
            RefreshIconButton { await client.fetch() }
        }
        .padding(20)
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

/// Concentration metrics (2026-09-06, systems audit §4) -- ported
/// directly from desktop's own ConcentrationSection, see that file's
/// docstring for why the two bar groups stay separate.
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
        .background(RoundedRectangle(cornerRadius: 14).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 14).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(theme.surfaceBorder))
    }
}

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
/// filtering) -- ported from desktop's own FinanceAccountHistoryPopover,
/// presented as a `.sheet` per this file's own established iOS-vs-desktop
/// modal convention (see JoshxProjectDetailSheet.swift). See desktop's
/// docstring for why this is a plain filterable list, not a chart.
private struct FinanceAccountHistorySheet: View {
    let account: FinanceAccount
    @ObservedObject var client: FinanceClient
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
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
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                Picker("Period", selection: $period) {
                    ForEach(Period.allCases) { p in
                        Text(p.rawValue).tag(p)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16)
                .padding(.top, 12)
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
            .background(theme.background)
            .navigationTitle(account.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
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
