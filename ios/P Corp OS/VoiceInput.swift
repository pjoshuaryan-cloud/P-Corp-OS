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

    private var joinedTranscript: String {
        [committedText, segmentText].filter { !$0.isEmpty }.joined(separator: " ")
    }

    func toggle(onFinished: @escaping (String?) -> Void) {
        if isListening {
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
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            errorMessage = "Couldn't configure audio session: \(error.localizedDescription)"
            onFinished(nil)
            return
        }

        onFinishedCallback = onFinished
        didDeliver = false
        stopRequested = false
        endpointer = VoiceEndpointer()
        recordingStartedAt = Date()
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
            if let failure, joinedTranscript.isEmpty { errorMessage = "Recognition error: \(failure.localizedDescription)" }
            finishAndDeliver()
            return
        }

        // The recognizer ended this stretch by itself while we're still listening. Keep what it heard and carry on, unless
        // it keeps failing straight away (no network, speech service down): then say so and send what there is.
        let lastedLongEnough = Date().timeIntervalSince(segmentStartedAt) > 1.0
        if recognizerRestarts >= maxRestarts || (failure != nil && !lastedLongEnough) {
            if let failure { errorMessage = "Recognition error: \(failure.localizedDescription)" }
            stop(note: nil)
            finishAndDeliver()
            return
        }
        committedText = joinedTranscript
        segmentText = ""
        recognizerRestarts += 1
        startSegment()
    }

    private func handleLevel(rms: Double) {
        guard isListening else { return }
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
