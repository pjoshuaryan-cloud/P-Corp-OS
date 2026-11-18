import SwiftUI
import PCorpKit

/// "Describe an edit" at the top of the POST tab (Cinematic Reel Autopilot phase 6a, 2026-11-18). Josh types a sentence; the card shows what doing it takes
/// and costs (each step against the cap, $1 unless he says otherwise); Go runs it and ends with the plan ready for Review Moments and Build My Edit.
struct DescribeEditBox: View {
    @StateObject private var chat = EditChatClient()
    @Environment(\.appTheme) private var theme
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("DESCRIBE AN EDIT").font(PCorpFont.label(10)).tracking(0.6).foregroundStyle(theme.textSecondary)
            HStack(spacing: 8) {
                TextField("e.g. Rabit Haus recap of the JD shoot, 3 2 1, 35 seconds", text: $text)
                    .textFieldStyle(.roundedBorder)
                    .font(PCorpFont.body(12.5))
                    .onSubmit { understand() }
                Button(chat.isUnderstanding ? "Reading…" : "Plan it") { understand() }
                    .buttonStyle(.borderedProminent)
                    .disabled(chat.isUnderstanding || text.trimmingCharacters(in: .whitespaces).isEmpty || chat.run?.isRunning == true)
            }
            Text("Shoot, style, song, length and a cap (\"up to $2\"). Nothing is spent until you press Go.")
                .font(PCorpFont.body(10.5)).foregroundStyle(theme.textTertiary)
            if let error = chat.errorMessage {
                Text(error).font(PCorpFont.body(11.5)).foregroundStyle(theme.statusRisk)
            }
            if let message = chat.message {
                Text(message).font(PCorpFont.body(11.5)).foregroundStyle(theme.statusHot)
            }
            if let card = chat.card {
                cardView(card)
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(theme.surface))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(theme.surfaceBorder))
    }

    private func understand() {
        let sentence = text.trimmingCharacters(in: .whitespaces)
        guard !sentence.isEmpty else { return }
        Task { await chat.understand(sentence) }
    }

    private func money(_ usd: Double) -> String {
        usd == 0 ? "free" : (usd < 1 ? "about \(max(1, Int((usd * 100).rounded())))¢" : String(format: "about $%.2f", usd))
    }

    @ViewBuilder
    private func cardView(_ card: EditChatCard) -> some View {
        let run = chat.run
        VStack(alignment: .leading, spacing: 8) {
            Text("\(card.style.name) · \(card.job.shootName ?? "shoot #\(card.job.id)")")
                .font(PCorpFont.body(13.5).weight(.semibold)).foregroundStyle(theme.textPrimary)
            Text([card.seconds.map { String(format: "%.0f s", $0) }, card.song.map { "song: \($0.name)" }, String(format: "cap $%.2f", card.usdCap)]
                    .compactMap { $0 }.joined(separator: " · "))
                .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
            ForEach(run?.steps ?? card.steps) { step in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(symbol(step.state)).font(PCorpFont.body(12)).frame(width: 16)
                    Text(step.what).font(PCorpFont.body(12)).foregroundStyle(theme.textPrimary)
                    Spacer(minLength: 8)
                    Text(step.spentUsd.map { String(format: "$%.3f", $0) } ?? money(step.usd))
                        .font(PCorpFont.mono(11)).foregroundStyle(theme.textSecondary)
                }
            }
            ForEach(card.warnings, id: \.self) { w in
                Text(w).font(PCorpFont.body(11)).foregroundStyle(theme.statusHot)
            }
            if card.overCap {
                Text(String(format: "That's about $%.2f, over your $%.2f cap. Say a higher cap (\"up to $3\") and plan it again.", card.usdTotal, card.usdCap))
                    .font(PCorpFont.body(11.5)).foregroundStyle(theme.statusRisk)
            }
            if let run, let message = run.message {
                Text(message).font(PCorpFont.body(11.5))
                    .foregroundStyle(run.state == "done" ? theme.statusGood : (run.state == "running" ? theme.textSecondary : theme.statusRisk))
            }
            HStack(spacing: 8) {
                if run == nil {
                    Button(String(format: "Go (%@)", money(card.usdTotal))) { Task { await chat.go() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(!card.ready)
                    Button("Cancel") { chat.clear() }.buttonStyle(.bordered)
                } else if run?.isRunning == true {
                    ProgressView().controlSize(.small)
                    Text("Working… you can leave this screen.").font(PCorpFont.body(11)).foregroundStyle(theme.textSecondary)
                } else {
                    if let result = run?.result {
                        Text("\(result.shots) shots" + (result.seconds.map { String(format: ", %.0f s", $0) } ?? "")
                             + ((result.blurMoves ?? 0) > 0 ? ", \(result.blurMoves!) blur moves" : ""))
                            .font(PCorpFont.body(11.5)).foregroundStyle(theme.textSecondary)
                        Button("Review Moments") { NSWorkspace.shared.open(EditPlanClient(jobId: card.job.id).reviewPageURL()) }
                            .buttonStyle(.borderedProminent)
                    }
                    Button("Done") { chat.clear(); text = "" }.buttonStyle(.bordered)
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
