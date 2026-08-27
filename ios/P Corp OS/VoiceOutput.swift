import AVFoundation
import Combine
import Foundation
import PCorpKit

/// Text-to-speech for Frank's replies -- iOS parity port (2026-08-27) of
/// desktop's own VoiceOutput.swift. Same ElevenLabs-via-backend-proxy
/// design, same interrupt-on-new-recording behavior, same generation
/// counter guarding a superseded in-flight fetch from starting playback
/// late. AVFoundation is fully cross-platform (AVAudioPlayer works
/// identically on iOS), so this needed no real rework -- except the one
/// platform-specific fix below.
///
/// Real fix, not copied verbatim: desktop's `speakURL` hardcodes
/// "127.0.0.1" because the backend runs on the same Mac the app does. On
/// iOS the backend runs on Joshua's Mac, not the phone -- BackendClient.swift
/// (PCorpKit) already solves this exact problem for chat via
/// `BackendHost.host` (set to the Mac's Tailscale IP in P_Corp_OSApp.swift),
/// so this uses the same host rather than a hardcoded loopback address that
/// would silently fail on a real device.
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
        var components = URLComponents(string: "http://\(BackendHost.host):8731/speak")!
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

                // Real bug found live (2026-08-27): VoiceInput.swift leaves
                // the shared AVAudioSession's category set to `.record`
                // (for speech-recognition accuracy) even after it
                // deactivates the session -- category persists across
                // activate/deactivate, only activation itself toggles. A
                // `.record`-only category can't route audio output at
                // all, so playing straight into it here made play() a
                // silent no-op: no sound, and no completion delegate call
                // either since real playback never started -- leaving
                // isSpeaking stuck true forever and the UI pinned on the
                // full-screen "Speaking…" orb, permanently hiding the
                // chat thread underneath (including the reply text that
                // had, in fact, already arrived). Desktop never hit this
                // since macOS has no equivalent per-category output gate.
                try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: .duckOthers)
                try AVAudioSession.sharedInstance().setActive(true, options: .notifyOthersOnDeactivation)

                let newPlayer = try AVAudioPlayer(data: data)
                newPlayer.isMeteringEnabled = true
                newPlayer.delegate = self
                player = newPlayer
                guard newPlayer.play() else { throw VoiceOutputError.playbackFailed }
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
    case playbackFailed
}
