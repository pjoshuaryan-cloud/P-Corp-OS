import SwiftUI

struct WarRoomView: View {
    @State private var inputText: String = ""
    @State private var showConversationList = false
    @Environment(\.appTheme) private var theme
    @FocusState private var isInputFocused: Bool
    @StateObject private var backend = BackendClient()

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

    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            content(currentDate: context.date)
        }
    }

    private func content(currentDate: Date) -> some View {
        VStack(spacing: 0) {
            topBar(currentDate: currentDate)

            if backend.messages.isEmpty {
                Spacer(minLength: 0)

                VStack(alignment: .leading, spacing: 12) {
                    Text("\(timeOfDayGreeting(at: currentDate)), Joshx.")
                        .font(PCorpFont.display(38, weight: .bold))
                        .foregroundStyle(theme.textPrimary)
                    Text("I'm Frank. How can I help you today?")
                        .font(PCorpFont.body(17))
                        .foregroundStyle(theme.textSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 48)

                Spacer(minLength: 20)

                // Only shown in the empty/idle state — once a text
                // conversation is active the thread takes this space
                // instead. Voice mode (not built yet) will be the other
                // case where this reappears, reactive to real audio rather
                // than the current synthetic shimmer — scoped separately.
                FrankOrb()
                    .frame(width: 185, height: 185)
                    .frame(maxWidth: .infinity)

                Spacer(minLength: 20)
            } else {
                ChatThreadView(messages: backend.messages)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }

            inputBar
                .padding(.horizontal, 48)
                .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.background)
        .onAppear { backend.connect() }
    }

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        backend.send(text)
        inputText = ""
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
                        Task { await backend.switchToConversation(conversationID) }
                    }
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
                    Image(systemName: "waveform.circle.fill")
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
            Image(systemName: "waveform")
                .foregroundStyle(theme.textSecondary)
            TextField("Talk to Frank...", text: $inputText)
                .textFieldStyle(.plain)
                .font(PCorpFont.body(14))
                .foregroundStyle(theme.textPrimary)
                .focused($isInputFocused)
                .onSubmit(sendMessage)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(theme.accentText)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(theme.accentFill))
            }
            .buttonStyle(.plain)
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

/// Lets Joshua get back to an older conversation — surfaced directly after
/// he asked "where would I find previous chats" once "new chat" existed but
/// nothing let him return to one. Backed by GET /conversations; picking a
/// row calls BackendClient.switchToConversation, which makes it active on
/// the backend and reconnects.
private struct ConversationListPopover: View {
    @ObservedObject var backend: BackendClient
    let onSelect: (Int) -> Void

    @State private var conversations: [ConversationSummary] = []
    @State private var isLoading = true
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Conversations")
                .font(PCorpFont.label(10))
                .trackedLabel(1.2)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, 14)
                .padding(.top, 12)
                .padding(.bottom, 8)

            if isLoading {
                ProgressView().padding(14)
            } else if conversations.isEmpty {
                Text("No conversations yet")
                    .font(PCorpFont.body(12))
                    .foregroundStyle(theme.textSecondary)
                    .padding(14)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(conversations) { conversation in
                            Button { onSelect(conversation.id) } label: {
                                row(conversation)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .frame(maxHeight: 320)
            }
        }
        .frame(width: 280)
        .padding(.bottom, 8)
        .task {
            conversations = await backend.fetchConversationList()
            isLoading = false
        }
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
        .padding(.horizontal, 14)
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

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    ForEach(messages) { message in
                        ChatBubble(message: message).id(message.id)
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
    @Environment(\.appTheme) private var theme

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 60) }

            Text(message.content)
                .font(PCorpFont.body(14))
                .foregroundStyle(isUser ? theme.accentText : theme.textPrimary)
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
private struct FrankOrb: View {
    @State private var floatUp = false
    @Environment(\.appTheme) private var theme

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

            TimelineView(.animation) { timeline in
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    let maxRadius = min(size.width, size.height) / 2
                    let t = timeline.date.timeIntervalSinceReferenceDate

                    for particle in Self.particles {
                        let r = maxRadius * particle.radiusFactor
                        let x = center.x + r * cos(particle.angle)
                        let y = center.y + r * sin(particle.angle)

                        // Per-particle shimmer, out of phase with its
                        // neighbors, so the cluster reads as alive rather
                        // than a static scatter of dots. This is a synthetic
                        // time-based wave (0.9 rad/s) — TODO, tracked in
                        // UI_GUIDELINES.md: once Frank actually has a voice
                        // (Phase 4+ of the UI build-out), this should be
                        // driven by real audio amplitude/frequency instead,
                        // so the blob visibly moves in sync with speech
                        // rather than an unrelated idle animation.
                        let shimmer = (sin(t * 0.9 + particle.phaseOffset) + 1) / 2 // 0...1
                        // Higher floor and higher center value than before —
                        // this is the "bolder" lever: less see-through overall,
                        // a genuinely solid-reading core, not just more dots.
                        let baseOpacity = 0.32 + (1 - particle.radiusFactor) * 0.68
                        let opacity = min(baseOpacity * (0.7 + shimmer * 0.3), 1.0)
                        let dotSize = particle.size * (0.85 + shimmer * 0.15)

                        let rect = CGRect(x: x - dotSize / 2, y: y - dotSize / 2, width: dotSize, height: dotSize)
                        context.fill(Path(ellipseIn: rect), with: .color(theme.textPrimary.opacity(opacity)))
                    }
                }
            }
            .offset(y: floatUp ? -10 : 10)
        }
        .animation(.easeInOut(duration: 3.4).repeatForever(autoreverses: true), value: floatUp)
        .onAppear { floatUp = true }
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
