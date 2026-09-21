import SwiftUI

/// Shared conversation-thread UI for all four Trade Intelligence
/// capabilities (2026-09-21, "I want to be able to respond") -- pure
/// SwiftUI, no platform-specific code, genuinely shared unlike the image
/// picker code each platform's own TradeIntelligenceView.swift still
/// needs (NSOpenPanel vs PhotosPicker). Deliberately not a reuse of
/// WarRoomView's own private ChatBubble -- that carries streaming/tool-
/// call/approval-card baggage this feature doesn't need; this is a
/// small, purpose-built thread view for a simple back-and-forth.
public struct AdvisoryConversationThread: View {
    let messages: [TradeIntelligenceMessage]
    let isSending: Bool
    let errorMessage: String?
    let onSend: (String) -> Void
    let onReset: () -> Void

    @Environment(\.appTheme) private var theme
    @State private var draftText = ""

    public init(
        messages: [TradeIntelligenceMessage], isSending: Bool, errorMessage: String? = nil,
        onSend: @escaping (String) -> Void, onReset: @escaping () -> Void
    ) {
        self.messages = messages
        self.isSending = isSending
        self.errorMessage = errorMessage
        self.onSend = onSend
        self.onReset = onReset
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(messages) { message in
                    AdvisoryMessageBubble(message: message)
                }
                if isSending {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Thinking…")
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                if let errorMessage {
                    Text(errorMessage)
                        .font(PCorpFont.body(12))
                        .foregroundStyle(theme.statusRisk)
                }
            }

            HStack(spacing: 8) {
                TextField("Ask a follow-up…", text: $draftText)
                    .textFieldStyle(.plain)
                    .font(PCorpFont.body(12.5))
                    .padding(10)
                    .cardSurface(radius: 8)
                    .disabled(isSending)
                    .onSubmit { send() }
                Button(action: send) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 22))
                }
                .buttonStyle(.plain)
                .disabled(isSending || draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            Button("Start Over", role: .destructive, action: onReset)
                .font(PCorpFont.body(11.5))
        }
    }

    private func send() {
        let text = draftText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        draftText = ""
        onSend(text)
    }
}

private struct AdvisoryMessageBubble: View {
    let message: TradeIntelligenceMessage
    @Environment(\.appTheme) private var theme

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        VStack(alignment: isUser ? .trailing : .leading, spacing: 4) {
            if !message.imageDataList.isEmpty {
                HStack(spacing: 6) {
                    ForEach(Array(message.imageDataList.enumerated()), id: \.offset) { _, data in
                        if let platformImg = PlatformImage(data: data) {
                            platformImage(platformImg)
                                .resizable()
                                .scaledToFill()
                                .frame(width: 60, height: 60)
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                        }
                    }
                }
            }
            if !message.text.isEmpty {
                Text(message.text)
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(isUser ? theme.accentText : theme.textPrimary)
                    .padding(10)
                    .background(isUser ? theme.accentFill : theme.surfaceElevated)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .textSelection(.enabled)
            }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}
