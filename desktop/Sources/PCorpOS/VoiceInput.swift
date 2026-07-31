import AVFoundation
import Foundation
import Speech

/// Push-to-talk speech-to-text — click once to start listening; stops on
/// its own once you stop talking (see trackVoiceActivity below), or can
/// still be stopped manually by clicking again. Confirmed decision
/// (2026-07-28): push-to-talk, not continuous/always-listening — the mic
/// is only ever active while deliberately triggered, a much smaller
/// privacy footprint than an always-on microphone. Auto-stop-on-silence
/// was added the same day, after live use: requiring a second click to
/// end every single turn felt like unnecessary friction once the click-
/// to-start privacy boundary was already in place — the mic being
/// deliberately triggered is what matters, not requiring a second
/// deliberate action to end it too.
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

    /// Auto-stop-on-silence bookkeeping. `hasDetectedSpeech` gates the
    /// silence check so it can never fire before you've actually started
    /// talking — otherwise it'd stop instantly on the silence between
    /// clicking the mic and beginning to speak.
    private var hasDetectedSpeech = false
    private var lastVoiceActivityAt = Date()
    private var recordingStartedAt = Date()
    /// Set from a real logged recording (2026-07-30, via os_log/Logger —
    /// plain print() was silently discarded since this GUI app's stdout
    /// goes to /dev/null once activated): actual speech on Joshua's setup
    /// peaked at only ~0.005 RMS, well under the original 0.015 guess, so
    /// hasDetectedSpeech never became true and auto-stop never fired at
    /// all -- not a logic bug, just a threshold set before any real data
    /// existed. 0.002 sits between that observed ~0.0005-0.001 ambient
    /// floor and the ~0.005 speech peak.
    private let voiceActivityThreshold: Double = 0.002
    private let silenceDuration: TimeInterval = 1.2
    /// Safety net now that there's no manual "click to stop" requirement
    /// — caps how long the mic can stay open if silence is never cleanly
    /// detected (e.g. sustained background noise), rather than leaving it
    /// open indefinitely.
    private let maxRecordingDuration: TimeInterval = 60

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
        hasDetectedSpeech = false
        let now = Date()
        lastVoiceActivityAt = now
        recordingStartedAt = now

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request

        let inputNode = audioEngine.inputNode
        // Pin capture to the built-in mic specifically, regardless of
        // whatever the system's current default input is -- confirmed
        // decision (2026-07-30): recognition accuracy was noticeably
        // worse over AirPods, a real Bluetooth HFP bandwidth limitation
        // (see BuiltInMicSelector.swift), not something fixable by
        // tuning this app's own code. Output (VoiceOutput's TTS) is
        // untouched by this -- it keeps playing through AirPods/whatever
        // is connected, since only capture quality was the problem.
        // Must happen before reading outputFormat below, since the
        // format depends on which device is actually selected.
        if let builtInMic = BuiltInMicSelector.builtInInputDeviceID(),
           let audioUnit = inputNode.audioUnit {
            BuiltInMicSelector.setInputDevice(builtInMic, on: audioUnit)
        }
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
                self?.trackVoiceActivity(rawRMS: rms)
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

    /// Runs on every audio buffer (~roughly every 20-30ms) while listening.
    /// Auto-stops once real speech has been heard AND then gone quiet for
    /// `silenceDuration` — `hasDetectedSpeech` is what prevents this from
    /// firing during the silence before you've started talking at all.
    /// Also enforces `maxRecordingDuration` regardless, as a safety net.
    private func trackVoiceActivity(rawRMS: Double) {
        guard isListening else { return }
        let now = Date()

        if rawRMS > voiceActivityThreshold {
            hasDetectedSpeech = true
            lastVoiceActivityAt = now
        }

        if hasDetectedSpeech, now.timeIntervalSince(lastVoiceActivityAt) > silenceDuration {
            stop()
            return
        }
        if now.timeIntervalSince(recordingStartedAt) > maxRecordingDuration {
            stop()
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
