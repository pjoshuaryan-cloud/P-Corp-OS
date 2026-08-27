import SwiftUI
import PCorpKit
import PhotosUI

/// The real War Room screen (2026-08-12, restyled to match desktop
/// pixel-for-pixel where the layout allows). Desktop's own docs call
/// War Room "the primary interface, not a stub" (WAR_ROOM.md), so this
/// is the one screen worth making properly real before any broader
/// mobile navigation -- deferred, not forgotten (see ROADMAP.md).
///
/// Now uses PCorpKit's real AppTheme via `\.appTheme`, exactly the way
/// every desktop view does -- reversed from the first cut, which used
/// iOS's own native semantic colors instead. Direct ask: match desktop
/// as closely as possible. The exact colors, card chrome (regularMaterial
/// + theme.background.opacity(0.35) + strokeBorder + shadow), chat
/// bubble styling, and input bar treatment are all copied from
/// desktop's own RightRail.swift/WarRoomView.swift, not approximated.
/// No manual dark-mode toggle yet, though -- there's no Settings screen
/// on iOS to put one in (out of scope, see ROADMAP.md's "10 other nav
/// destinations" note); AppTheme is picked from the system's actual
/// current appearance instead (ContentView.swift), the best available
/// signal absent a real toggle, not a guess.
///
/// Desktop's separate right-rail cards (Mission Status, Insights,
/// Situation Room) are a fixed, non-scrolling header here rather than
/// another column, with the chat getting its own dedicated scroll
/// region below -- real bug found and fixed live (2026-08-12): an
/// earlier version put everything in one combined ScrollView with no
/// auto-scroll, so a reply could render successfully but sit off-screen
/// below the cards, looking exactly like "no response." Today's Agenda
/// is deliberately excluded -- desktop's version reads the macOS
/// Calendar app via AppleScript, which has no iOS equivalent; a real
/// mobile agenda would need iOS's own EventKit against the iPhone's own
/// calendar, a genuinely separate feature not built yet. Voice
/// input/image attach (desktop's mic/paperclip buttons) are also not
/// built on iOS yet -- VoiceInput.swift is a desktop-only file, not in
/// PCorpKit -- so the input bar only has text + send, styled to match.
///
/// Update (2026-08-12): voice input and image attach are now built here
/// too, via their own iOS-appropriate mechanisms -- VoiceInput.swift
/// (ported from desktop's, swapping its macOS-only mic-selector step for
/// an AVAudioSession activation) and PhotosPicker (SwiftUI's own iOS photo
/// picker, replacing desktop's NSOpenPanel) -- same mic/paperclip buttons,
/// same push-to-talk and attached-image-chip behavior, same styling.
///
/// Update (2026-08-13): real bug found live -- "Frank doesn't respond."
/// Root cause confirmed server-side first (backend/data/pcorp.db showed a
/// real, correctly-generated reply sitting there that never reached the
/// phone): BackendClient.connect() (PCorpKit) only ever opens a socket
/// once and guards against reopening it (`task == nil`), which is exactly
/// right for desktop -- a Mac app is never suspended -- but wrong for
/// iOS, where the OS suspends network activity whenever the phone locks
/// or the app backgrounds, leaving `task` non-nil but silently dead.
/// Fixed with a scenePhase watcher, scoped to iOS only rather than
/// touching PCorpKit's shared connect() logic: returning to `.active`
/// force-reconnects (disconnect() clears the stale task, then connect()
/// opens a fresh one and reloads history so nothing sent while
/// disconnected is lost from view).
///
/// Update (2026-08-27): voice OUTPUT ported too, closing the loop on
/// "talking to Frank" -- VoiceOutput.swift (iOS parity port of desktop's
/// own) speaks the reply after a voice-triggered turn finishes streaming,
/// same pendingVoiceReply mechanism and same interrupt-on-new-recording
/// behavior as desktop. FrankOrb's `.speaking` state, previously withheld
/// on iOS for having no real TTS signal to react to, is wired in here too.
struct WarRoomView: View {
    // Injected from RootView (2026-08-20, SystemStatusHeader parity pass)
    // rather than owned here -- same move already made on desktop's
    // WarRoomView.swift, for the same reason: the header needs to read
    // this same real state across every section, not just War Room, and
    // the connection now survives navigating away from and back instead
    // of tearing down and reconnecting every time `.id(selectedItem.id)`
    // recreates this view.
    @ObservedObject var backend: BackendClient
    @ObservedObject var situationRoomClient: SituationRoomClient
    @StateObject private var focusClient = FocusClient()
    @StateObject private var insightsClient = InsightsClient()
    @StateObject private var voiceInput = VoiceInput()
    // iOS parity port (2026-08-27) of desktop's own VoiceOutput -- the
    // output half of "talking to Frank" that iOS never had. Same "only
    // speak replies to voice-triggered turns" rule as desktop, tracked the
    // same way: pendingVoiceReply is set true right when a push-to-talk
    // transcript is sent, consumed once that turn's reply finishes
    // streaming (see the onChange(of: backend.isStreaming) handler below).
    @StateObject private var voiceOutput = VoiceOutput()
    @State private var pendingVoiceReply = false
    @State private var inputText = ""
    @State private var photoPickerItem: PhotosPickerItem?
    @State private var attachedImageData: Data?
    @State private var attachedImageMediaType: String?
    @State private var attachedImagePreview: UIImage?
    @FocusState private var isInputFocused: Bool
    @Environment(\.appTheme) private var theme

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 0..<12: "Good morning"
        case 12..<17: "Good afternoon"
        default: "Good evening"
        }
    }

    /// Proactive greeting summary (2026-08-25 iOS parity pass, porting
    /// desktop's own Face-Lift item 08) -- real Situation Room alerts
    /// plus risk-category Insights, same two sources app/brief.py's
    /// "What Matters" section combines. Unlike desktop, this reuses the
    /// same `insightsClient` already feeding this view's own "FRANK'S
    /// INSIGHTS" card below rather than a second separate client --
    /// desktop needs its own copy because the greeting and the right-
    /// rail Insights card are two different views there; here they're
    /// the same view, so one fetch already covers both.
    fileprivate struct AttentionItem: Identifiable {
        let id = UUID()
        let label: String
        let detail: String
    }

    private var attentionItems: [AttentionItem] {
        let urgent = situationRoomClient.alerts.map { AttentionItem(label: $0.targetNavTitle.uppercased(), detail: $0.detail) }
        let risks = insightsClient.insights
            .filter { $0.category == "risk" }
            .map { AttentionItem(label: $0.targetNavTitle.uppercased(), detail: $0.detail) }
        return urgent + risks
    }

    var body: some View {
        VStack(spacing: 0) {
            if !situationRoomClient.alerts.isEmpty {
                situationRoomBanner
            }
            if voiceInput.isListening {
                // Takes over this space the same way desktop's own
                // listening state does -- real visual feedback (the orb,
                // reacting to real mic level) replacing what used to be
                // just the mic button turning red.
                Spacer(minLength: 0)
                FrankOrb(state: .listening(audioLevel: voiceInput.audioLevel))
                    .frame(width: 160, height: 160)
                    .frame(maxWidth: .infinity)
                Text(voiceInput.transcript.isEmpty ? "Listening…" : voiceInput.transcript)
                    .font(PCorpFont.body(14))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                    .padding(.top, 8)
                Spacer(minLength: 0)
            } else if voiceOutput.isSpeaking {
                // Mirrors the isListening case above -- the orb takes over
                // regardless of the chat thread underneath while Frank is
                // actually talking, reactive to real playback amplitude
                // rather than a synthetic shimmer. Falls through to the
                // normal thread view the instant playback ends, so the
                // full reply text is never lost, just shown once he's done
                // saying it.
                Spacer(minLength: 0)
                FrankOrb(state: .speaking(audioLevel: voiceOutput.audioLevel))
                    .frame(width: 160, height: 160)
                    .frame(maxWidth: .infinity)
                Text("Speaking…")
                    .font(PCorpFont.body(14))
                    .foregroundStyle(theme.textSecondary)
                    .padding(.top, 8)
                Spacer(minLength: 0)
            } else if let voiceOutputError = voiceOutput.errorMessage {
                // Same reasoning as the voiceInput.errorMessage branch
                // below -- ElevenLabs not being configured, or a real
                // network failure, would otherwise look identical to Frank
                // just staying silent.
                Spacer(minLength: 0)
                FrankOrb(state: .error)
                    .frame(width: 160, height: 160)
                    .frame(maxWidth: .infinity)
                Text(voiceOutputError)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                    .padding(.top, 8)
                Spacer(minLength: 0)
            } else if let voiceError = voiceInput.errorMessage {
                Spacer(minLength: 0)
                FrankOrb(state: .error)
                    .frame(width: 160, height: 160)
                    .frame(maxWidth: .infinity)
                Text(voiceError)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                    .padding(.top, 8)
                Spacer(minLength: 0)
            } else {
                // Real bug found live (2026-08-27): dashboardHeader used to
                // sit outside this scroll region as a fixed-height sibling.
                // With the keyboard up eating screen space, that fixed
                // header didn't shrink -- it squeezed ChatThreadView's own
                // ScrollView down (sometimes to near-zero height), leaving
                // no real room to drag through message history while
                // typing. Folding the header into the same ScrollView as
                // the messages makes the whole thing one continuous
                // scrollable region -- the header just scrolls out of the
                // way instead of permanently reserving space.
                ChatThreadView(messages: backend.messages, isStreaming: backend.isStreaming) {
                    dashboardHeader
                }
            }
            if let preview = attachedImagePreview {
                attachedImageChip(preview)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 8)
            }
            inputBar
                .padding(.horizontal, 16)
                .padding(.bottom, 12)
        }
        .background(theme.background)
        // connect()/situation-room polling now live in RootView, which
        // owns both clients' lifecycle (see WarRoomView's own property
        // comments above) -- this view no longer starts either itself.
        .task {
            await focusClient.fetch()
            await insightsClient.fetch()
        }
        .onChange(of: backend.isStreaming) { _, isStreaming in
            // isStreaming going true -> false is the real signal a turn
            // just completed (backend's own "\n[done]" sentinel) -- only
            // then is the assistant's reply actually complete text, safe
            // to hand to VoiceOutput. Speaking it mid-stream would mean
            // synthesizing broken sentence fragments as they arrive.
            guard !isStreaming, pendingVoiceReply else { return }
            pendingVoiceReply = false
            if let reply = backend.messages.last(where: { $0.role == "assistant" })?.content {
                voiceOutput.speak(reply)
            }
        }
        .onChange(of: photoPickerItem) { _, newItem in
            guard let newItem else { return }
            Task {
                guard let data = try? await newItem.loadTransferable(type: Data.self),
                      let image = UIImage(data: data)
                else { return }
                await MainActor.run {
                    attachedImageData = data
                    attachedImageMediaType = "image/jpeg"
                    attachedImagePreview = image
                }
            }
        }
    }

    private func attachedImageChip(_ preview: UIImage) -> some View {
        HStack(spacing: 8) {
            Image(uiImage: preview)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 32, height: 32)
                .clipShape(RoundedRectangle(cornerRadius: 6))
            Text("Image attached")
                .font(PCorpFont.body(12))
                .foregroundStyle(theme.textSecondary)
            Spacer()
            Button(action: clearAttachedImage) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(theme.textTertiary)
            }
            .buttonStyle(.plain)
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.surface.opacity(0.5)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.surfaceBorder))
    }

    private func clearAttachedImage() {
        photoPickerItem = nil
        attachedImageData = nil
        attachedImageMediaType = nil
        attachedImagePreview = nil
    }

    private var dashboardHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(greeting), Joshx.")
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                // Real, dynamic summary (2026-08-25 iOS parity pass) --
                // replaces the old static line with the same honest
                // "day is clear" vs "N things require attention" logic
                // desktop's own War Room greeting already has.
                if attentionItems.isEmpty {
                    Text("Nothing requires immediate attention. Your day is clear.")
                        .font(PCorpFont.body(11.5))
                        .foregroundStyle(theme.textSecondary)
                } else {
                    Text("\(attentionItems.count) THING\(attentionItems.count == 1 ? "" : "S") REQUIRE\(attentionItems.count == 1 ? "S" : "") YOUR ATTENTION.")
                        .font(PCorpFont.label(9))
                        .tracking(1.0)
                        .foregroundStyle(theme.textSecondary)
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(attentionItems.prefix(3).enumerated()), id: \.offset) { index, item in
                            AttentionRow(number: index + 1, item: item)
                        }
                    }
                    .padding(.top, 2)
                }
            }
            // Ported from desktop's own WarRoomCommandMap.swift
            // (2026-08-20, Face-Lift iOS parity pass) -- desktop places
            // this below Frank's orb, which iOS's dashboard-cards-always-
            // visible layout doesn't have in this spot; placing it right
            // after the greeting, before the cards, is the closest honest
            // analog -- quiet ambient info ahead of the actionable cards.
            WarRoomCommandMap()
            missionStatusCard
            if !insightsClient.insights.isEmpty {
                insightsCard
            }
        }
        .padding(16)
        .contentShape(Rectangle())
        .onTapGesture { isInputFocused = false }
    }

    private var missionStatusCard: some View {
        CardContainer {
            HStack {
                sectionLabel("MISSION STATUS")
                Spacer()
                HStack(spacing: 4) {
                    Circle().fill(Color.green).frame(width: 6, height: 6)
                    Text("Active").font(PCorpFont.body(11, weight: .semibold)).foregroundStyle(theme.textPrimary)
                }
            }
            Text("Create Leverage.\nFreedom Tomorrow.")
                .font(PCorpFont.display(19))
                .foregroundStyle(theme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Text("Focus: \(focusClient.objective ?? "Nothing set yet")")
                .font(PCorpFont.body(11))
                .foregroundStyle(theme.textSecondary)
        }
    }

    private var insightsCard: some View {
        CardContainer {
            sectionLabel("FRANK'S INSIGHTS")
            VStack(alignment: .leading, spacing: 10) {
                ForEach(insightsClient.insights) { insight in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: insight.systemImage)
                            .font(.system(size: 13))
                            .foregroundStyle(theme.textPrimary)
                            .frame(width: 22, height: 22)
                            .background(Circle().fill(theme.textPrimary.opacity(0.06)))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(insight.title)
                                .font(PCorpFont.body(12.5, weight: .semibold))
                                .foregroundStyle(theme.textPrimary)
                            Text(insight.detail)
                                .font(PCorpFont.body(11.5))
                                .foregroundStyle(theme.textSecondary)
                        }
                    }
                }
            }
        }
    }

    private var situationRoomBanner: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                Text("SITUATION ROOM")
                    .font(PCorpFont.label(10))
                    .tracking(1.4)
                    .foregroundStyle(.red)
            }
            ForEach(situationRoomClient.alerts) { alert in
                Text("\(alert.title) — \(alert.detail)")
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(theme.textPrimary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color.red.opacity(0.12))
        .overlay(Rectangle().frame(height: 1).foregroundStyle(.red.opacity(0.3)), alignment: .bottom)
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            Button {
                if !voiceInput.isListening {
                    // About to start a new push-to-talk recording --
                    // confirmed decision (matches desktop): that interrupts
                    // any reply Frank is still speaking, same as cutting
                    // off a person mid-sentence, rather than talking over
                    // him or waiting him out.
                    voiceOutput.stop()
                }
                voiceInput.toggle { transcript in
                    guard let transcript else { return }
                    pendingVoiceReply = true
                    backend.send(transcript)
                }
            } label: {
                Image(systemName: "mic.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.accentText)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(voiceInput.isListening ? Color.red : theme.accentFill))
            }
            .buttonStyle(.plain)

            PhotosPicker(selection: $photoPickerItem, matching: .images) {
                Image(systemName: "paperclip")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
                    .frame(width: 32, height: 32)
            }

            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(14))
                .foregroundStyle(theme.textPrimary)
                .focused($isInputFocused)
                .onSubmit(sendMessage)

            if backend.isStreaming {
                Button(action: backend.stopGenerating) {
                    Image(systemName: "square.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(theme.accentText)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(theme.accentFill))
                }
                .buttonStyle(.plain)
            } else {
                Button(action: sendMessage) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(theme.accentText)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(theme.accentFill))
                }
                .buttonStyle(.plain)
                .disabled(inputText.isEmpty)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(RoundedRectangle(cornerRadius: 24).fill(.ultraThinMaterial))
        .background(RoundedRectangle(cornerRadius: 24).fill(theme.surface.opacity(0.3)))
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(isInputFocused ? theme.textPrimary : theme.surfaceBorder, lineWidth: isInputFocused ? 2 : 1)
        )
        .shadow(color: theme.cardShadow, radius: isInputFocused ? 20 : 16, x: 0, y: isInputFocused ? 8 : 6)
        .animation(.easeOut(duration: 0.15), value: isInputFocused)
    }

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty || attachedImageData != nil else { return }
        backend.send(text, imageData: attachedImageData, mediaType: attachedImageMediaType)
        inputText = ""
        clearAttachedImage()
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(PCorpFont.label(9.5))
            .tracking(1.6)
            .foregroundStyle(theme.textSecondary)
    }
}

/// One numbered row in the proactive greeting's attention list, matching
/// desktop's own AttentionRow (WarRoomView.swift there) -- "01 / LABEL /
/// detail." `number` is a real 1-based position, not decoration.
private struct AttentionRow: View {
    let number: Int
    let item: WarRoomView.AttentionItem
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(String(format: "%02d", number))
                .font(PCorpFont.mono(10))
                .foregroundStyle(theme.textTertiary)
                .frame(width: 16, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.label)
                    .font(PCorpFont.label(9))
                    .tracking(0.8)
                    .foregroundStyle(theme.textPrimary)
                Text(item.detail)
                    .font(PCorpFont.body(11.5))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }
}

/// Exact match for desktop's own private CardContainer (RightRail.swift).
private struct CardContainer<Content: View>: View {
    let content: Content
    @Environment(\.appTheme) private var theme
    init(@ViewBuilder content: () -> Content) { self.content = content() }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18).fill(.regularMaterial))
        .background(RoundedRectangle(cornerRadius: 18).fill(theme.background.opacity(0.35)))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(theme.surfaceBorder))
        .shadow(color: theme.cardShadow, radius: 12, x: 0, y: 4)
    }
}

/// Its own dedicated scroll region with auto-scroll-to-newest, including
/// while a reply is still streaming in -- same proven pattern as
/// desktop's own ChatThreadView, and the same chat bubble styling
/// (ChatBubble there) copied here rather than approximated.
private struct ChatThreadView<Header: View>: View {
    let messages: [ChatMessage]
    let isStreaming: Bool
    @ViewBuilder var header: () -> Header
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 0) {
                    header()
                    Divider().overlay(theme.divider)
                    LazyVStack(alignment: .leading, spacing: 14) {
                        ForEach(messages) { message in
                            ChatBubble(message: message).id(message.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: messages.count) { _, _ in scrollToEnd(proxy) }
            .onChange(of: messages.last?.content) { _, _ in scrollToEnd(proxy) }
            .onAppear { scrollToEnd(proxy, animated: false) }
        }
    }

    private func scrollToEnd(_ proxy: ScrollViewProxy, animated: Bool = true) {
        guard let lastID = messages.last?.id else { return }
        if animated {
            withAnimation(.easeOut(duration: 0.15)) { proxy.scrollTo(lastID, anchor: .bottom) }
        } else {
            proxy.scrollTo(lastID, anchor: .bottom)
        }
    }
}

/// Exact match for desktop's own private ChatBubble (WarRoomView.swift
/// there) -- same colors, corner radius, padding, max width, spacer
/// widths. Plain Text, not desktop's markdown renderer -- that lives in
/// a desktop-only file (SimpleMarkdownView), a real follow-up, not a
/// shortfall of this pass specifically.
private struct ChatBubble: View {
    let message: ChatMessage
    @Environment(\.appTheme) private var theme

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                if let image = message.image {
                    Image(uiImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 240, maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                } else if message.hasStoredImage {
                    HStack(spacing: 6) {
                        Image(systemName: "photo")
                        Text("Image attached")
                    }
                    .font(PCorpFont.body(12))
                    .foregroundStyle((isUser ? theme.accentText : theme.textPrimary).opacity(0.8))
                }
                if !message.content.isEmpty || (message.image == nil && !message.hasStoredImage) {
                    Text(message.content.isEmpty ? "…" : message.content)
                        .font(PCorpFont.body(14))
                }
            }
            .foregroundStyle(isUser ? theme.accentText : theme.textPrimary)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 16).fill(isUser ? theme.accentFill : theme.surface.opacity(0.7)))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(isUser ? Color.clear : theme.surfaceBorder))
            .frame(maxWidth: 340, alignment: isUser ? .trailing : .leading)

            if !isUser { Spacer(minLength: 40) }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}

#Preview {
    WarRoomView(backend: BackendClient(), situationRoomClient: SituationRoomClient())
}
