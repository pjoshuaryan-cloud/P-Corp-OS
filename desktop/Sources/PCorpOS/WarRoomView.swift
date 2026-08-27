import AppKit
import PCorpKit
import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""
    @State private var showConversationList = false
    @State private var showTheBrief = false
    // Image upload (2026-08-05): held as raw Data + a real MIME type, not
    // just an NSImage -- the MIME type is what the backend needs to build
    // Claude's own image content block, and re-deriving it from an NSImage
    // later would be more work than just keeping what NSOpenPanel already
    // told us via the file's UTType.
    @State private var attachedImageData: Data? = nil
    @State private var attachedImageMediaType: String? = nil
    @State private var attachedImagePreview: NSImage? = nil
    @Environment(\.appTheme) private var theme
    @FocusState private var isInputFocused: Bool
    // Injected from ContentView (2026-08-20) rather than owned here --
    // SystemStatusHeader needs to read the same real connection/streaming/
    // alert state across all 11 sections, not just while War Room is
    // selected, so ContentView now owns the lifecycle (connect/poll) and
    // this view just observes. Real side benefit: the connection now
    // survives navigating away from and back to War Room, instead of
    // tearing down and reconnecting every time `.id(selectedItem.id)`
    // recreates this view.
    @ObservedObject var backend: BackendClient
    @ObservedObject var situationRoom: SituationRoomClient
    // Own instance, separate from RightRail's InsightsCard one -- same
    // "each view fetches its own copy" pattern already used elsewhere
    // (AgentsView/FrankView each own their own client too), not shared
    // state. Backs the proactive greeting below (2026-08-20, Face-Lift
    // item 08), not a duplicate of the right rail's card.
    @StateObject private var greetingInsightsClient = InsightsClient()
    @StateObject private var voiceInput = VoiceInput()
    @StateObject private var voiceOutput = VoiceOutput()
    /// Set true right when a push-to-talk transcript is sent, consumed
    /// once that turn's reply finishes streaming -- the mechanism for
    /// "only speak replies to voice input" (confirmed decision,
    /// 2026-07-28): a typed message never sets this, so its reply stays
    /// silent same as before VoiceOutput existed.
    @State private var pendingVoiceReply = false

    /// Real time-of-day check, not a fixed string. Takes the date explicitly
    /// (from the TimelineView in `body`, below) rather than reading `.now`
    /// directly — a plain computed property reading `.now` only re-evaluates
    /// when something else causes SwiftUI to re-render this view (sending a
    /// message, reconnecting, etc.), so a genuinely idle window would keep
    /// showing "Good morning" all afternoon. The TimelineView ticks on its
    /// own, independent of any other app state, so the greeting actually
    /// updates as real time passes.
    private func timeOfDayGreeting(at date: Date) -> String {
        switch Calendar.current.component(.hour, from: date) {
        case 0..<12: "Good morning"
        case 12..<17: "Good afternoon"
        default: "Good evening"
        }
    }

    /// The greeting's "N things require your attention" list (2026-08-20,
    /// Face-Lift item 08) -- real Situation Room alerts plus risk-category
    /// Insights, the same two sources `app/brief.py`'s "What Matters"
    /// section already combines, just fetched independently here rather
    /// than through GET /brief (which has a real side effect -- it marks
    /// the Brief as viewed -- that this greeting must never trigger).
    /// Both sources carry a real `targetNavTitle`, used as the label here.
    fileprivate struct AttentionItem: Identifiable {
        let id = UUID()
        let label: String
        let detail: String
    }

    private var attentionItems: [AttentionItem] {
        let urgent = situationRoom.alerts.map { AttentionItem(label: $0.targetNavTitle.uppercased(), detail: $0.detail) }
        let risks = greetingInsightsClient.insights
            .filter { $0.category == "risk" }
            .map { AttentionItem(label: $0.targetNavTitle.uppercased(), detail: $0.detail) }
        return urgent + risks
    }

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            content(currentDate: context.date)
        }
    }

    private func content(currentDate: Date) -> some View {
        VStack(spacing: 0) {
            topBar(currentDate: currentDate)

            if !situationRoom.alerts.isEmpty {
                SituationRoomBanner(alerts: situationRoom.alerts)
            }

            if voiceInput.isListening {
                // While actively recording, the blob takes over the center
                // area regardless of whether a text thread exists — this is
                // the case FrankOrb's audio-reactive path (below) was built
                // for, replacing the synthetic shimmer with real mic level.
                Spacer(minLength: 0)

                FrankOrb(state: .listening(audioLevel: voiceInput.audioLevel))
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)

                Text(voiceInput.transcript.isEmpty ? "Listening…" : voiceInput.transcript)
                    .font(PCorpFont.body(15))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 480)
                    .padding(.top, 8)
            } else if voiceOutput.isSpeaking {
                // Mirrors the isListening case above -- the orb takes over
                // regardless of the text thread underneath while Frank is
                // actually talking, reactive to real playback amplitude
                // (VoiceOutput.swift) rather than the synthetic shimmer.
                // Falls through to the normal thread view (below) the
                // instant playback ends, so the full reply text is never
                // lost, just shown once he's done saying it.
                Spacer(minLength: 0)

                FrankOrb(state: .speaking(audioLevel: voiceOutput.audioLevel))
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)

                Text("Speaking…")
                    .font(PCorpFont.body(15))
                    .foregroundStyle(theme.textSecondary)
                    .padding(.top, 8)

                Spacer(minLength: 20)
            } else if let voiceOutputError = voiceOutput.errorMessage {
                // Same reasoning as the voiceInput.errorMessage branch
                // below -- ElevenLabs not being configured, or a real
                // network failure, would otherwise look identical to
                // Frank just staying silent. Uses the orb's own real
                // .error state (2026-08-20) rather than an unrelated
                // waveform-slash icon -- the "restrained warning state"
                // the Face-Lift brief asks for, not a separate UI.
                Spacer(minLength: 0)
                FrankOrb(state: .error)
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)
                Text(voiceOutputError)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 400)
                    .padding(.top, 8)
                Spacer(minLength: 20)
            } else if let voiceError = voiceInput.errorMessage {
                // Surfaced explicitly — this was previously tracked
                // (VoiceInput.errorMessage) but never actually shown
                // anywhere, so a real failure (permission denied, no
                // recognizer available) looked identical to silence.
                Spacer(minLength: 0)
                FrankOrb(state: .error)
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)
                Text(voiceError)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 400)
                    .padding(.top, 8)
                Spacer(minLength: 20)
            } else if backend.messages.isEmpty {
                Spacer(minLength: 0)

                VStack(alignment: .leading, spacing: 12) {
                    Text("\(timeOfDayGreeting(at: currentDate)), Joshx.")
                        .font(PCorpFont.display(38, weight: .bold))
                        .foregroundStyle(theme.textPrimary)

                    // Real, dynamic summary (2026-08-20, Face-Lift item 08)
                    // -- replaces the old static "I'm Frank. How can I
                    // help you today?" line. Only ever reflects
                    // attentionItems (real Situation Room + risk Insights
                    // data, above) -- an honest "day is clear" is a real,
                    // expected state, not an error or something to hide.
                    if attentionItems.isEmpty {
                        Text("Nothing requires immediate attention. Your day is clear.")
                            .font(PCorpFont.body(17))
                            .foregroundStyle(theme.textSecondary)
                    } else {
                        Text("\(attentionItems.count) THING\(attentionItems.count == 1 ? "" : "S") REQUIRE\(attentionItems.count == 1 ? "S" : "") YOUR ATTENTION.")
                            .font(PCorpFont.label(11))
                            .trackedLabel(1.2)
                            .foregroundStyle(theme.textSecondary)

                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(attentionItems.prefix(3).enumerated()), id: \.offset) { index, item in
                                AttentionRow(number: index + 1, item: item)
                            }
                        }
                        .padding(.top, 4)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 48)

                Spacer(minLength: 20)

                // Only shown in the empty/idle state — once a text
                // conversation is active the thread takes this space
                // instead. The other case where the blob shows is actively
                // listening (above), reactive to real audio.
                FrankOrb(state: .idle)
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)

                Spacer(minLength: 20)

                // Stats row sits below Frank himself, not competing with
                // him — "Frank > Mission > Intelligence > Navigation" per
                // the brief's own stated hierarchy (item 21).
                WarRoomCommandMap()
                    .padding(.horizontal, 48)

                Spacer(minLength: 20)
            } else {
                ChatThreadView(messages: backend.messages, isStreaming: backend.isStreaming)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

            if let preview = attachedImagePreview {
                attachedImageChip(preview)
                    .padding(.horizontal, 48)
                    .padding(.bottom, 8)
            }

            if let approval = backend.pendingApproval {
                ApprovalRequestCard(
                    request: approval,
                    onApprove: { backend.respondToApproval(approved: true) },
                    onReject: { backend.respondToApproval(approved: false) }
                )
                .padding(.horizontal, 48)
                .padding(.bottom, 8)
            }

            inputBar
                .disabled(backend.pendingApproval != nil)
                .padding(.horizontal, 48)
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        // connect()/situation-room polling now live in ContentView, which
        // owns both clients' lifecycle (see WarRoomView's own property
        // comments above) -- this view no longer starts either itself.
        .task {
            // Same 30s-poll reasoning as RightRail's InsightsCard --
            // genuinely proactive shouldn't require a manual refresh.
            while !Task.isCancelled {
                await greetingInsightsClient.fetch()
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
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
    }

    private func attachedImageChip(_ preview: NSImage) -> some View {
        HStack(spacing: 8) {
            Image(nsImage: preview)
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

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty || attachedImageData != nil else { return }
        backend.send(text, imageData: attachedImageData, mediaType: attachedImageMediaType)
        inputText = ""
        clearAttachedImage()
    }

    private func clearAttachedImage() {
        attachedImageData = nil
        attachedImageMediaType = nil
        attachedImagePreview = nil
    }

    /// NSOpenPanel restricted to real image types -- .png/.jpeg cover what
    /// Claude's vision input actually accepts; not offering formats it'd
    /// just reject. Reads the raw bytes directly rather than re-encoding
    /// through NSImage, so what gets sent is exactly the original file.
    private func pickImage() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.png, .jpeg]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        guard panel.runModal() == .OK, let url = panel.url, let data = try? Data(contentsOf: url) else { return }
        attachedImageData = data
        attachedImageMediaType = url.pathExtension.lowercased() == "png" ? "image/png" : "image/jpeg"
        attachedImagePreview = NSImage(data: data)
    }

    private func topBar(currentDate: Date) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("\(timeOfDayGreeting(at: currentDate)), Joshx.")
                    .font(PCorpFont.body(13, weight: .semibold))
                    .foregroundStyle(theme.textPrimary)
                Text(currentDate.formatted(date: .complete, time: .omitted))
                    .font(PCorpFont.body(11))
                    .foregroundStyle(theme.textSecondary)
            }

            Spacer()

            PLogoMark()

            Spacer()

            HStack(spacing: 4) {
                Button {
                    voiceOutput.stop()
                    Task { await backend.startNewConversation() }
                } label: {
                    Image(systemName: "square.and.pencil")
                }
                .buttonStyle(.icon)
                .help("New chat — memory carries forward, the transcript starts fresh")
                .disabled(backend.messages.isEmpty)

                Button {
                    showConversationList = true
                } label: {
                    Image(systemName: "clock.arrow.circlepath")
                }
                .buttonStyle(.icon)
                .help("Previous conversations")
                .popover(isPresented: $showConversationList) {
                    ConversationListPopover(backend: backend) { conversationID in
                        showConversationList = false
                        voiceOutput.stop()
                        Task { await backend.switchToConversation(conversationID) }
                    }
                }

                Button {
                    showTheBrief = true
                } label: {
                    Image(systemName: "sun.max")
                }
                .buttonStyle(.icon)
                .help("The Brief — what matters, what changed, what Frank recommends")
                .popover(isPresented: $showTheBrief) {
                    TheBriefPopover()
                }

                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Image(systemName: "magnifyingglass")
                }
                .buttonStyle(.icon)

                Button {
                    // no-op: shell only, not wired up yet
                } label: {
                    Label("Mission", systemImage: "plus")
                }
                .buttonStyle(.pillFilled)
                .fixedSize()
                .padding(.leading, 8)
            }
        }
        .padding(.horizontal, 32)
        .padding(.vertical, 20)
    }

    private var inputBar: some View {
        HStack(spacing: 12) {
            // Voice-first: this used to be a small icon tucked into the top
            // toolbar, separate from the actual input area -- the literal
            // reason voice read as an accessory rather than the primary way
            // to talk to Frank (direct feedback: "still gives me more of a
            // chatgpt vibe than something similar to jarvis"). Now it's the
            // first, most prominent thing in the input bar itself, same
            // visual weight as the send button.
            Button {
                if !voiceInput.isListening {
                    // About to start a new push-to-talk recording --
                    // confirmed decision: that interrupts any reply Frank
                    // is still speaking, same as cutting off a person
                    // mid-sentence, rather than talking over him or
                    // waiting him out.
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
            .help("Push-to-talk — click to start, stops and sends automatically once you stop talking")

            Button(action: pickImage) {
                Image(systemName: "paperclip")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .help("Attach an image — for Frank or the Design Agent to actually see")

            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(14))
                .foregroundStyle(theme.textPrimary)
                .focused($isInputFocused)
                .onSubmit(sendMessage)

            if backend.isStreaming {
                // Stop, same as Claude's own input bar -- actually
                // interrupts the connection (BackendClient.stopGenerating),
                // not just a cosmetic swap.
                Button(action: backend.stopGenerating) {
                    Image(systemName: "square.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(theme.accentText)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(theme.accentFill))
                }
                .buttonStyle(.plain)
                .help("Stop generating")
            } else {
                Button(action: sendMessage) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(theme.accentText)
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(theme.accentFill))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(.ultraThinMaterial)
        )
        .background(
            RoundedRectangle(cornerRadius: 24)
                .fill(theme.surface.opacity(0.3))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .strokeBorder(isInputFocused ? theme.textPrimary : theme.surfaceBorder, lineWidth: isInputFocused ? 2 : 1)
        )
        .shadow(color: theme.cardShadow, radius: isInputFocused ? 20 : 16, x: 0, y: isInputFocused ? 8 : 6)
        .animation(.easeOut(duration: 0.15), value: isInputFocused)
    }
}

/// Situation Room (2026-08-10) -- an escalated alert banner, deliberately
/// not styled like the calm right-rail Insights card: this should read
/// as "interrupt," not "routine list." Only ever shown when
/// SituationRoomClient.alerts is non-empty (WarRoomView.content), so its
/// absence is the honest, common case, not something hidden behind a
/// collapsed state.
private struct SituationRoomBanner: View {
    let alerts: [SituationRoomAlert]
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                Text("SITUATION ROOM")
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.4)
                    .foregroundStyle(.red)
            }
            ForEach(alerts) { alert in
                Text("\(alert.title) — \(alert.detail)")
                    .font(PCorpFont.body(12.5))
                    .foregroundStyle(theme.textPrimary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.vertical, 12)
        .background(Color.red.opacity(0.12))
        .overlay(Rectangle().frame(height: 1).foregroundStyle(.red.opacity(0.3)), alignment: .bottom)
    }
}

/// Engineering Agent's file-edit approval card (2026-08-27) -- shown
/// whenever BackendClient.pendingApproval is non-nil, blocking normal
/// chat input until Joshua explicitly approves or rejects (see
/// backend/app/engineering_agent.py's propose_file_edit tool). Styled as
/// a neutral bordered card, reusing attachedImageChip's own surface/
/// border treatment -- deliberately NOT SituationRoomBanner's red alert
/// styling above, since that's already this app's specific signal for a
/// real risk alert, and reusing it here would blur that meaning. This is
/// a decision request, not a risk alert.
private struct ApprovalRequestCard: View {
    let request: ApprovalRequest
    let onApprove: () -> Void
    let onReject: () -> Void
    @Environment(\.appTheme) private var theme
    @State private var isDiffExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "pencil.and.outline")
                    .foregroundStyle(theme.accentText)
                Text("ENGINEERING AGENT WANTS TO EDIT A FILE")
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.2)
                    .foregroundStyle(theme.textSecondary)
            }

            Text(request.path)
                .font(PCorpFont.body(13, weight: .semibold))
                .foregroundStyle(theme.textPrimary)

            Text(request.summary)
                .font(PCorpFont.body(13))
                .foregroundStyle(theme.textSecondary)

            DisclosureGroup("Show diff", isExpanded: $isDiffExpanded) {
                ScrollView {
                    Text(request.diff)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(theme.textPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 240)
            }
            .font(PCorpFont.body(12))

            HStack(spacing: 10) {
                Button("Reject", role: .destructive, action: onReject)
                    .buttonStyle(.bordered)
                Button("Approve", action: onApprove)
                    .buttonStyle(.borderedProminent)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(theme.surface.opacity(0.5)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(theme.accentFill, lineWidth: 1.5))
    }
}

/// Three dots, staggered bounce, repeating for as long as it's on screen
/// -- standard "typing" affordance, shown in place of the send button
/// exactly while backend.isStreaming is true.
private struct TypingIndicatorDots: View {
    @Environment(\.appTheme) private var theme
    @State private var animate = false

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(theme.textSecondary)
                    .frame(width: 5, height: 5)
                    .scaleEffect(animate ? 1 : 0.5)
                    .opacity(animate ? 1 : 0.4)
                    .animation(
                        .easeInOut(duration: 0.55)
                            .repeatForever(autoreverses: true)
                            .delay(Double(index) * 0.15),
                        value: animate
                    )
            }
        }
        .onAppear { animate = true }
    }
}

/// Frank's full conversation history — searchable, grouped by when each
/// conversation was last actually active. Built directly from a real
/// request ("I want frank to remember all chats indefinitely, I want to be
/// able to go to old chats at any point") — retention was already
/// indefinite (no expiry logic anywhere), but the original small popover
/// wouldn't have scaled to searching real history built up over months or
/// years, so this replaces it rather than sitting alongside it. Backed by
/// GET /conversations (optionally ?q=... for real message-content search,
/// not just preview text); picking a row calls
/// BackendClient.switchToConversation, which makes it active on the backend
/// and reconnects.
private struct ConversationListPopover: View {
    @ObservedObject var backend: BackendClient
    let onSelect: (Int) -> Void

    @State private var conversations: [ConversationSummary] = []
    @State private var isLoading = true
    @State private var searchText = ""
    @State private var searchTask: Task<Void, Never>?
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Conversations")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)

            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 12))
                    .foregroundStyle(theme.textSecondary)
                TextField("Search all conversations…", text: $searchText)
                    .textFieldStyle(.plain)
                    .font(PCorpFont.body(12.5))
                    .onChange(of: searchText) { _, newValue in
                        scheduleSearch(newValue)
                    }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 8).fill(theme.textPrimary.opacity(0.05)))
            .padding(.horizontal, 16)
            .padding(.bottom, 10)

            Divider().overlay(theme.divider)

            if isLoading {
                ProgressView()
                    .padding(20)
                    .frame(maxWidth: .infinity)
            } else if conversations.isEmpty {
                Text(searchText.isEmpty ? "No conversations yet" : "No matches for \"\(searchText)\"")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
                    .padding(20)
                    .frame(maxWidth: .infinity)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(groupedByDay, id: \.0) { day, dayConversations in
                            Text(day)
                                .font(PCorpFont.label(9))
                                .trackedLabel(1.1)
                                .foregroundStyle(theme.textSecondary)
                                .padding(.horizontal, 16)
                                .padding(.top, 10)
                                .padding(.bottom, 2)
                            ForEach(dayConversations) { conversation in
                                Button { onSelect(conversation.id) } label: {
                                    row(conversation)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
                .frame(maxHeight: 420)
            }
        }
        .frame(width: 360)
        .padding(.bottom, 8)
        .task { await load(query: nil) }
    }

    /// Groups by when each conversation was last actually active (real
    /// calendar day in the user's local timezone, not UTC — the DB stores
    /// UTC timestamps, but "today"/"yesterday" should mean the user's own
    /// today). Groups stay ordered newest-first, matching the overall list.
    private var groupedByDay: [(String, [ConversationSummary])] {
        let grouped = Dictionary(grouping: conversations) { conversation -> String in
            guard let date = Self.sqliteDateFormatter.date(from: conversation.lastMessageAt) else { return "Earlier" }
            if Calendar.current.isDateInToday(date) { return "Today" }
            if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
            return Self.dayLabelFormatter.string(from: date)
        }
        return grouped.sorted { lhs, rhs in
            let lhsDate = lhs.value.first.flatMap { Self.sqliteDateFormatter.date(from: $0.lastMessageAt) } ?? .distantPast
            let rhsDate = rhs.value.first.flatMap { Self.sqliteDateFormatter.date(from: $0.lastMessageAt) } ?? .distantPast
            return lhsDate > rhsDate
        }
    }

    private static let sqliteDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter
    }()

    private static let dayLabelFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, MMM d"
        return formatter
    }()

    /// Debounced — searches on every keystroke would mean a real request
    /// per character typed.
    private func scheduleSearch(_ text: String) {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            await load(query: text)
        }
    }

    private func load(query: String?) async {
        isLoading = true
        conversations = await backend.fetchConversationList(query: query)
        isLoading = false
    }

    private func row(_ conversation: ConversationSummary) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(conversation.firstMessage ?? "New conversation")
                .font(PCorpFont.body(12.5))
                .foregroundStyle(theme.textPrimary)
                .lineLimit(1)
            Text("\(conversation.messageCount) message\(conversation.messageCount == 1 ? "" : "s")")
                .font(PCorpFont.body(10.5))
                .foregroundStyle(theme.textSecondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}

/// The real chat thread — replaces the old single-line "most recent reply
/// only" display. The backend has persisted full conversation history since
/// day one (backend/app/db.py); this is the first time the UI actually
/// shows it. Auto-scrolls to the newest message, including while a reply is
/// still streaming in.
private struct ChatThreadView: View {
    let messages: [ChatMessage]
    let isStreaming: Bool

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(messages) { message in
                        // Only the LAST message can ever be the pending
                        // one -- an empty assistant bubble mid-array
                        // would just be a genuinely empty reply, not
                        // something to show a typing indicator for.
                        let isPending = isStreaming && message.id == messages.last?.id
                            && message.role == "assistant" && message.content.isEmpty
                        ChatBubble(message: message, isPending: isPending).id(message.id)
                    }
                }
                .padding(.horizontal, 48)
                .padding(.vertical, 16)
            }
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

private struct ChatBubble: View {
    let message: ChatMessage
    /// True only for the single trailing empty assistant bubble while a
    /// reply is being awaited -- shows the typing dots in place of
    /// (nonexistent) content, same spot real text will appear in once
    /// the first chunk arrives.
    var isPending: Bool = false
    @Environment(\.appTheme) private var theme

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 60) }

            content
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(isUser ? theme.accentFill : theme.surface.opacity(0.7))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .strokeBorder(isUser ? Color.clear : theme.surfaceBorder)
                )
                .frame(maxWidth: 520, alignment: isUser ? .trailing : .leading)

            if !isUser { Spacer(minLength: 60) }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }

    // Frank's replies can contain real markdown (an Operations Agent SOP
    // draft, a numbered list) -- rendering it plain showed literal `**`/`-`
    // characters instead of actual formatting. Reusing SimpleMarkdownView
    // (already built for the Knowledge section) rather than a second
    // renderer. User's own typed messages stay plain Text -- there's no
    // reason to interpret an incidental asterisk he types as bold syntax.
    @ViewBuilder
    private var content: some View {
        if isPending {
            TypingIndicatorDots()
        } else if isUser {
            VStack(alignment: .trailing, spacing: 8) {
                if let nsImage = message.image {
                    // Already decoded once at send time (BackendClient.send)
                    // -- real bug fixed 2026-08-10: decoding here in the view
                    // body re-ran on every re-render during streaming and
                    // visibly froze the chat. See ChatMessage.image's doc.
                    Image(nsImage: nsImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: 240, maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                } else if message.hasStoredImage {
                    // A reopened old conversation's message that had an
                    // image -- shown as a plain indicator, not re-fetched
                    // (see ChatMessage.hasStoredImage's own doc comment).
                    HStack(spacing: 6) {
                        Image(systemName: "photo")
                        Text("Image attached")
                    }
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.accentText.opacity(0.8))
                }
                if !message.content.isEmpty {
                    Text(message.content)
                        .font(PCorpFont.body(14))
                        .foregroundStyle(theme.accentText)
                }
            }
        } else {
            SimpleMarkdownView(text: message.content)
        }
    }
}

/// A restrained stand-in for Frank's presence — now a cluster of individual
/// particles rather than one solid shape, per direct feedback ("a blob of
/// particles floating" instead of a continuous liquid form). No mascot
/// features (no face, no eyes) — presence still comes from motion and
/// texture only, per FOUNDER_BRIEF.md/UI_GUIDELINES.md's anti-mascot
/// direction. Unlike the earlier hand-particle attempt, this doesn't sample
/// a bitmap — particle positions are generated directly from a deterministic
/// seeded random sequence, which is simple and reliable enough to trust
/// without a visual preview (the risk there was in reading pixels back out
/// of a rendered image; there's no such step here).
/// Frank's particle "Intelligence Core" (2026-08-20, Face-Lift brief item
/// 07) -- deliberately abstract, not a glowing AI-orb cliché. Four real
/// states, each wired to a genuinely real signal, not decoration:
/// - `.idle`: no signal, a slow, near-imperceptible synthetic shimmer.
/// - `.listening`: real mic RMS (VoiceInput.swift) -- particles contract
///   toward the centre, a "gathering" posture.
/// - `.speaking`: real TTS playback amplitude (VoiceOutput.swift) --
///   particles pulse outward with the actual sound.
/// - `.error`: a real capture/playback failure -- a restrained muted-
///   orange state, replacing what used to be a plain waveform-slash icon
///   with no relation to the orb at all.
///
/// The brief's other two named states, Thinking and Executing, are
/// deliberately NOT implemented here, not stubbed with dead code either.
/// This component isn't shown at all once a chat thread exists (the
/// thread + typing-dots take over instead — see this file's `content`
/// property), and tool-use happens invisibly inside the same
/// `isStreaming` window Frank's whole reply streams through, so there's
/// no honest, distinct signal for either state without changing *when*
/// this component appears — a War Room layout decision the brief's own
/// item 18 explicitly defers, not something to fold in unilaterally here.
/// One numbered row in the proactive greeting's attention list (2026-08-20,
/// Face-Lift item 08) -- "01 / LABEL / detail," matching the brief's own
/// example layout. `number` is a real 1-based position, not decoration.
private struct AttentionRow: View {
    let number: Int
    let item: WarRoomView.AttentionItem
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Text(String(format: "%02d", number))
                .font(PCorpFont.mono(12))
                .foregroundStyle(theme.textTertiary)
                .frame(width: 20, alignment: .leading)
            VStack(alignment: .leading, spacing: 1) {
                Text(item.label)
                    .font(PCorpFont.label(10))
                    .trackedLabel(1.0)
                    .foregroundStyle(theme.textPrimary)
                Text(item.detail)
                    .font(PCorpFont.body(13))
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }
}

private struct FrankOrb: View {
    enum OrbState: Equatable {
        case idle
        case listening(audioLevel: Double)
        case speaking(audioLevel: Double)
        case error
    }

    var state: OrbState = .idle

    @State private var floatUp = false
    @Environment(\.appTheme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var audioLevel: Double? {
        switch state {
        case .idle, .error: nil
        case .listening(let level), .speaking(let level): level
        }
    }

    /// The real "gravitational" behavior change the brief asks for,
    /// distinct from the shimmer/opacity pulsing that already existed --
    /// listening pulls particles in toward the centre (a fixed, steady
    /// contraction; audio level already drives per-particle shimmer, so
    /// this shouldn't also jitter with every RMS tick), speaking pushes
    /// them out scaled by how loud the real audio actually is.
    private var radiusScale: Double {
        switch state {
        case .idle, .error: 1.0
        case .listening: 0.78
        case .speaking(let level): 1.0 + level * 0.22
        }
    }

    private var particleColor: Color {
        state == .error ? .orange : theme.textPrimary
    }

    private struct Particle {
        let angle: Double
        let radiusFactor: Double // 0...1, distance from center as a fraction of the cluster's radius
        let size: CGFloat
        let phaseOffset: Double
    }

    /// Deterministic (fixed seed), not true randomness — same layout every
    /// launch, matching the rest of the shell's "reproducible, not jittery
    /// between runs" pattern. Bumped again, 260 -> 450, with larger dot sizes
    /// and higher base opacity per direct feedback ("more particles... it
    /// must be bolder") — this pass deliberately goes for a denser, more
    /// solid-reading cluster rather than a faint scatter.
    private static let particles: [Particle] = {
        var rng = SeededGenerator(seed: 7)
        return (0..<450).map { _ in
            let angle = Double.random(in: 0..<(2 * .pi), using: &rng)
            // Squaring biases points toward the center for a denser core that
            // thins out toward the edge, rather than a uniform-density disc.
            let radiusFactor = pow(Double.random(in: 0...1, using: &rng), 1.7)
            let size = CGFloat.random(in: 2.2...5.8, using: &rng)
            let phaseOffset = Double.random(in: 0..<(2 * .pi), using: &rng)
            return Particle(angle: angle, radiusFactor: radiusFactor, size: size, phaseOffset: phaseOffset)
        }
    }()

    var body: some View {
        ZStack {
            // Soft contact shadow — grounds the cluster so the float reads
            // as floating rather than just sliding up and down in place.
            Ellipse()
                .fill(theme.textPrimary.opacity(floatUp ? 0.08 : 0.16))
                .frame(width: floatUp ? 100 : 72, height: floatUp ? 14 : 10)
                .blur(radius: 8)
                .offset(y: 74)

            // Paused under Reduce Motion (2026-08-20) rather than removing
            // the component entirely -- real state changes (a state
            // transition, a real audio level jump) still redraw normally
            // since those come from ordinary SwiftUI view updates, not
            // from this schedule; only the continuous idle/decorative
            // ticking stops.
            TimelineView(.animation(paused: reduceMotion)) { timeline in
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    let maxRadius = min(size.width, size.height) / 2
                    let t = timeline.date.timeIntervalSinceReferenceDate
                    let scale = radiusScale
                    let color = particleColor

                    for particle in Self.particles {
                        let r = maxRadius * particle.radiusFactor * scale
                        let x = center.x + r * cos(particle.angle)
                        let y = center.y + r * sin(particle.angle)

                        // Per-particle shimmer, out of phase with its
                        // neighbors, so the cluster reads as alive rather
                        // than a static scatter of dots. Idle: a slower,
                        // lower-amplitude synthetic wave than before --
                        // "almost imperceptibly" per the brief, now that
                        // listening/speaking carry their own real motion
                        // instead of leaning on this same shimmer. Error:
                        // no shimmer at all, restrained per the brief, not
                        // an alarm. Listening/speaking: real audio level
                        // dominates, with a small synthetic component still
                        // blended in so the cluster keeps reading as organic
                        // per-particle motion rather than a flat pulse.
                        let syntheticShimmer = (sin(t * 0.5 + particle.phaseOffset) + 1) / 2 // 0...1
                        let shimmer: Double
                        switch state {
                        case .error:
                            shimmer = 0.4
                        case .idle:
                            shimmer = reduceMotion ? 0.5 : 0.35 + syntheticShimmer * 0.3
                        case .listening, .speaking:
                            let level = audioLevel ?? 0
                            shimmer = reduceMotion ? level : min(1.0, syntheticShimmer * 0.2 + level * 0.9)
                        }
                        // Higher floor and higher center value than before —
                        // this is the "bolder" lever: less see-through overall,
                        // a genuinely solid-reading core, not just more dots.
                        let baseOpacity = 0.32 + (1 - particle.radiusFactor) * 0.68
                        let opacity = min(baseOpacity * (0.7 + shimmer * 0.3), 1.0)
                        let dotSize = particle.size * (0.85 + shimmer * 0.15)

                        let rect = CGRect(x: x - dotSize / 2, y: y - dotSize / 2, width: dotSize, height: dotSize)
                        context.fill(Path(ellipseIn: rect), with: .color(color.opacity(opacity)))
                    }
                }
            }
            .offset(y: (reduceMotion ? 0 : (floatUp ? -10 : 10)))
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 3.4).repeatForever(autoreverses: true), value: floatUp)
        .animation(reduceMotion ? nil : .easeOut(duration: 0.5), value: state)
        .onAppear { if !reduceMotion { floatUp = true } }
    }
}

/// A minimal deterministic random generator (linear congruential) — used
/// wherever this shell needs "random-looking but reproducible every launch"
/// placement, since Swift's default generator is intentionally
/// non-reproducible between runs.
private struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64
    init(seed: UInt64) { self.state = seed }
    mutating func next() -> UInt64 {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return state
    }
}

/// The real P mark, finally. Three hand-built vector-path attempts (a
/// rounded stem+bowl, an angular folded-ribbon, and rendering the original
/// P_logo.pdf via PDFKit) all fell short — this shape is intricate enough
/// (angled facets, a beveled bowl, diagonal notches in the stem) that
/// guessing coordinates was never going to land. Joshua's actual reference
/// (a gold/metallic textured render, `p_logo_black.png` in Resources) was
/// processed directly instead: thresholded by luminance to separate the
/// bright letterform from its solid-black background, recolored to a flat
/// black silhouette with anti-aliased edges, and cropped to content bounds —
/// reading real pixel data rather than approximating from a description.
private struct PLogoMark: View {
    /// `.template` rendering mode treats the PNG as an alpha mask, so it
    /// tints via `theme.textPrimary` — black in light mode (matching
    /// Joshua's "make it black" request) but white in dark mode, so it
    /// doesn't go invisible against a dark background the way a hardcoded
    /// black fill would (same reasoning as the particle blob's theming).
    private static let image: Image? = {
        guard let url = AppResources.url(forResource: "p_logo_black", withExtension: "png"),
              let nsImage = NSImage(contentsOf: url)
        else { return nil }
        return Image(nsImage: nsImage)
    }()

    @Environment(\.appTheme) private var theme

    var body: some View {
        Group {
            if let image = Self.image {
                image
                    .resizable()
                    .renderingMode(.template)
                    .scaledToFit()
                    .foregroundStyle(theme.textPrimary)
            } else {
                // Fallback only if the resource fails to load at runtime.
                Text("P").font(.system(size: 22, weight: .bold, design: .rounded))
            }
        }
        .frame(width: 20, height: 24, alignment: .center)
    }
}
