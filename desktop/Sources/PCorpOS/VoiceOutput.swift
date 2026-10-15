import AVFoundation
import Foundation
import PCorpKit

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

    // Real gap found in Infrastructure Independence Stage 1 (2026-09-09):
    // this hardcoded 127.0.0.1 directly, bypassing BackendHost entirely --
    // harmless only because desktop's .local default happened to equal
    // this literal. Now goes through the same shared builder every other
    // client uses, so an environment switch actually reaches this call
    // site too.
    private var speakURL: URL { BackendHost.url(path: "/speak") }

    /// Speaks once the backend is actually answering requests, for a line spoken at launch (the greeting). The backend and the
    /// app start together at login (or the backend is restarted), and the backend takes ~25 s before it listens -- speaking
    /// straight away got "connection refused" and left an error on the orb for the whole session. `BackendClient.isConnected`
    /// can't be the signal: it turns true when the socket attempt STARTS, not when it succeeds (2026-10-15). Any HTTP reply to
    /// /health counts as answering (a 422 for a missing token still proves the server is up). If anything else speaks or stops
    /// in the meantime, the waiting greeting is dropped. After the timeout it speaks anyway so a real failure still surfaces.
    func speakWhenBackendReady(_ text: String, timeoutSeconds: Double = 120) {
        let startedGeneration = generation
        Task {
            let deadline = Date().addingTimeInterval(timeoutSeconds)
            while Date() < deadline {
                guard generation == startedGeneration else { return }
                if await Self.backendIsAnswering() { break }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
            guard generation == startedGeneration else { return }
            speak(text)
        }
    }

    private static func backendIsAnswering() async -> Bool {
        var request = URLRequest(url: BackendHost.url(path: "/health"))
        request.timeoutInterval = 3
        do {
            _ = try await URLSession.shared.data(for: request)
            return true
        } catch {
            return false
        }
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
            // Which step is running, so a failure says WHAT failed instead of one catch-all message (2026-10-13: the
            // old message always blamed ElevenLabs/the backend, even though the backend answered every request it
            // received fine -- the failure was somewhere inside this app and the message hid where).
            var step = "building the request"
            do {
                var request = URLRequest(url: speakURL)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONEncoder().encode(["text": trimmed])

                step = "contacting the backend"
                let (data, response) = try await URLSession.shared.data(for: request)
                guard generation == thisGeneration else { return } // superseded while in flight

                step = "reading the backend's reply"
                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    throw VoiceOutputError.badResponse((response as? HTTPURLResponse)?.statusCode)
                }

                step = "decoding the audio (\(data.count) bytes)"
                let newPlayer = try AVAudioPlayer(data: data)
                newPlayer.isMeteringEnabled = true
                newPlayer.delegate = self
                player = newPlayer
                step = "starting playback"
                guard newPlayer.play() else { throw VoiceOutputError.playbackRefused }
                startMetering(generation: thisGeneration)
            } catch {
                guard generation == thisGeneration else { return }
                isSpeaking = false
                let ns = error as NSError
                errorMessage = "Frank's voice failed while \(step): \(error.localizedDescription) (\(ns.domain) \(ns.code))"
                // NSError's description embeds the full request URL, which carries the auth token -- strip it before it touches disk.
                let safe = "\(error) | \(ns.domain) \(ns.code)".replacingOccurrences(of: #"token=[^&\s,")]*"#, with: "token=…", options: .regularExpression)
                Self.appendDebugLine("speak failed while \(step): \(safe) | host \(speakURL.host ?? "?"):\(speakURL.port ?? 0)")
            }
        }
    }

    /// A one-line trace in /tmp so a failure can be diagnosed after the fact (the unified log shows nothing for this app).
    private static func appendDebugLine(_ line: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        let data = Data("\(stamp) \(line)\n".utf8)
        let path = "/tmp/pcorp-voice-output.log"
        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            try? handle.close()
        } else {
            FileManager.default.createFile(atPath: path, contents: data)
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

private enum VoiceOutputError: Error, LocalizedError {
    case badResponse(Int?)
    case playbackRefused

    var errorDescription: String? {
        switch self {
        case .badResponse(let code): return "the backend answered \(code.map(String.init) ?? "with no HTTP status")"
        case .playbackRefused: return "the audio player refused to start"
        }
    }
}
