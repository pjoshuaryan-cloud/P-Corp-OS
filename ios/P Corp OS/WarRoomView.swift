import SwiftUI
import PCorpKit
import PhotosUI
import QuickLook
import UniformTypeIdentifiers

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
    // Lifted up from WarRoomCommandMap (2026-09-11), same reasoning as
    // insightsClient's own 2026-09-07 move: this used to be a private
    // @StateObject there, unreachable from pull-to-refresh above it --
    // "AGENTS ONLINE" could be stuck showing 0 after a failed fetch with
    // no way to force a retry short of a full app relaunch.
    @StateObject private var agentsClient = AgentsClient()
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
    // Multi-attach (2026-09-05, generalized from the old single image-only
    // slots below) -- one PendingAttachment per staged file, any kind.
    @State private var pendingAttachments: [PendingAttachment] = []
    // photoPickerItem still drives the Photo picker binding, but no longer
    // 1:1 with a single attachment -- on load it appends and resets to nil
    // so the picker can be invoked again for another photo.
    // Real complaint, live (2026-09-11): this used to be a single
    // PhotosPickerItem?, so picking a second photo meant reopening the
    // picker from scratch each time. Now an array -- same photosPicker
    // API, just its multi-selection overload, matching how the
    // Document picker below already allows multiple at once. No client-
    // side cap: the backend already trims anything past
    // MAX_ATTACHMENTS_PER_MESSAGE with a clear in-band message
    // (document_attachments.py), same as an over-large Document
    // selection already does -- one true limit, not a duplicated one.
    @State private var photoPickerItems: [PhotosPickerItem] = []
    @State private var showPhotosPicker = false
    @State private var showDocumentImporter = false
    // Real complaint, live (2026-09-11): tapping these two small inline
    // refresh icons (Insights/Situation Room) looked identical whether
    // they were working or not -- these use a custom small/plain style
    // that doesn't match RefreshIconButton's `.icon`-styled circle, so
    // each gets its own local spinner state instead of reusing that
    // shared component here.
    @State private var isInsightsRefreshing = false
    @State private var isSituationRoomRefreshing = false
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
                ChatThreadView(messages: backend.messages, isStreaming: backend.isStreaming, runningTool: backend.runningTool, onRefresh: {
                    await backend.refreshHistory()
                    await focusClient.fetch()
                    await insightsClient.fetch()
                    await situationRoomClient.fetch()
                    await agentsClient.fetch()
                }) {
                    dashboardHeader
                }
            }
            if !pendingAttachments.isEmpty {
                AttachmentChipStrip(attachments: pendingAttachments) { id in
                    pendingAttachments.removeAll { $0.id == id }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            if let approval = backend.pendingApproval {
                ApprovalCard(
                    request: approval,
                    onApprove: { backend.respondToApproval(approved: true) },
                    onReject: { backend.respondToApproval(approved: false) }
                )
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            inputBar
                .disabled(backend.pendingApproval != nil)
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
            await agentsClient.fetch()
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
        .onChange(of: photoPickerItems) { _, newItems in
            guard !newItems.isEmpty else { return }
            let itemsToLoad = newItems
            Task {
                for item in itemsToLoad {
                    guard let data = try? await item.loadTransferable(type: Data.self),
                          UIImage(data: data) != nil
                    else { continue }
                    // Real bug found live, fixed as part of generalizing this
                    // to multi-attach (2026-09-05): this used to hardcode
                    // "image/jpeg" regardless of what was actually picked --
                    // derived properly now via the item's own content type,
                    // matching desktop's own (correct, file-extension-based)
                    // behavior.
                    let mediaType = item.supportedContentTypes.first?.preferredMIMEType ?? "image/jpeg"
                    await MainActor.run {
                        pendingAttachments.append(
                            PendingAttachment(data: data, mediaType: mediaType, filename: "photo", thumbnail: UIImage(data: data))
                        )
                    }
                }
                await MainActor.run { photoPickerItems = [] }
            }
        }
        .photosPicker(isPresented: $showPhotosPicker, selection: $photoPickerItems, matching: .images)
        .fileImporter(
            isPresented: $showDocumentImporter,
            allowedContentTypes: Self.documentContentTypes,
            allowsMultipleSelection: true
        ) { result in
            guard case .success(let urls) = result else { return }
            for url in urls { stageAttachment(from: url) }
        }
    }

    private static let documentContentTypes: [UTType] = {
        var types: [UTType] = [.pdf, .commaSeparatedText]
        if let docx = UTType(filenameExtension: "docx") { types.append(docx) }
        if let xlsx = UTType(filenameExtension: "xlsx") { types.append(xlsx) }
        return types
    }()

    /// The one code path for "a file got attached" via the document
    /// importer. Files outside the sandbox (iCloud Drive, Files app)
    /// require security-scoped access -- easy to omit and have it work
    /// fine in the Simulator's more forgiving sandbox while silently
    /// failing on a real device.
    private func stageAttachment(from url: URL) {
        guard url.startAccessingSecurityScopedResource() else { return }
        defer { url.stopAccessingSecurityScopedResource() }
        guard let data = try? Data(contentsOf: url) else { return }
        let filename = url.lastPathComponent
        let mediaType = Self.mediaType(forExtension: url.pathExtension.lowercased())
        pendingAttachments.append(PendingAttachment(data: data, mediaType: mediaType, filename: filename))
    }

    private static func mediaType(forExtension ext: String) -> String {
        switch ext {
        case "pdf": return "application/pdf"
        case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        case "xlsx": return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        case "csv": return "text/csv"
        default: return "application/octet-stream"
        }
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
            WarRoomCommandMap(agentsClient: agentsClient, insightsClient: insightsClient)
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
            HStack(spacing: 8) {
                sectionLabel("FRANK'S INSIGHTS")
                Spacer()
                // Real gap found live (2026-09-03, P Corp OS systems
                // audit): this card silently polls every 30s with no way
                // to force a refresh and no signal for how stale what's
                // on screen is -- confirmed the only two views in the
                // whole app missing both (the other being Situation Room
                // below).
                if let lastFetchedAt = insightsClient.lastFetchedAt {
                    Text("Updated \(lastFetchedAt.formatted(date: .omitted, time: .standard))")
                        .font(PCorpFont.body(9.5))
                        .foregroundStyle(theme.textTertiary)
                }
                Button {
                    guard !isInsightsRefreshing else { return }
                    isInsightsRefreshing = true
                    Task {
                        await insightsClient.fetch()
                        isInsightsRefreshing = false
                    }
                } label: {
                    if isInsightsRefreshing {
                        ProgressView()
                            .controlSize(.mini)
                            .frame(width: 11, height: 11)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                .buttonStyle(.plain)
                .disabled(isInsightsRefreshing)
            }
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
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(theme.statusRisk)
                Text("SITUATION ROOM")
                    .font(PCorpFont.label(10))
                    .tracking(1.4)
                    .foregroundStyle(theme.statusRisk)
                Spacer()
                // Real gap found live (2026-09-03, P Corp OS systems
                // audit): the only other view in the app with no manual
                // refresh and no staleness signal, alongside the Insights
                // card above -- an escalated alert shouldn't rely on
                // waiting out a silent 30s poll. Also matches desktop's
                // own WarRoomView.swift in using theme.statusRisk here
                // instead of raw .red -- this banner was one of the
                // pieces the 2026-08-31 UI cleanup pass deliberately left
                // for iOS's own follow-on sweep, fixed here since these
                // are the exact lines already being touched.
                if let lastFetchedAt = situationRoomClient.lastFetchedAt {
                    Text("Updated \(lastFetchedAt.formatted(date: .omitted, time: .standard))")
                        .font(PCorpFont.body(9))
                        .foregroundStyle(theme.statusRisk.opacity(0.7))
                }
                Button {
                    guard !isSituationRoomRefreshing else { return }
                    isSituationRoomRefreshing = true
                    Task {
                        await situationRoomClient.fetch()
                        isSituationRoomRefreshing = false
                    }
                } label: {
                    if isSituationRoomRefreshing {
                        ProgressView()
                            .controlSize(.mini)
                            .frame(width: 10, height: 10)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(theme.statusRisk.opacity(0.8))
                    }
                }
                .buttonStyle(.plain)
                .disabled(isSituationRoomRefreshing)
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
        .background(theme.statusRisk.opacity(0.12))
        .overlay(Rectangle().frame(height: 1).foregroundStyle(theme.statusRisk.opacity(0.3)), alignment: .bottom)
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 12) {
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

            // PhotosPicker is photo-library-only -- it can't reach Files/
            // iCloud Drive, so documents need a second, separate trigger
            // (.fileImporter, below) behind this same paperclip glyph
            // (2026-09-05, generalized from image-only).
            Menu {
                Button("Photo") { showPhotosPicker = true }
                Button("Document") { showDocumentImporter = true }
            } label: {
                Image(systemName: "paperclip")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.textSecondary)
                    .frame(width: 32, height: 32)
            }

            GrowingChatInput(
                text: $inputText,
                placeholder: "Talk to Frank...",
                isFocused: $isInputFocused,
                onSend: sendMessage
            )

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
        guard !text.isEmpty || !pendingAttachments.isEmpty else { return }
        backend.send(text, attachments: pendingAttachments)
        inputText = ""
        pendingAttachments = []
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

/// Engineering Agent's file-edit approval card (2026-08-27, iOS parity
/// port of desktop's own) -- shown whenever BackendClient.pendingApproval
/// is non-nil, blocking normal chat input until Joshua explicitly
/// approves or rejects. Generalized (2026-09-06, iOS parity port of
/// desktop's own same-day refactor) from two separate card views
/// (ApprovalRequestCard/CalendarApprovalCard) into one that switches on
/// request.kind, on the third approval flow's arrival (automation-rule
/// creation) -- see BackendClient.swift's ApprovalRequest doc comment.
/// Styled as a neutral bordered card, reusing attachedImageChip's own
/// surface/border treatment -- deliberately NOT situationRoomBanner's red
/// alert styling above, since that's already this app's specific signal
/// for a real risk alert, and reusing it here would blur that meaning.
/// This is a decision request, not a risk alert.
private struct ApprovalCard: View {
    let request: ApprovalRequest
    let onApprove: () -> Void
    let onReject: () -> Void
    @Environment(\.appTheme) private var theme
    @State private var isDiffExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            switch request.kind {
            case .fileEdit: fileEditBody
            case .calendarChange: calendarChangeBody
            case .automationRule: automationRuleBody
            case .alphaModeChange: alphaModeChangeBody
            }
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

    @ViewBuilder
    private var header: some View {
        HStack(spacing: 6) {
            switch request.kind {
            case .fileEdit:
                Image(systemName: "pencil.and.outline").foregroundStyle(theme.accentText)
                Text("ENGINEERING AGENT WANTS TO EDIT A FILE")
            case .calendarChange:
                Image(systemName: "calendar.badge.clock").foregroundStyle(theme.accentText)
                Text("FRANK WANTS TO CHANGE YOUR CALENDAR")
            case .automationRule:
                Image(systemName: "bolt.badge.clock").foregroundStyle(theme.accentText)
                Text("FRANK WANTS TO CREATE AN AUTOMATION")
            case .alphaModeChange:
                Image(systemName: "building.2.crop.circle").foregroundStyle(theme.accentText)
                Text("FRANK WANTS TO UPDATE ALPHA MODE MEDIA")
            }
        }
        .font(PCorpFont.label(10))
        .tracking(1.2)
        .foregroundStyle(theme.textSecondary)
    }

    @ViewBuilder
    private var fileEditBody: some View {
        Text(request.path ?? "")
            .font(PCorpFont.body(13, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
        Text(request.summary ?? "")
            .font(PCorpFont.body(13))
            .foregroundStyle(theme.textSecondary)
        DisclosureGroup("Show diff", isExpanded: $isDiffExpanded) {
            ScrollView {
                Text(request.diff ?? "")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(theme.textPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(maxHeight: 240)
        }
        .font(PCorpFont.body(12))
    }

    @ViewBuilder
    private var calendarChangeBody: some View {
        Text(request.title ?? "")
            .font(PCorpFont.body(13, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
        Text(request.details ?? "")
            .font(PCorpFont.body(13))
            .foregroundStyle(theme.textSecondary)
    }

    @ViewBuilder
    private var alphaModeChangeBody: some View {
        Text(request.title ?? "")
            .font(PCorpFont.body(13, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
        Text(request.details ?? "")
            .font(PCorpFont.body(13))
            .foregroundStyle(theme.textSecondary)
    }

    @ViewBuilder
    private var automationRuleBody: some View {
        Text(request.name ?? "")
            .font(PCorpFont.body(13, weight: .semibold))
            .foregroundStyle(theme.textPrimary)
        Text(request.description ?? "")
            .font(PCorpFont.body(13))
            .foregroundStyle(theme.textSecondary)
        Text("Trigger: \(request.triggerTool ?? "?")  ·  Agent: \(request.agent ?? "?")")
            .font(PCorpFont.body(11.5))
            .foregroundStyle(theme.textTertiary)
        Text(request.instruction ?? "")
            .font(PCorpFont.body(12))
            .foregroundStyle(theme.textSecondary)
    }
}

/// Its own dedicated scroll region with auto-scroll-to-newest, including
/// while a reply is still streaming in -- same proven pattern as
/// desktop's own ChatThreadView, and the same chat bubble styling
/// (ChatBubble there) copied here rather than approximated.
private struct ChatThreadView<Header: View>: View {
    let messages: [ChatMessage]
    let isStreaming: Bool
    let runningTool: String?
    // Pull-to-refresh (2026-09-11, real request live) -- refreshes the
    // dashboard data inside `header()` (Focus/Insights/Situation Room),
    // not the chat thread itself: there's no "refresh" concept for a live
    // WebSocket conversation, and the header is what's actually stale
    // data a pull-down gesture should update.
    let onRefresh: () async -> Void
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
                            // Same "only the last message" reasoning as
                            // desktop's own ChatThreadView -- a tool call
                            // is always part of the turn currently in
                            // flight, never an older one.
                            let isPending = isStreaming && message.id == messages.last?.id
                                && message.role == "assistant" && message.content.isEmpty
                            let isLast = message.id == messages.last?.id
                            ChatBubble(message: message, isPending: isPending, runningTool: isLast ? runningTool : nil).id(message.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
            }
            .refreshable { await onRefresh() }
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

/// Ported verbatim from desktop's own private TypingIndicatorDots
/// (WarRoomView.swift there), 2026-09-04 -- iOS had no equivalent at all
/// before this (ChatBubble below used to show a static "…" literal with
/// no animation while a reply was pending), a real, separate gap fixed
/// here as a side effect of adding the tool-execution indicator, which
/// needed this same dots affordance to build on.
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

/// Exact match for desktop's own private ChatBubble (WarRoomView.swift
/// there) -- same colors, corner radius, padding, max width, spacer
/// widths. Plain Text, not desktop's markdown renderer -- that lives in
/// a desktop-only file (SimpleMarkdownView), a real follow-up, not a
/// shortfall of this pass specifically.
private struct ChatBubble: View {
    let message: ChatMessage
    /// True only for the single trailing empty assistant bubble while a
    /// reply is being awaited -- same meaning as desktop's own ChatBubble.
    var isPending: Bool = false
    /// The friendly label from the backend's most recent tool call while
    /// it's still running (see BackendClient.runningTool), non-nil only
    /// for the trailing message. Shown alongside the typing dots when no
    /// text has streamed yet, or appended below already-streamed text
    /// when a tool fires mid-reply (2026-09-04) -- same shape as desktop's
    /// own ChatBubble, ported here alongside TypingIndicatorDots below
    /// since neither existed on iOS before this.
    var runningTool: String? = nil
    @Environment(\.appTheme) private var theme
    @State private var previewURL: URL?

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 40) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                // Generalized 2026-09-05 from a single image to any kind/
                // count of attachment -- see MessageAttachmentsView's own
                // doc comment (only ever meaningfully populated for a user
                // message; Frank never attaches anything to his own
                // replies, so this renders as nothing for assistant
                // messages exactly as the old image-only version did).
                MessageAttachmentsView(
                    attachments: message.attachments,
                    storedAttachmentNames: message.storedAttachmentNames
                )
                // Real PDFs Frank generated (2026-09-09, "viewable &
                // saveable" fix) -- fetched over the network (no
                // filesystem access to the Mac from a phone), then shown
                // via SwiftUI's own native QuickLook integration.
                ForEach(message.generatedDocuments) { document in
                    GeneratedDocumentRow(document: document) {
                        Task {
                            guard let (data, _) = try? await BackendURLSession.shared.data(
                                from: BackendClient.documentURL(filename: document.filename)
                            ) else { return }
                            let tempURL = FileManager.default.temporaryDirectory
                                .appendingPathComponent(document.filename)
                            try? data.write(to: tempURL)
                            previewURL = tempURL
                        }
                    }
                }
                if isPending, let runningTool {
                    HStack(spacing: 6) {
                        TypingIndicatorDots()
                        Text(runningTool)
                            .font(PCorpFont.body(12))
                            .foregroundStyle(theme.textPrimary.opacity(0.7))
                    }
                } else if isPending {
                    TypingIndicatorDots()
                } else if !message.content.isEmpty || (message.attachments.isEmpty && message.storedAttachmentNames.isEmpty) {
                    if isUser {
                        // User's own literally-typed characters -- a
                        // stray "*"/"#" shouldn't be reinterpreted as
                        // markdown syntax, matching desktop's own
                        // assistant-only-markdown decision exactly.
                        Text(message.content)
                            .font(PCorpFont.body(14))
                            // Real bug found live (2026-08-27): Joshua
                            // couldn't copy chat text to paste elsewhere --
                            // plain SwiftUI Text isn't selectable by default.
                            .textSelection(.enabled)
                    } else {
                        // Real gap closed (2026-09-05): this used to be
                        // plain Text for assistant replies too, so
                        // headings/lists/bold/italic never rendered here
                        // at all -- desktop's own ChatBubble already used
                        // SimpleMarkdownView; iOS's chat view just hadn't
                        // been wired up to it yet (iOS's Knowledge section
                        // already was). Now also gets tables/code blocks
                        // for free as SimpleMarkdownView's own capability.
                        SimpleMarkdownView(text: message.content)
                    }
                    if let runningTool {
                        HStack(spacing: 6) {
                            TypingIndicatorDots()
                            Text(runningTool)
                                .font(PCorpFont.body(12))
                                .foregroundStyle(theme.textPrimary.opacity(0.7))
                        }
                    }
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
        .quickLookPreview($previewURL)
    }
}

#Preview {
    WarRoomView(backend: BackendClient(), situationRoomClient: SituationRoomClient())
}
