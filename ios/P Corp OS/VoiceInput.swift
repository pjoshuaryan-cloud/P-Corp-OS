import AVFoundation
import Combine
import Foundation
import PCorpKit
import Speech

/// iOS port of desktop's VoiceInput.swift: tap once to start, it stops by itself after you finish talking (or tap again
/// to send at once).
///
/// 2026-10-11: the "finished talking" rule was rebuilt (see PCorpKit's VoiceEndpointing.swift). It used to stop 1.2 s
/// after the mic last heard a FIXED volume, copied from the Mac and never checked on the phone, which cut people off at
/// every thinking pause ("Frank I want you to"). It now waits 2.5 s (4 s after an unfinished-sounding word like "to"),
/// learns the room's background level instead of using a fixed number, and counts new words from the recognizer as proof
/// you're still talking. If Apple's recognizer ends a stretch by itself while you are still talking, a new stretch is
/// started and the text is joined, instead of sending half a sentence. `lastStopNote` says in plain words why the last
/// recording ended, so a cut-off can be diagnosed instead of guessed at.
@MainActor
final class VoiceInput: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var transcript = ""
    @Published private(set) var audioLevel: Double = 0
    @Published private(set) var errorMessage: String?
    /// Why the last recording ended ("Stopped after a 2.5 s pause."), shown for a few seconds. nil after a plain tap.
    @Published private(set) var lastStopNote: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private let requestBox = RecognitionRequestBox()
    private var task: SFSpeechRecognitionTask?
    private var onFinishedCallback: ((String?) -> Void)?
    private var didDeliver = false
    private var stopRequested = false

    private var endpointer = VoiceEndpointer()
    private var recordingStartedAt = Date()

    // Apple's recognizer can end a stretch of audio on its own; the text of finished stretches is kept here and the
    // recognizer is started again on the same live audio.
    private var committedText = ""
    private var segmentText = ""
    private var segmentID = 0
    private var segmentStartedAt = Date()
    private var recognizerRestarts = 0
    private let maxRestarts = 8

    /// Everything recognized in the current recording, echo included.
    private var rawTranscript: String {
        [committedText, segmentText].filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// What Josh said: in a conversation, the echo of Frank before Josh cut in (`dropWords`) is left out.
    private var joinedTranscript: String {
        dropWords > 0 ? Self.dropping(dropWords, from: rawTranscript) : rawTranscript
    }

    /// `text` without its first `count` words (counted the way EchoFilter counts them).
    private static func dropping(_ count: Int, from text: String) -> String {
        var seen = 0
        let tokens = text.split(whereSeparator: { $0.isWhitespace })
        for (i, token) in tokens.enumerated() {
            if seen >= count { return tokens[i...].joined(separator: " ") }
            seen += EchoFilter.wordCount(String(token))
        }
        return ""
    }

    // MARK: Conversation mode (2026-11-14)
    //
    // One tap starts a back-and-forth: the mic stays on for the whole conversation (shown on screen the whole time) and turns
    // pass between Josh and Frank with no clicking. Josh's turn ends when TurnTaking (PCorpKit, ConversationalVoice.swift) says
    // he's finished -- the pause, the words, and optionally the small model (VoiceTurnCheck) -- not a fixed timer, so a long
    // answer with thinking pauses isn't cut off. During Frank's turn the mic listens for Josh talking over him (EchoFilter
    // tells his words from Frank's echo on the speakers); when he does, Frank stops and Josh's words so far are kept.
    // It ends when he taps it off, says "that's all" (ConversationExit), or stays quiet for 8 s on his turn.
    // This changes the 2026-07-28 push-to-talk decision ONLY while conversation mode is switched on (Josh's call, 2026-11-14).
    // On the iPhone the conversation uses the call audio mode (.playAndRecord / .voiceChat): the phone's own echo
    // cancellation then removes most of Frank's voice from the mic, and EchoFilter handles what's left.

    /// True while a conversation holds the audio session: VoiceOutput must not switch it to playback-only then, or the mic
    /// would stop (VoiceOutput.preparePlayback).
    static private(set) var conversationHoldsAudioSession = false

    enum ConversationPhase: Equatable { case josh, frank }
    /// nil = not in a conversation (plain push-to-talk).
    @Published private(set) var conversationPhase: ConversationPhase?
    var isInConversation: Bool { conversationPhase != nil }

    private var frankSaid: () -> String = { "" }
    private var onTurn: ((String, ConversationExit) -> Void)?
    private var onBargeIn: (() -> Void)?
    private var onConversationEnded: ((String?) -> Void)?
    private var dropWords = 0
    /// Set when this recording was stopped by ending a conversation (see handleRecognition's stopRequested branch).
    private var endedConversation = false
    private var verdicts: [String: TurnTaking.Verdict] = [:]
    private var askedModelFor: Set<String> = []

    private static let checkWaitLimit: TimeInterval = 2.2

    private static func conversationEndpointer() -> VoiceEndpointer {
        var settings = VoiceEndpointer.Settings()
        settings.pauseSeconds = .infinity          // TurnTaking decides when a turn ends
        settings.danglingPauseSeconds = .infinity
        settings.noSpeechSeconds = 8               // quiet on his turn for 8 s: the conversation ends
        settings.maxSeconds = 120
        return VoiceEndpointer(settings: settings)
    }

    /// Starts a conversation. `frankSaid` returns what Frank has said aloud in his current reply (for the echo check);
    /// `onTurn` gets each finished turn of Josh's; `onBargeIn` fires when Josh talks over Frank (stop Frank's voice);
    /// `onEnded` fires once, with a note on why it ended (nil when Josh tapped it off).
    func startConversation(frankSaid: @escaping () -> String, onTurn: @escaping (String, ConversationExit) -> Void,
                           onBargeIn: @escaping () -> Void, onEnded: @escaping (String?) -> Void) {
        guard !isListening else { return }
        self.frankSaid = frankSaid
        self.onTurn = onTurn
        self.onBargeIn = onBargeIn
        self.onConversationEnded = onEnded
        conversationPhase = .josh
        start { [weak self] transcript in
            // Only reached when recording couldn't start (permissions, no recognizer): turns are delivered through onTurn.
            guard let self, transcript == nil, self.conversationPhase != nil, !self.isListening else { return }
            self.endConversation(note: self.errorMessage)
        }
    }

    /// Frank has finished his reply (or had nothing to say): it's Josh's turn.
    func frankFinished() {
        guard conversationPhase == .frank, isListening else { return }
        conversationPhase = .josh
        startFreshTurn()
    }

    /// Ends the conversation and turns the mic off. Nothing more is sent.
    func endConversation(note: String? = nil) {
        guard conversationPhase != nil else { return }
        let ended = onConversationEnded
        conversationPhase = nil
        onTurn = nil
        onBargeIn = nil
        onConversationEnded = nil
        frankSaid = { "" }
        dropWords = 0
        if isListening {
            onFinishedCallback = nil
            endedConversation = true
            stop(note: note)
        } else if let note {
            setStopNote(note)
        }
        ended?(note)
    }

    /// A new turn on the same live audio: what was heard so far (Josh's last turn, or Frank's echo) is dropped.
    private func startFreshTurn() {
        committedText = ""
        segmentText = ""
        transcript = ""
        dropWords = 0
        recognizerRestarts = 0
        verdicts = [:]
        askedModelFor = []
        endpointer = Self.conversationEndpointer()
        recordingStartedAt = Date()
        startSegment()
    }

    /// Josh's turn, on every audio buffer: has he finished?
    private func handleConversationLevel(rms: Double) {
        let elapsed = Date().timeIntervalSince(recordingStartedAt)
        if conversationPhase == .frank {
            let heard = rawTranscript
            guard !heard.isEmpty, EchoFilter.isBargeIn(heard: heard, frankSaid: frankSaid()) else { return }
            // Josh is talking over Frank. Keep listening on the same audio (his first words are mid-recognition), drop the echo
            // before them, and make it his turn.
            dropWords = EchoFilter.joshStartIndex(heard: heard, frankSaid: frankSaid()) ?? 0
            transcript = joinedTranscript
            conversationPhase = .josh
            endpointer = Self.conversationEndpointer()
            recordingStartedAt = Date()
            verdicts = [:]
            askedModelFor = []
            onBargeIn?()
            return
        }
        if let reason = endpointer.feed(rms: rms, elapsed: elapsed, transcript: transcript) {
            switch reason {
            case .noSpeech: endConversation(note: "Conversation ended after 8 s of quiet.")
            case .timeLimit: deliverTurn()
            case .pause: break
            }
            return
        }
        guard endpointer.hasDetectedSpeech else { return }
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let pause = elapsed - endpointer.lastVoiceAt
        let talked = endpointer.lastVoiceAt - (endpointer.firstVoiceAt ?? endpointer.lastVoiceAt)
        if TurnTaking.worthAskingModel(pause: pause, transcript: text), !askedModelFor.contains(text) {
            askedModelFor.insert(text)
            let frankLast = frankSaid()
            Task { [weak self] in
                if let verdict = await VoiceTurnCheck.ask(transcript: text, frankLast: frankLast.isEmpty ? nil : frankLast) {
                    self?.verdicts[text] = verdict
                }
            }
        }
        // The check takes about a second from here (measured 2026-11-14: 1.0-1.1 s). While it's on its way, wait for it
        // (up to `checkWaitLimit` of pause) rather than answering on the pause alone and cutting Josh off mid-thought.
        if askedModelFor.contains(text), verdicts[text] == nil, pause < Self.checkWaitLimit { return }
        if TurnTaking.shouldRespond(pause: pause, transcript: text, talkedSeconds: talked, verdict: verdicts[text]) {
            deliverTurn()
        }
    }

    private func deliverTurn() {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, conversationPhase == .josh else { return }
        let exit = ConversationExit.check(text)
        if exit == .endOnly {
            endConversation(note: "Conversation ended: you said \"\(text)\".")
            return
        }
        conversationPhase = .frank
        startFreshTurn()
        onTurn?(text, exit)
    }

    func toggle(onFinished: @escaping (String?) -> Void) {
        if isInConversation {
            endConversation()
        } else if isListening {
            stop(note: nil)
        } else {
            start(onFinished: onFinished)
        }
    }

    private func start(onFinished: @escaping (String?) -> Void) {
        errorMessage = nil
        lastStopNote = nil
        transcript = ""

        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            Task { @MainActor in
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "Speech recognition permission not granted."
                    onFinished(nil)
                    return
                }
                AVAudioApplication.requestRecordPermission { granted in
                    Task { @MainActor in
                        guard granted else {
                            self.errorMessage = "Microphone permission not granted."
                            onFinished(nil)
                            return
                        }
                        self.beginRecording(onFinished: onFinished)
                    }
                }
            }
        }
    }

    private func beginRecording(onFinished: @escaping (String?) -> Void) {
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Speech recognizer unavailable right now."
            onFinished(nil)
            return
        }

        do {
            let session = AVAudioSession.sharedInstance()
            if isInConversation {
                // Mic and Frank's voice at once, with the phone's echo cancellation; speaker by default, AirPods for output if connected.
                try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothA2DP, .duckOthers])
                Self.conversationHoldsAudioSession = true
            } else {
                try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            }
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            errorMessage = "Couldn't configure audio session: \(error.localizedDescription)"
            onFinished(nil)
            return
        }

        onFinishedCallback = onFinished
        didDeliver = false
        endedConversation = false
        stopRequested = false
        endpointer = isInConversation ? Self.conversationEndpointer() : VoiceEndpointer()
        recordingStartedAt = Date()
        dropWords = 0
        committedText = ""
        segmentText = ""
        recognizerRestarts = 0
        startSegment()

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self, requestBox] buffer, _ in
            requestBox.append(buffer)
            guard let channelData = buffer.floatChannelData?[0] else { return }
            let frameLength = Int(buffer.frameLength)
            guard frameLength > 0 else { return }
            var sum: Float = 0
            for i in 0..<frameLength { sum += channelData[i] * channelData[i] }
            let rms = Double(sqrt(sum / Float(frameLength)))
            Task { @MainActor in
                self?.audioLevel = min(rms * 12, 1.0)
                self?.handleLevel(rms: rms)
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
        } catch {
            inputNode.removeTap(onBus: 0)
            task?.cancel()
            task = nil
            requestBox.clear()
            errorMessage = "Couldn't start audio engine: \(error.localizedDescription)"
            onFinished(nil)
        }
    }

    /// Starts (or restarts) the recognizer on the live audio. Each stretch has its own id so a late callback from an
    /// earlier one can't be mistaken for the current one.
    private func startSegment() {
        segmentID += 1
        let id = segmentID
        segmentText = ""
        segmentStartedAt = Date()
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.addsPunctuation = true
        requestBox.set(request)
        task = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            // Plain values only: this callback arrives on a background queue.
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            let failure = error as NSError?
            Task { @MainActor in self?.handleRecognition(id: id, text: text, isFinal: isFinal, failure: failure) }
        }
    }

    private func handleRecognition(id: Int, text: String?, isFinal: Bool, failure: NSError?) {
        guard id == segmentID, !didDeliver else { return }
        if let text {
            segmentText = text
            transcript = joinedTranscript
        }
        guard isFinal || failure != nil else { return }

        if stopRequested {  // we asked it to finish (tap / pause): this is the end of the last stretch
            // Ending a conversation stops the recognizer on a fresh, empty turn, and Apple answers "No speech detected": expected,
            // not an error (it turned the orb orange every time a conversation ended, 2026-11-14).
            if let failure, joinedTranscript.isEmpty, !endedConversation { errorMessage = "Recognition error: \(failure.localizedDescription)" }
            finishAndDeliver()
            return
        }

        // The recognizer ended this stretch by itself while we're still listening. Keep what it heard and carry on, unless
        // it keeps failing straight away (no network, speech service down): then say so and send what there is.
        let lastedLongEnough = Date().timeIntervalSince(segmentStartedAt) > 1.0
        if recognizerRestarts >= maxRestarts || (failure != nil && !lastedLongEnough) {
            if let failure { errorMessage = "Recognition error: \(failure.localizedDescription)" }
            if isInConversation {
                endConversation(note: errorMessage ?? "Apple's recognizer kept stopping, so I ended the conversation.")
                return
            }
            stop(note: nil)
            finishAndDeliver()
            return
        }
        committedText = joinedTranscript
        dropWords = 0
        segmentText = ""
        recognizerRestarts += 1
        startSegment()
    }

    private func handleLevel(rms: Double) {
        guard isListening else { return }
        if isInConversation {
            handleConversationLevel(rms: rms)
            return
        }
        let elapsed = Date().timeIntervalSince(recordingStartedAt)
        guard let reason = endpointer.feed(rms: rms, elapsed: elapsed, transcript: transcript) else { return }
        switch reason {
        case .pause(let seconds): stop(note: "Stopped after a \(String(format: "%g", seconds)) s pause.")
        case .noSpeech: stop(note: "Didn't hear anything, so I stopped.")
        case .timeLimit: stop(note: "Hit the 60-second limit.")
        }
    }

    private func stop(note: String?) {
        guard isListening else { return }
        stopRequested = true
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        requestBox.endAudio()
        isListening = false
        audioLevel = 0
        setStopNote(note)
        Self.conversationHoldsAudioSession = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            await MainActor.run { self.finishAndDeliver() }
        }
    }

    private func setStopNote(_ note: String?) {
        var text = note
        if recognizerRestarts > 0 {
            text = (text.map { $0 + " " } ?? "") + "(Apple's recognizer ended \(recognizerRestarts) time\(recognizerRestarts == 1 ? "" : "s") by itself; I kept listening.)"
        }
        lastStopNote = text
        guard let text else { return }
        Task {
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await MainActor.run { if self.lastStopNote == text { self.lastStopNote = nil } }
        }
    }

    private func finishAndDeliver() {
        guard !didDeliver else { return }
        didDeliver = true

        task = nil
        requestBox.clear()
        let callback = onFinishedCallback
        onFinishedCallback = nil

        let finalTranscript = joinedTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        transcript = finalTranscript
        callback?(finalTranscript.isEmpty ? nil : finalTranscript)
    }
}

/// The audio tap runs on a real-time audio thread; the recognition request is swapped when a new stretch starts. This
/// holds the current request behind a lock so the tap can append to it from any thread.
private final class RecognitionRequestBox: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func set(_ new: SFSpeechAudioBufferRecognitionRequest) {
        lock.lock(); defer { lock.unlock() }
        request?.endAudio()  // the stretch being replaced is over
        request = new
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); defer { lock.unlock() }
        request?.append(buffer)
    }

    func endAudio() {
        lock.lock(); defer { lock.unlock() }
        request?.endAudio()
    }

    func clear() {
        lock.lock(); defer { lock.unlock() }
        request = nil
    }
}
