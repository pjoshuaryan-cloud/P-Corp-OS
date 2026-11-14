import AVFoundation
import Foundation

/// Speaks Frank's reply a piece at a time while it is still being written (conversational voice, 2026-11-14). Before this,
/// the app waited for the whole reply, sent all of it to ElevenLabs, downloaded the whole audio file, and only then started
/// playing -- a long silence for a long reply. Now each finished sentence (SpeechChunker) is queued here: its audio is fetched
/// while the previous one plays (up to `prefetchAhead` ahead), and pieces play back to back in order.
///
/// Shared by the Mac and iPhone apps: each app's VoiceOutput subclasses this and supplies `fetchAudio` (its /speak call) and,
/// on the iPhone, `preparePlayback` (the audio session).
///
/// Use: `beginReply()`, then `enqueue(_:)` for each piece, then `endReply()` once the reply is complete. `speak(_:)` does all
/// three for a single line (the greeting). `stop()` cuts Frank off at once (Josh talking over him, or a new recording).
/// `onReplyFinished` fires only when a reply has been spoken to the end, not when it was stopped.
@MainActor
open class ReplySpeaker: NSObject, ObservableObject, AVAudioPlayerDelegate {
    /// A reply is in progress: waiting for its first audio, or playing.
    @Published public private(set) var isSpeaking = false
    /// Audio is actually playing right now (false while the first piece is still being written or fetched).
    @Published public private(set) var isPlaying = false
    /// Real amplitude of what's playing, 0...1 -- feeds the orb.
    @Published public private(set) var audioLevel: Double = 0
    @Published public var errorMessage: String?
    /// Everything Frank has started saying aloud in this reply, plus the piece about to play -- what the echo filter compares
    /// the mic against when Josh may be talking over him (EchoFilter, ConversationalVoice.swift).
    public private(set) var spokenText = ""
    public var onReplyFinished: (() -> Void)?
    /// Bumped on every beginReply()/stop(); a fetch from a superseded reply is thrown away when it returns.
    public private(set) var replyGeneration = 0
    public var prefetchAhead = 2

    private struct Piece { let text: String; var audio: Data?; var failed = false }
    private var pieces: [Piece] = []
    private var replyOpen = false
    private var fetching = false
    private var player: AVAudioPlayer?
    private var meterTask: Task<Void, Never>?
    private var fetchTask: Task<Void, Never>?

    public override init() { super.init() }

    // MARK: subclass hooks

    /// The audio (mp3 or wav) for one piece of text. Subclasses call the backend's /speak.
    open func fetchAudio(for text: String) async throws -> Data {
        throw NSError(domain: "ReplySpeaker", code: 1, userInfo: [NSLocalizedDescriptionKey: "no voice configured"])
    }

    /// Called just before each piece plays (the iPhone sets its audio session here).
    open func preparePlayback() throws {}

    /// A piece couldn't be fetched or played. The rest of the reply still plays.
    open func pieceFailed(_ error: Error, text: String) {
        errorMessage = "Frank's voice failed: \(error.localizedDescription)"
    }

    // MARK: speaking

    public func beginReply() {
        stop()
        replyGeneration += 1
        replyOpen = true
        spokenText = ""
        errorMessage = nil
        isSpeaking = true
    }

    public func enqueue(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard replyOpen, !trimmed.isEmpty else { return }
        pieces.append(Piece(text: trimmed))
        pump()
    }

    public func endReply() {
        guard replyOpen else { return }
        replyOpen = false
        pump()
    }

    /// One line, start to finish.
    public func speak(_ text: String) {
        beginReply()
        enqueue(text)
        endReply()
    }

    public func stop() {
        replyGeneration += 1
        fetchTask?.cancel()
        fetchTask = nil
        meterTask?.cancel()
        meterTask = nil
        player?.stop()
        player = nil
        pieces = []
        replyOpen = false
        fetching = false
        isSpeaking = false
        isPlaying = false
        audioLevel = 0
    }

    /// Plays what's ready, fetches what's next, and finishes the reply when nothing is left.
    private func pump() {
        if player == nil {
            while let first = pieces.first, first.failed { pieces.removeFirst() }
            if let first = pieces.first, let audio = first.audio {
                pieces.removeFirst()
                play(audio, text: first.text)
            }
        }
        if !fetching, let index = pieces.firstIndex(where: { $0.audio == nil && !$0.failed }), index < prefetchAhead {
            fetch(at: index)
        }
        if player == nil, pieces.isEmpty, !replyOpen, !fetching, isSpeaking {
            isSpeaking = false
            isPlaying = false
            audioLevel = 0
            onReplyFinished?()
        }
    }

    private func fetch(at index: Int) {
        fetching = true
        let generation = replyGeneration
        let text = pieces[index].text
        fetchTask = Task {
            var audio: Data?
            var failure: Error?
            do { audio = try await fetchAudio(for: text) } catch { failure = error }
            guard generation == replyGeneration else { return }   // stopped or replaced while in flight
            fetching = false
            if let slot = pieces.firstIndex(where: { $0.text == text && $0.audio == nil && !$0.failed }) {
                if let audio { pieces[slot].audio = audio } else { pieces[slot].failed = true }
            }
            if let failure { pieceFailed(failure, text: text) }
            pump()
        }
    }

    private func play(_ audio: Data, text: String) {
        do {
            try preparePlayback()
            let newPlayer = try AVAudioPlayer(data: audio)
            newPlayer.isMeteringEnabled = true
            newPlayer.delegate = self
            guard newPlayer.play() else {
                throw NSError(domain: "ReplySpeaker", code: 2, userInfo: [NSLocalizedDescriptionKey: "the audio player refused to start"])
            }
            player = newPlayer
            spokenText += (spokenText.isEmpty ? "" : " ") + text
            isPlaying = true
            startMetering(generation: replyGeneration)
        } catch {
            pieceFailed(error, text: text)
            pump()
        }
    }

    private func startMetering(generation: Int) {
        meterTask?.cancel()
        meterTask = Task {
            while !Task.isCancelled, replyGeneration == generation, let player, player.isPlaying {
                player.updateMeters()
                // averagePower is in decibels, roughly -160 (silence) to 0 (loudest), remapped to 0...1 for the orb.
                audioLevel = max(0, min(1, (Double(player.averagePower(forChannel: 0)) + 50) / 50))
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
        }
    }

    private func pieceEnded(_ id: ObjectIdentifier) {
        guard let player, ObjectIdentifier(player) == id else { return }
        self.player = nil
        isPlaying = false
        audioLevel = 0
        pump()
    }

    nonisolated public func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let id = ObjectIdentifier(player)
        Task { @MainActor in self.pieceEnded(id) }
    }

    nonisolated public func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        let id = ObjectIdentifier(player)
        Task { @MainActor in self.pieceEnded(id) }
    }
}

/// Asks the backend whether Josh has finished talking (POST /voice/turn-check, Claude Haiku 5.5). Returns nil when the check is
/// off, slow or failed -- the caller then decides from the pause and the words alone (TurnTaking). Once the backend says the
/// check is off, it isn't asked again for 10 minutes.
public enum VoiceTurnCheck {
    @MainActor private static var offUntil: Date?

    @MainActor
    public static func ask(transcript: String, frankLast: String?) async -> TurnTaking.Verdict? {
        if let offUntil, Date() < offUntil { return nil }
        var request = URLRequest(url: BackendHost.url(path: "/voice/turn-check"))
        request.httpMethod = "POST"
        request.timeoutInterval = 3
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        struct Body: Encodable { let transcript: String; let frank_last: String? }
        struct Reply: Decodable { let enabled: Bool; let verdict: TurnTaking.Verdict? }
        guard let body = try? JSONEncoder().encode(Body(transcript: transcript, frank_last: frankLast)) else { return nil }
        request.httpBody = body
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let reply = try? JSONDecoder().decode(Reply.self, from: data) else { return nil }
        if !reply.enabled { offUntil = Date().addingTimeInterval(600) }
        return reply.verdict
    }
}
