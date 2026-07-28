import AVFoundation
import Foundation
import Speech

/// Push-to-talk speech-to-text — click to start listening, click again to
/// stop and get the transcript. Confirmed decision (2026-07-28): push-to-
/// talk, not continuous/always-listening — the mic is only ever active
/// while deliberately triggered, a much smaller privacy footprint and far
/// less technical risk (no wake-word/voice-activity-detection needed) than
/// an always-on microphone.
///
/// Uses Speech + AVAudioEngine directly, both privacy-gated frameworks in
/// the same category as EventKit/UNUserNotificationCenter, which failed
/// outright on the earlier unbundled raw executable. Worth testing live
/// now that SMAppService packaging gives this app a real signed bundle —
/// that's the actual prerequisite these frameworks need, confirmed by that
/// earlier failure, not assumed to now "just work."
@MainActor
final class VoiceInput: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var transcript = ""
    /// Real microphone RMS level, 0...1 — feeds FrankOrb's shimmer while
    /// listening, replacing the synthetic sine wave for this state (the
    /// TODO already flagged in FrankOrb's own comments).
    @Published private(set) var audioLevel: Double = 0
    @Published private(set) var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var onFinishedCallback: ((String?) -> Void)?
    private var didDeliver = false

    /// Returns the final transcript once stopped, or nil if nothing was
    /// captured (e.g. permission denied, no speech).
    func toggle(onFinished: @escaping (String?) -> Void) {
        if isListening {
            stop()
        } else {
            start(onFinished: onFinished)
        }
    }

    private func start(onFinished: @escaping (String?) -> Void) {
        errorMessage = nil
        transcript = ""

        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            Task { @MainActor in
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "Speech recognition permission not granted."
                    onFinished(nil)
                    return
                }
                self.beginRecording(onFinished: onFinished)
            }
        }
    }

    private func beginRecording(onFinished: @escaping (String?) -> Void) {
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Speech recognizer unavailable right now."
            onFinished(nil)
            return
        }

        onFinishedCallback = onFinished
        didDeliver = false

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            request.append(buffer)
            guard let channelData = buffer.floatChannelData?[0] else { return }
            let frameLength = Int(buffer.frameLength)
            guard frameLength > 0 else { return }
            var sum: Float = 0
            for i in 0..<frameLength { sum += channelData[i] * channelData[i] }
            let rms = Double(sqrt(sum / Float(frameLength)))
            Task { @MainActor in
                // RMS on raw mic input is typically tiny (often < 0.05 even
                // for normal speech) — scaled up so it actually reads as
                // "reactive" in the UI rather than a barely-visible flicker.
                self?.audioLevel = min(rms * 12, 1.0)
            }
        }

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    // isFinal is the recognizer's own signal that it has
                    // finished processing all buffered audio and this is
                    // the definitive, most-accurate transcript — NOT just
                    // whatever partial result had arrived by the moment the
                    // user clicked stop. Deliver here, not synchronously in
                    // stop() (see that function's own comment for the real
                    // bug this fixes: cancelling the task immediately on
                    // stop was truncating real speech, e.g. a full sentence
                    // collapsing to "And it's so").
                    if result.isFinal {
                        self.finishAndDeliver()
                    }
                }
                if let error {
                    self.errorMessage = "Recognition error: \(error.localizedDescription)"
                    self.finishAndDeliver()
                }
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
        } catch {
            errorMessage = "Couldn't start audio engine: \(error.localizedDescription)"
            onFinished(nil)
        }
    }

    /// Stops CAPTURING new audio and tells the recognizer no more is coming
    /// — it does not cancel the recognition task. The task's own result
    /// handler (isFinal) is what actually delivers the transcript, once the
    /// recognizer finishes processing whatever audio is already buffered.
    /// A short safety timeout covers the case where isFinal never arrives.
    private func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        isListening = false
        audioLevel = 0

        Task {
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            await MainActor.run { self.finishAndDeliver() }
        }
    }

    private func finishAndDeliver() {
        guard !didDeliver else { return }
        didDeliver = true

        task = nil
        request = nil
        let callback = onFinishedCallback
        onFinishedCallback = nil

        let finalTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        callback?(finalTranscript.isEmpty ? nil : finalTranscript)
    }
}
