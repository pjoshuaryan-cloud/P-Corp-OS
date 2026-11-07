import AVFoundation
import Foundation
import Speech

/// Records a voice note to a temporary file, which the journal seals and deletes straight after. Voice quality, mono, about 6 MB for half an hour.
@MainActor
public final class JournalRecorder: NSObject, ObservableObject {
    @Published public private(set) var isRecording = false
    @Published public private(set) var elapsed: TimeInterval = 0

    /// A note longer than this stops by itself, so a forgotten recording can't fill the server's room for recordings.
    public static let longest: TimeInterval = 30 * 60

    private var recorder: AVAudioRecorder?
    private var file: URL?
    private var ticker: Timer?

    public override init() {}

    /// Starts recording. Why it couldn't, or nil.
    public func start() async -> String? {
        guard await Self.microphoneAllowed() else { return "Microphone access is off. Turn it on for P Corp OS in Settings." }
        #if os(iOS)
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .spokenAudio, options: [.defaultToSpeaker])
            try session.setActive(true)
        } catch {
            return "The microphone couldn't start."
        }
        #endif
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("journal-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 44_100, AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 48_000]
        guard let recorder = try? AVAudioRecorder(url: url, settings: settings), recorder.record(forDuration: Self.longest) else {
            return "The recording couldn't start."
        }
        #if os(iOS)
        // Unreadable whenever the phone is locked, for the few minutes it exists. Locking the phone ends the recording anyway.
        try? (url as NSURL).setResourceValue(URLFileProtection.complete, forKey: .fileProtectionKey)
        #endif
        self.recorder = recorder
        file = url
        elapsed = 0
        isRecording = true
        ticker = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let recorder = self.recorder else { return }
                self.elapsed = recorder.currentTime
                if !recorder.isRecording { self.isRecording = false }
            }
        }
        return nil
    }

    /// Stops and hands over the file and its length. The caller seals it and calls discard.
    public func stop() -> (url: URL, duration: TimeInterval)? {
        guard let recorder, let file else { return nil }
        let duration = max(recorder.currentTime, elapsed)
        recorder.stop()
        finish()
        return (file, duration)
    }

    public func cancel() {
        recorder?.stop()
        if let file { Self.discard(file) }
        finish()
    }

    private func finish() {
        ticker?.invalidate()
        ticker = nil
        recorder = nil
        file = nil
        isRecording = false
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    public static func discard(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    /// Recordings left behind if the app was closed mid-note. Run before anything records, so it can't take one in progress.
    public static func clearLeftovers() {
        let temp = FileManager.default.temporaryDirectory
        let names = (try? FileManager.default.contentsOfDirectory(atPath: temp.path)) ?? []
        for name in names where name.hasPrefix("journal-") && name.hasSuffix(".m4a") {
            discard(temp.appendingPathComponent(name))
        }
    }

    private static func microphoneAllowed() async -> Bool {
        #if os(iOS)
        return await AVAudioApplication.requestRecordPermission()
        #else
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: .audio)
        default: return false
        }
        #endif
    }
}

/// Works out what a voice note said, on the device only. If this device can't do that, the note keeps its recording and no words: it's never sent anywhere else to transcribe.
public enum JournalTranscriber {
    public static func transcribe(_ url: URL) async -> String? {
        let allowed: Bool = await withCheckedContinuation { done in
            SFSpeechRecognizer.requestAuthorization { done.resume(returning: $0 == .authorized) }
        }
        guard allowed else { return nil }
        let candidates = [SFSpeechRecognizer(locale: Locale.current), SFSpeechRecognizer(locale: Locale(identifier: "en-US"))]
        guard let recognizer = candidates.compactMap({ $0 }).first(where: { $0.supportsOnDeviceRecognition && $0.isAvailable }) else { return nil }
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        request.addsPunctuation = true
        return await withCheckedContinuation { done in
            var finished = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !finished else { return }
                if let result, result.isFinal {
                    finished = true
                    let words = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                    done.resume(returning: words.isEmpty ? nil : words)
                } else if error != nil {
                    finished = true
                    done.resume(returning: nil)
                }
            }
        }
    }
}

/// Plays a voice note straight from memory, so the recording is never written out readable to play it.
@MainActor
public final class JournalPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published public private(set) var playingID: String?
    private var player: AVAudioPlayer?

    public override init() {}

    public func play(_ data: Data, id: String) {
        stop()
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        try? AVAudioSession.sharedInstance().setActive(true)
        #endif
        guard let player = try? AVAudioPlayer(data: data) else { return }
        player.delegate = self
        self.player = player
        player.play()
        playingID = id
    }

    public func stop() {
        player?.stop()
        player = nil
        playingID = nil
    }

    nonisolated public func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.stop() }
    }
}
