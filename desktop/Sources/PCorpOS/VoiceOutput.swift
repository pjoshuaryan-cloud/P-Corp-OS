import AVFoundation
import Foundation

/// Text-to-speech for Frank's replies -- the output half of "talking to
/// Frank," alongside VoiceInput.swift's push-to-talk input. Confirmed
/// decision (2026-07-28): only replies to a voice-triggered turn are
/// spoken aloud, and starting a new push-to-talk recording interrupts
/// playback immediately, same as cutting off a person mid-sentence.
///
/// Uses ElevenLabs (via the backend's `/speak` proxy, app/main.py) rather
/// than on-device `AVSpeechSynthesizer` -- a real, confirmed upgrade, not
/// the original scope. The original on-device version hit a genuine
/// ceiling: "Tom (Enhanced)" is the only downloadable en-US male voice on
/// this Mac, with no Premium tier available for it at all, and it still
/// read as robotic. Cloud TTS was flagged from the start as the fallback
/// if the on-device voice ever felt wrong once actually heard -- that
/// happened, so this is that upgrade, with its accepted real costs (a
/// paid ElevenLabs account, a network round-trip -- and its latency --
/// for every spoken reply) rather than something adopted casually.
///
/// The API key stays server-side (backend/.env, same pattern as
/// ANTHROPIC_API_KEY) -- this class only ever talks to the local backend,
/// never to ElevenLabs directly.
@MainActor
final class VoiceOutput: NSObject, ObservableObject {
    @Published private(set) var isSpeaking = false
    /// Real amplitude of what's actually playing right now, 0...1 -- feeds
    /// FrankOrb's shimmer while Frank talks. Stays 0 while a speak() call
    /// is waiting on the network (ElevenLabs generation + download take a
    /// real moment, unlike instant local synthesis) -- the orb still
    /// appears immediately, just calm until real audio actually starts.
    @Published private(set) var audioLevel: Double = 0
    /// Surfaced explicitly (same reasoning as VoiceInput.errorMessage) --
    /// otherwise ElevenLabs not being configured yet, or a real network
    /// failure, would look identical to Frank just staying silent.
    @Published private(set) var errorMessage: String?

    private var player: AVAudioPlayer?
    private var meterTask: Task<Void, Never>?
    private var fetchTask: Task<Void, Never>?
    /// Bumped on every speak()/stop() -- an in-flight network fetch from a
    /// superseded call checks this before touching state or starting
    /// playback, so a slow response that arrives after an interruption
    /// can't start speaking anyway.
    private var generation = 0

    private var speakURL: URL {
        var components = URLComponents(string: "http://127.0.0.1:8731/speak")!
        components.queryItems = [URLQueryItem(name: "token", value: AuthToken.current ?? "")]
        return components.url!
    }

    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        stop()
        generation += 1
        let thisGeneration = generation
        errorMessage = nil
        isSpeaking = true

        fetchTask = Task {
            do {
                var request = URLRequest(url: speakURL)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONEncoder().encode(["text": trimmed])

                let (data, response) = try await URLSession.shared.data(for: request)
                guard generation == thisGeneration else { return } // superseded while in flight

                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    throw VoiceOutputError.badResponse
                }

                let newPlayer = try AVAudioPlayer(data: data)
                newPlayer.isMeteringEnabled = true
                newPlayer.delegate = self
                player = newPlayer
                newPlayer.play()
                startMetering(generation: thisGeneration)
            } catch {
                guard generation == thisGeneration else { return }
                isSpeaking = false
                errorMessage = "Couldn't reach Frank's voice (ElevenLabs) — check backend/.env is configured and the backend is reachable."
            }
        }
    }

    /// Interrupts playback immediately -- confirmed decision: starting a
    /// new push-to-talk recording should cut Frank off mid-sentence rather
    /// than waiting for him to finish.
    func stop() {
        generation += 1
        fetchTask?.cancel()
        fetchTask = nil
        meterTask?.cancel()
        meterTask = nil
        player?.stop()
        player = nil
        isSpeaking = false
        audioLevel = 0
    }

    private func startMetering(generation: Int) {
        meterTask = Task {
            while !Task.isCancelled, self.generation == generation, let player, player.isPlaying {
                player.updateMeters()
                // averagePower is in decibels, roughly -160 (silence) to 0
                // (loudest) -- remapped to a 0...1 range FrankOrb expects,
                // same shape as the mic-RMS meter VoiceInput already uses.
                let db = Double(player.averagePower(forChannel: 0))
                self.audioLevel = max(0, min(1, (db + 50) / 50))
                try? await Task.sleep(nanoseconds: 50_000_000) // ~20fps
            }
        }
    }
}

extension VoiceOutput: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.isSpeaking = false
            self.audioLevel = 0
        }
    }
}

private enum VoiceOutputError: Error {
    case badResponse
}
