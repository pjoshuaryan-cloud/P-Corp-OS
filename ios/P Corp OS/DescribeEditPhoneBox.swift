import SwiftUI
import PCorpKit

/// Describe an edit on the phone (Cinematic Reel Autopilot phase 6b, 2026-11-18). The sentence goes to the cloud; the Mac picks it up, writes the costed card
/// back, and runs it when Go is pressed here. While the Mac is off nothing happens, and this says so.
struct DescribeEditPhoneBox: View {
    @StateObject private var relay = EditChatRelayClient()
    @Environment(\.appTheme) private var theme
    @State private var text = ""
    @State private var poll: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("DESCRIBE AN EDIT").font(PCorpFont.label(10)).tracking(0.6).foregroundStyle(theme.textSecondary)
                Spacer()
                HStack(spacing: 5) {
                    Circle().fill(relay.macOnline ? theme.statusGood : theme.statusRisk).frame(width: 7, height: 7)
                    Text(relay.macOnline ? "Mac online" : "Mac offline").font(PCorpFont.body(10.5)).foregroundStyle(theme.textSecondary)
                }
            }
            TextField("e.g. Rabit Haus recap of the JD shoot, 35 seconds", text: $text, axis: .vertical)
                .lineLimit(1...3)
                .textFieldStyle(.roundedBorder)
                .font(PCorpFont.body(14))
                .submitLabel(.send)
                .onSubmit { send() }
            HStack {
                Text(relay.macOnline ? "The Mac plans it. Nothing is spent until you press Go." : "Your Mac needs to be on, with the drive plugged in.")
                    .font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary)
                Spacer()
                Button(relay.isSending ? "Sending…" : "Plan it") { send() }
                    .buttonStyle(.borderedProminent)
                    .disabled(relay.isSending || text.trimmingCharacters(in: .whitespaces).isEmpty || relay.request?.status == "running")
            }
            if let error = relay.errorMessage {
                Text(error).font(PCorpFont.body(12)).foregroundStyle(theme.statusRisk)
            }
            if let req = relay.request, req.status != "replaced" {
                requestView(req)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(theme.surface))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(theme.surfaceBorder))
        .onAppear { startPolling() }
        .onDisappear { poll?.cancel() }
    }

    private func send() {
        let sentence = text.trimmingCharacters(in: .whitespaces)
        guard !sentence.isEmpty else { return }
        Task { await relay.send(sentence) }
    }

    private func startPolling() {
        poll?.cancel()
        poll = Task {
            while !Task.isCancelled {
                await relay.refresh()
                try? await Task.sleep(nanoseconds: (relay.request?.isPending == true ? 2 : 8) * 1_000_000_000)
            }
        }
    }

    private func money(_ usd: Double) -> String {
        usd == 0 ? "free" : (usd < 1 ? "about \(max(1, Int((usd * 100).rounded())))¢" : String(format: "about $%.2f", usd))
    }

    private func statusLine(_ req: EditChatRelayRequest) -> String? {
        switch req.status {
        case "new": return relay.macOnline ? "Sent. Waiting for the Mac…" : "Sent. It will be picked up when your Mac is on (within 15 minutes)."
        case "understanding": return "The Mac is reading it…"
        case "go", "starting": return "Starting on the Mac…"
        case "expired", "unclear", "failed", "stopped", "cancelled": return req.message ?? req.status.capitalized
        default: return nil
        }
    }

    @ViewBuilder
    private func requestView(_ req: EditChatRelayRequest) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("“\(req.text)”").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary).lineLimit(2)
            if let line = statusLine(req) {
                Text(line).font(PCorpFont.body(12.5))
                    .foregroundStyle(["failed", "stopped", "expired", "unclear"].contains(req.status) ? theme.statusRisk : theme.textPrimary)
            }
            if let card = req.card {
                Text("\(card.style.name) · \(card.job.shootName ?? "shoot #\(card.job.id)")")
                    .font(PCorpFont.body(14).weight(.semibold)).foregroundStyle(theme.textPrimary)
                Text([card.seconds.map { String(format: "%.0f s", $0) }, card.song.map { "song: \($0.name)" }, String(format: "cap $%.2f", card.usdCap)]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                ForEach(req.run?.steps ?? card.steps) { step in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(symbol(step.state)).font(PCorpFont.body(12)).frame(width: 14)
                        Text(step.what).font(PCorpFont.body(12.5)).foregroundStyle(theme.textPrimary)
                        Spacer(minLength: 6)
                        Text(step.spentUsd.map { String(format: "$%.3f", $0) } ?? money(step.usd)).font(PCorpFont.mono(11)).foregroundStyle(theme.textSecondary)
                    }
                }
                ForEach(card.warnings, id: \.self) { Text($0).font(PCorpFont.body(11.5)).foregroundStyle(theme.statusHot) }
                if card.overCap {
                    Text(String(format: "About $%.2f, over your $%.2f cap. Say a higher cap and plan it again.", card.usdTotal, card.usdCap))
                        .font(PCorpFont.body(12)).foregroundStyle(theme.statusRisk)
                }
                if req.status == "understood" {
                    HStack(spacing: 8) {
                        Button(String(format: "Go (%@)", money(card.usdTotal))) { Task { await relay.go() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(!card.ready || !relay.macOnline)
                        Button("Cancel") { Task { await relay.cancel() } }.buttonStyle(.bordered)
                    }
                    if !relay.macOnline { Text("Go needs your Mac on.").font(PCorpFont.body(11)).foregroundStyle(theme.textTertiary) }
                }
            }
            if req.status == "running" {
                HStack(spacing: 8) { ProgressView(); Text("Working on the Mac…").font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary) }
            }
            if req.status == "done" {
                Text(req.message ?? "Planned.").font(PCorpFont.body(12.5)).foregroundStyle(theme.statusGood)
                if let result = req.run?.result {
                    Text("\(result.shots) shots" + (result.seconds.map { String(format: ", %.0f s", $0) } ?? "")
                         + ((result.blurMoves ?? 0) > 0 ? ", \(result.blurMoves!) blur moves" : "") + ". Review Moments and Build My Edit are on the Mac.")
                        .font(PCorpFont.body(12)).foregroundStyle(theme.textSecondary)
                }
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(theme.background))
    }

    private func symbol(_ state: String?) -> String {
        switch state {
        case "done": return "✓"
        case "running": return "…"
        case "failed": return "✕"
        case "skipped": return "–"
        default: return "○"
        }
    }
}
