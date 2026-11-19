import SwiftUI

// FestX signals in the Trading tab (2026-11-18), Mac and iPhone. Screenshots in; a signal or "no trade" out, read against the setups from Clint's FestX
// course; every signal shows its setup's backtest record; the size is worked out only after the live price is confirmed; a log of what was taken and how it
// went, with each setup's live record next to its backtest. Warnings never block. Nothing here places an order: every trade is placed by hand in MT5.

public struct FestxSetupCheck: Decodable, Identifiable, Sendable {
    public let setup: String
    public let name: String
    public let applies: Bool
    public let met: [String]
    public let missing: [String]
    public var id: String { setup }
}

public struct FestxSignal: Decodable, Sendable {
    public let setup: String
    public let setupName: String
    public let direction: String
    public let entry: Double
    public let stop: Double
    public let tp1: Double
    public let tp2: Double?
    public let confluenceWords: [String]
    public let strength: String
    public let why: String
    public let rewardToRisk: Double
    public let record: String
    public let belowFestxMinimum: Bool
}

public struct FestxReading: Decodable, Sendable {
    public let instrument: String
    public let timeframe: String
    public let priceScaleLegible: Bool
    public let currentPrice: Double?
    public let setups: [FestxSetupCheck]
    public let signal: FestxSignal?
    public let noTradeReason: String
    public let watchFor: String
    public let dropped: String?
}

public struct FestxSizing: Decodable, Sendable {
    public let lots: Double
    public let fitsRisk: Bool
    public let riskZar: Double
    public let riskPctActual: Double
    public let riskPctChosen: Double
    public let smallestTradeRiskZar: Double
    public let smallestTradeRiskPct: Double
    public let winTp1Zar: Double
    public let winTp2Zar: Double?
    public let rateSource: String?
    public let specConfirmed: Bool
    public let message: String?
    public let entryUsed: Double?
    public let rewardToRisk: Double?
}

public struct FestxSignalRow: Decodable, Identifiable, Sendable {
    public let id: Int
    public let createdAt: String
    public let symbol: String
    public let setup: String?
    public let direction: String?
    public let strength: String?
    public let status: String
    public let reading: FestxReading
    public let sizing: FestxSizing?
    public let fillPrice: Double?
    public let resultZar: Double?
    public let warnings: [String]?
}

public struct FestxLive: Decodable, Sendable { public let trades: Int; public let wins: Int; public let resultZar: Double; public let avgR: Double? }
public struct FestxBacktest: Decodable, Sendable { public let name: String; public let record: String; public let markets: String }
public struct FestxSettings: Decodable, Sendable {
    public let balanceZar: Double?
    public let standardPct: Double
    public let strongPct: Double
    public let dailyLossTrades: Int
    public let dailyLossPct: Double
}
/// Robot results (2026-11-18): the frozen setup D forward test run from AMM - APP. Read-only; never part of his own trades, balance or warnings.
public struct FestxRobotStats: Decodable, Sendable { public let trades: Int; public let avgR: Double?; public let totalR: Double?; public let profitFactor: Double? }
public struct FestxRobotTrade: Decodable, Sendable, Identifiable {
    public var id: String { day }
    public let day: String; public let direction: String?; public let entry: Double?; public let stop: Double?; public let exit: Double?
    public let reason: String?; public let r: Double?
}
public struct FestxRobot: Decodable, Sendable {
    public let name: String
    public let verdict: String?
    public let forwardPeriod: String?
    public let forward: FestxRobotStats?
    public let combined: FestxRobotStats?
    public let updatedAt: String
    public let recent: [FestxRobotTrade]
}
public struct FestxSummary: Decodable, Sendable {
    public let settings: FestxSettings
    public let recent: [FestxSignalRow]
    public let live: [String: FestxLive]
    public let backtest: [String: FestxBacktest]
    public let warnings: [String]
    public let robot: [String: FestxRobot]?
}

@MainActor
public final class FestxClient: ObservableObject {
    @Published public private(set) var summary: FestxSummary?
    @Published public private(set) var current: FestxSignalRow?
    @Published public private(set) var isWorking = false
    @Published public private(set) var errorMessage: String?

    public init() {}

    private struct ErrorDetail: Decodable { let detail: String }
    private struct ReadReply: Decodable { let signal: FestxSignalRow; let summary: FestxSummary }
    private struct RowReply: Decodable { let signal: FestxSignalRow; let summary: FestxSummary? }
    private static let decoder: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()

    private func call(_ method: String, _ path: String, body: [String: Any]? = nil, timeout: TimeInterval = 60) async -> Data? {
        var r = URLRequest(url: BackendHost.url(path: path))
        r.httpMethod = method
        r.timeoutInterval = timeout
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: r)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                errorMessage = (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode))."
                return nil
            }
            errorMessage = nil
            return data
        } catch {
            errorMessage = "Couldn't reach the backend — check the connection and try again."
            return nil
        }
    }

    public func load() async {
        if let data = await call("GET", "/trading/festx/summary"), let s = try? Self.decoder.decode(FestxSummary.self, from: data) { summary = s }
    }

    public func read(_ screenshots: [ChartScreenshot], note: String) async {
        guard !screenshots.isEmpty, !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        let body: [String: Any] = ["images": screenshots.enumerated().map { i, shot in
            ["media_type": shot.mediaType, "filename": "chart-\(i + 1).jpg", "data": shot.data.base64EncodedString()] }, "note": note]
        if let data = await call("POST", "/trading/festx/read", body: body, timeout: 150),
           let reply = try? Self.decoder.decode(ReadReply.self, from: data) {
            current = reply.signal
            summary = reply.summary
        } else if errorMessage == nil {
            errorMessage = "Unexpected reply from the backend."
        }
    }

    public func size(_ id: Int, price: Double) async {
        if let data = await call("POST", "/trading/festx/signals/\(id)/size", body: ["current_price": price]),
           let reply = try? Self.decoder.decode(RowReply.self, from: data) { current = reply.signal }
    }

    public func log(_ id: Int, status: String, fill: Double? = nil, exit: Double? = nil, resultZar: Double? = nil) async {
        var body: [String: Any] = ["status": status]
        if let fill { body["fill_price"] = fill }
        if let exit { body["exit_price"] = exit }
        if let resultZar { body["result_zar"] = resultZar }
        if let data = await call("POST", "/trading/festx/signals/\(id)/log", body: body),
           let reply = try? Self.decoder.decode(RowReply.self, from: data) {
            if current?.id == id { current = reply.signal }
            if let s = reply.summary { summary = s }
        }
    }

    public func saveSettings(_ changes: [String: Any]) async {
        if let data = await call("PUT", "/trading/festx/settings", body: changes), let s = try? Self.decoder.decode(FestxSummary.self, from: data) { summary = s }
    }

    public func clear() { current = nil; errorMessage = nil }
}

// MARK: - Views

func festxRand(_ v: Double) -> String { String(format: v < 0 ? "−R%.2f" : "R%.2f", abs(v)) }
func festxPrice(_ v: Double) -> String { v >= 1000 ? String(format: "%.1f", v) : (v >= 100 ? String(format: "%.2f", v) : String(format: "%.5f", v)) }
private func parsePrice(_ s: String) -> Double? { Double(s.replacingOccurrences(of: ",", with: ".").trimmingCharacters(in: .whitespaces)) }

/// The signal (or no-trade) card for the current reading, with the price confirm, the size and the log buttons.
struct FestxSignalCard: View {
    @Environment(\.appTheme) private var theme
    @ObservedObject var festx: FestxClient
    let row: FestxSignalRow
    @State private var price = ""
    @State private var fill = ""
    @State private var exit = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let sig = row.reading.signal {
                HStack {
                    Text("\(sig.direction == "buy" ? "BUY" : "SELL") \(row.symbol)")
                        .font(PCorpFont.display(20)).foregroundStyle(sig.direction == "buy" ? theme.statusGood : theme.statusRisk)
                    Spacer()
                    Text(sig.strength == "strong" ? "Strong · \(sig.confluenceWords.count) confluences" : "Standard")
                        .font(PCorpFont.label(10)).foregroundStyle(theme.textSecondary)
                }
                Text("Setup \(sig.setup): \(sig.setupName)").font(PCorpFont.body(13, weight: .semibold)).foregroundStyle(theme.textPrimary)
                Text(sig.record).font(PCorpFont.body(12)).foregroundStyle(theme.statusHot)
                levels(sig)
                if sig.belowFestxMinimum {
                    Text(String(format: "Reward to risk is only 1:%.1f, below FestX's 1:3 minimum.", sig.rewardToRisk)).font(PCorpFont.body(12)).foregroundStyle(theme.statusHot)
                }
                Text(sig.why).font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                ForEach(sig.confluenceWords, id: \.self) { Text("• \($0)").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary) }
                sizeSection
                logSection
            } else {
                Text("No trade").font(PCorpFont.display(20)).foregroundStyle(theme.textPrimary)
                Text(row.reading.noTradeReason).font(PCorpFont.body(13)).foregroundStyle(theme.textSecondary)
            }
            if !row.reading.watchFor.isEmpty {
                Text("Watch for: \(row.reading.watchFor)").font(PCorpFont.body(12)).foregroundStyle(theme.textTertiary)
            }
            DisclosureGroup("What each setup needed") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(row.reading.setups) { s in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(s.setup) · \(s.name)\(s.applies ? "" : " (doesn't apply)")").font(PCorpFont.body(12, weight: .semibold))
                            ForEach(s.met, id: \.self) { Text("✓ \($0)").font(PCorpFont.body(11.5)).foregroundStyle(theme.statusGood) }
                            ForEach(s.missing, id: \.self) { Text("✕ \($0)").font(PCorpFont.body(11.5)).foregroundStyle(theme.textTertiary) }
                        }
                    }
                }
                .padding(.top, 4)
            }
            .font(PCorpFont.body(12))
            ForEach(row.warnings ?? [], id: \.self) { w in
                Text("⚠︎ \(w)").font(PCorpFont.body(12.5, weight: .semibold)).foregroundStyle(theme.statusRisk)
            }
        }
        .padding(14)
        .cardSurface(radius: 10)
    }

    private func levels(_ sig: FestxSignal) -> some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 4) {
            GridRow { label("Entry"); value(festxPrice(sig.entry)) }
            GridRow { label("Stop"); value(festxPrice(sig.stop)) }
            GridRow { label("Target 1"); value(festxPrice(sig.tp1) + String(format: "  (1:%.1f)", sig.rewardToRisk)) }
            if let tp2 = sig.tp2 { GridRow { label("Target 2"); value(festxPrice(tp2)) } }
        }
    }
    private func label(_ t: String) -> some View { Text(t).font(PCorpFont.body(12)).foregroundStyle(theme.textTertiary) }
    private func value(_ t: String) -> some View { Text(t).font(PCorpFont.mono(13)).foregroundStyle(theme.textPrimary) }

    @ViewBuilder private var sizeSection: some View {
        if let z = row.sizing {
            VStack(alignment: .leading, spacing: 4) {
                Text(String(format: "%.2f lots", z.lots)).font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text("Risks \(festxRand(z.riskZar)) (\(String(format: "%.1f", z.riskPctActual))% of your account) · could make \(festxRand(z.winTp1Zar)) at target 1"
                     + (z.winTp2Zar.map { " or \(festxRand($0)) at target 2" } ?? ""))
                    .font(PCorpFont.body(12.5)).foregroundStyle(theme.textSecondary)
                if let m = z.message { Text(m).font(PCorpFont.body(12.5, weight: .semibold)).foregroundStyle(theme.statusRisk) }
                if !z.specConfirmed {
                    Text("Contract size not yet checked against Black Crown's MT5 (right-click the symbol > Specification). Check the lot size in MT5 before you trade.")
                        .font(PCorpFont.body(11)).foregroundStyle(theme.statusHot)
                }
                if let src = z.rateSource { Text("Rand at \(src).").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary) }
            }
        }
        if row.status == "signal" {
            HStack(spacing: 8) {
                TextField("Current price in MT5", text: $price).textFieldStyle(.roundedBorder).font(PCorpFont.mono(12))
                Button(row.sizing == nil ? "Work out size" : "Re-size") {
                    if let p = parsePrice(price) { Task { await festx.size(row.id, price: p) } }
                }
                .buttonStyle(.bordered).disabled(parsePrice(price) == nil)
            }
        }
    }

    @ViewBuilder private var logSection: some View {
        switch row.status {
        case "signal":
            HStack(spacing: 8) {
                TextField("Your fill price", text: $fill).textFieldStyle(.roundedBorder).font(PCorpFont.mono(12))
                Button("I took it") { Task { await festx.log(row.id, status: "taken", fill: parsePrice(fill)) } }
                    .buttonStyle(.borderedProminent).disabled(row.sizing == nil)
                Button("Skip") { Task { await festx.log(row.id, status: "skipped") } }.buttonStyle(.bordered)
            }
            if row.sizing == nil { Text("Confirm the price first, so the log knows the size.").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary) }
        case "taken":
            VStack(alignment: .leading, spacing: 6) {
                Text("Open trade" + (row.fillPrice.map { " · filled at \(festxPrice($0))" } ?? "")).font(PCorpFont.body(12.5, weight: .semibold))
                HStack(spacing: 8) {
                    TextField("Exit price", text: $exit).textFieldStyle(.roundedBorder).font(PCorpFont.mono(12))
                    Button("Won") { Task { await festx.log(row.id, status: "won", exit: parsePrice(exit)) } }.buttonStyle(.bordered)
                    Button("Lost") { Task { await festx.log(row.id, status: "lost", exit: parsePrice(exit)) } }.buttonStyle(.bordered)
                    Button("Break-even") { Task { await festx.log(row.id, status: "breakeven", exit: parsePrice(exit)) } }.buttonStyle(.bordered)
                }
                .disabled(parsePrice(exit) == nil)
            }
        default:
            Text(row.status.capitalized + (row.resultZar.map { " · \(festxRand($0))" } ?? "")).font(PCorpFont.body(13, weight: .semibold))
                .foregroundStyle((row.resultZar ?? 0) >= 0 ? theme.statusGood : theme.statusRisk)
        }
    }
}

/// Balance, risk settings, today's warnings, each setup's live record next to its backtest, and recent signals.
struct FestxAccountPanel: View {
    @Environment(\.appTheme) private var theme
    @ObservedObject var festx: FestxClient
    @State private var balance = ""
    @State private var standard = ""
    @State private var strong = ""
    @State private var showSettings = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let s = festx.summary {
                HStack {
                    Text("FESTX ACCOUNT").font(PCorpFont.label()).trackedLabel().foregroundStyle(theme.textTertiary)
                    Spacer()
                    Button(showSettings ? "Done" : "Settings") { showSettings.toggle() }.buttonStyle(.bordered)
                }
                Text(s.settings.balanceZar.map { "Balance \(festxRand($0))" } ?? "Set your balance to get sizes")
                    .font(PCorpFont.display(18)).foregroundStyle(theme.textPrimary)
                Text(String(format: "Risk %.0f%% standard · %.0f%% strong · warns after %d losses or %.0f%% down in a day",
                            s.settings.standardPct, s.settings.strongPct, s.settings.dailyLossTrades, s.settings.dailyLossPct))
                    .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                if showSettings { settingsForm(s) }
                ForEach(s.warnings, id: \.self) { Text("⚠︎ \($0)").font(PCorpFont.body(12.5, weight: .semibold)).foregroundStyle(theme.statusRisk) }
                Text("SETUPS: YOUR TRADES AND THE BACKTEST").font(PCorpFont.label()).trackedLabel().foregroundStyle(theme.textTertiary).padding(.top, 6)
                ForEach(["A", "C", "G", "D"], id: \.self) { code in
                    if let bt = s.backtest[code] {
                        let live = s.live[code]
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(code) · \(bt.name)").font(PCorpFont.body(12.5, weight: .semibold)).foregroundStyle(theme.textPrimary)
                            Text(live.map { $0.trades == 0 ? "Your trades: none yet" : "Your trades: \($0.trades), \($0.wins) won, \(festxRand($0.resultZar))" + ($0.avgR.map { String(format: ", %+.2fR a trade", $0) } ?? "") } ?? "Your trades: none yet")
                                .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                            Text(bt.record).font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                        }
                    }
                }
                if let robots = s.robot, let d = robots["D"] { robotSection(d) }
            } else if let e = festx.errorMessage {
                Text(e).font(PCorpFont.body(12)).foregroundStyle(theme.statusRisk)
            }
        }
        .padding(14)
        .cardSurface(radius: 10)
        .task { await festx.load() }
    }

    /// Read-only: what the frozen setup D rules did on Black Crown prices since 19 Nov 2026. No orders are placed by anything here.
    @ViewBuilder private func robotSection(_ d: FestxRobot) -> some View {
        Text("ROBOT TEST: SETUP D ON BLACK CROWN (NO REAL TRADES)").font(PCorpFont.label()).trackedLabel().foregroundStyle(theme.textTertiary).padding(.top, 6)
        VStack(alignment: .leading, spacing: 2) {
            Text(d.verdict ?? "No report yet").font(PCorpFont.body(12.5, weight: .semibold)).foregroundStyle(theme.textPrimary)
            if let f = d.forward {
                Text(f.trades == 0 ? "New trades since 19 Nov: none yet" :
                        "New trades since 19 Nov: \(f.trades)" + (f.avgR.map { String(format: ", %+.2fR a trade", $0) } ?? "") + (f.totalR.map { String(format: ", %+.1fR total", $0) } ?? ""))
                    .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
            }
            if let c = d.combined, let a = c.avgR {
                Text(String(format: "With the 47 backtest trades: %d trades, %+.2fR a trade. Decision at 40 new trades (needs +0.15R).", c.trades, a))
                    .font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
            }
            ForEach(d.recent.prefix(5)) { t in
                Text("\(t.day) · \((t.direction ?? "").uppercased()) · \(t.reason ?? "")" + (t.r.map { String(format: " · %+.2fR", $0) } ?? ""))
                    .font(PCorpFont.mono(11)).foregroundStyle(theme.textSecondary)
            }
            Text("Updated \(String(d.updatedAt.prefix(10))) · checked monthly").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
        }
    }

    private func settingsForm(_ s: FestxSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack { Text("Balance (R)").frame(width: 110, alignment: .leading); TextField(s.settings.balanceZar.map { String(format: "%.2f", $0) } ?? "e.g. 243.03", text: $balance).textFieldStyle(.roundedBorder) }
            HStack { Text("Standard risk %").frame(width: 110, alignment: .leading); TextField(String(format: "%.0f", s.settings.standardPct), text: $standard).textFieldStyle(.roundedBorder) }
            HStack { Text("Strong risk %").frame(width: 110, alignment: .leading); TextField(String(format: "%.0f", s.settings.strongPct), text: $strong).textFieldStyle(.roundedBorder) }
            Text("Most per trade: 10%. A logged result updates the balance by itself.").font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            Button("Save") {
                var changes: [String: Any] = [:]
                if let v = parsePrice(balance) { changes["balance_zar"] = v }
                if let v = parsePrice(standard) { changes["standard_pct"] = v }
                if let v = parsePrice(strong) { changes["strong_pct"] = v }
                Task { await festx.saveSettings(changes); balance = ""; standard = ""; strong = "" }
            }
            .buttonStyle(.borderedProminent)
        }
        .font(PCorpFont.body(12))
    }
}
