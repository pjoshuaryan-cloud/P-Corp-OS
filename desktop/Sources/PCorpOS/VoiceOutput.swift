import AVFoundation
import Foundation

/// Text-to-speech for Frank's replies -- the output half of "talking to
/// Frank," alongside VoiceInput.swift's push-to-talk input. Confirmed
/// decision (2026-07-28): only replies to a voice-triggered turn are
/// spoken aloud (typed conversations stay silent, same as before this
/// existed), and starting a new push-to-talk recording interrupts
/// playback immediately, same as cutting off a person mid-sentence.
///
/// Deliberately on-device (AVSpeechSynthesizer), not a cloud TTS API --
/// no new backend work, no network dependency, no per-request cost,
/// matching every other feature's local-first default (Speech,
/// EventKit/AppleScript, notifications). A cloud voice would sound more
/// natural/branded but is a real step up in scope (paid API, audio-
/// streaming plumbing that doesn't exist yet) -- worth revisiting only if
/// the on-device voice actually feels wrong once heard, not built
/// speculatively now.
///
/// Uses `write(_:toBufferCallback:)` rather than the simpler `speak(_:)`
/// specifically to get real PCM buffers to RMS-analyze -- `speak(_:)`
/// plays audio automatically but hands you nothing to react to, and
/// UI_GUIDELINES.md already flagged "shimmer driven by real audio once
/// Frank has an actual voice" as tracked-but-unbuildable until now. Since
/// `write` does NOT play audio itself (it's meant for offline rendering),
/// playback is done manually via a small AVAudioEngine graph -- the same
/// buffers that drive the meter are what's actually scheduled for
/// playback, so what you see is exactly what you hear.
@MainActor
final class VoiceOutput: ObservableObject {
    @Published private(set) var isSpeaking = false
    /// Real amplitude of what's actually playing right now, 0...1 -- feeds
    /// FrankOrb's shimmer while Frank talks, same pattern as VoiceInput's
    /// mic-level meter.
    @Published private(set) var audioLevel: Double = 0

    private let synthesizer = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var isEngineSetUp = false
    /// Bumped on every speak()/stop() -- buffers from a superseded
    /// utterance (already interrupted, or a newer speak() call) check this
    /// before touching published state or scheduling audio, so a stale
    /// in-flight buffer can't resurrect playback after an interruption.
    private var generation = 0

    /// Confirmed decision (2026-07-28): Frank's voice should be male.
    /// Checked this Mac directly (not assumed) -- every installed English
    /// voice is default quality, none Enhanced/Premium, and the earlier
    /// version of this fallback ignored gender entirely, which is exactly
    /// why it picked Samantha (female, the system default for en-US).
    /// Filters for gender == .male first, THEN ranks by quality within
    /// that -- getting gender right matters more than quality ranking
    /// here, since ranking by quality first (the previous bug) silently
    /// drops the gender requirement whenever no male voice happens to be
    /// top-ranked. Real ceiling worth naming: default-quality voices all
    /// sound synthetic no matter which one loads -- Enhanced/Premium (a
    /// real download via System Settings > Accessibility > Spoken Content)
    /// is what actually fixes "robotic," not voice selection logic; this
    /// picks the best of what's already on the machine and automatically
    /// prefers a better one the moment one is downloaded.
    private static let preferredVoice: AVSpeechSynthesisVoice? = {
        let englishVoices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("en") }
        let maleVoices = englishVoices.filter { $0.gender == .male }
        return maleVoices.first { $0.quality == .premium }
            ?? maleVoices.first { $0.quality == .enhanced }
            ?? maleVoices.first { $0.language == "en-US" }
            ?? maleVoices.first
            ?? AVSpeechSynthesisVoice(language: "en-US")
    }()

    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        stop()
        generation += 1
        let thisGeneration = generation
        isSpeaking = true

        let utterance = AVSpeechUtterance(string: trimmed)
        utterance.voice = Self.preferredVoice

        synthesizer.write(utterance) { [weak self] buffer in
            guard let self, let pcmBuffer = buffer as? AVAudioPCMBuffer else { return }

            if pcmBuffer.frameLength == 0 {
                // An empty buffer is AVSpeechSynthesizer's own signal that
                // this utterance is fully rendered -- nothing left to play.
                Task { @MainActor in
                    guard self.generation == thisGeneration else { return }
                    self.isSpeaking = false
                    self.audioLevel = 0
                }
                return
            }

            guard let channelData = pcmBuffer.floatChannelData?[0] else { return }
            let frameLength = Int(pcmBuffer.frameLength)
            var sum: Float = 0
            for i in 0..<frameLength { sum += channelData[i] * channelData[i] }
            let rms = Double(sqrt(sum / Float(frameLength)))

            Task { @MainActor in
                guard self.generation == thisGeneration else { return }
                self.audioLevel = min(rms * 6, 1.0)
                self.schedule(pcmBuffer, generation: thisGeneration)
            }
        }
    }

    /// Interrupts playback immediately -- confirmed decision: starting a
    /// new push-to-talk recording should cut Frank off mid-sentence rather
    /// than waiting for him to finish.
    func stop() {
        generation += 1
        player.stop()
        isSpeaking = false
        audioLevel = 0
    }

    private func schedule(_ buffer: AVAudioPCMBuffer, generation: Int) {
        guard self.generation == generation else { return }

        if !isEngineSetUp {
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: buffer.format)
            isEngineSetUp = true
        }
        if !engine.isRunning {
            try? engine.start()
        }
        player.scheduleBuffer(buffer)
        if !player.isPlaying {
            player.play()
        }
    }
}
