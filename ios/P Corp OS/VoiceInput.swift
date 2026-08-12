import AVFoundation
import Combine
import Foundation
import Speech

/// iOS port of desktop's VoiceInput.swift -- same push-to-talk design (tap
/// once to start, auto-stops on silence or after maxRecordingDuration, same
/// thresholds/timings carried over since they were tuned against real
/// recorded audio there). Drops desktop's BuiltInMicSelector step (that's
/// CoreAudio AudioObjectID plumbing, macOS-only -- iOS has no equivalent
/// concept of overriding the system's input route from within an app) and
/// adds an AVAudioSession activation, which desktop doesn't need but iOS
/// requires before AVAudioEngine will produce any input at all.
@MainActor
final class VoiceInput: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var transcript = ""
    @Published private(set) var audioLevel: Double = 0
    @Published private(set) var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var onFinishedCallback: ((String?) -> Void)?
    private var didDeliver = false

    private var hasDetectedSpeech = false
    private var lastVoiceActivityAt = Date()
    private var recordingStartedAt = Date()
    /// Same value as desktop's, carried over as the starting point -- not
    /// yet re-validated against a real recording on iPhone hardware/mic.
    private let voiceActivityThreshold: Double = 0.002
    private let silenceDuration: TimeInterval = 1.2
    private let maxRecordingDuration: TimeInterval = 60

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
        hasDetectedSpeech = false
        let now = Date()
        lastVoiceActivityAt = now
        recordingStartedAt = now

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
                self?.audioLevel = min(rms * 12, 1.0)
                self?.trackVoiceActivity(rawRMS: rms)
            }
        }

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
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

    private func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        isListening = false
        audioLevel = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

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
