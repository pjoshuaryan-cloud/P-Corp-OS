import AVFoundation
import Combine
import Foundation
import PCorpKit

/// Text-to-speech for Frank's replies -- iOS parity port (2026-08-27) of desktop's own VoiceOutput.swift. Same
/// ElevenLabs-via-backend-proxy design and the same interrupt-on-new-recording behavior.
///
/// 2026-11-14, conversational voice: the reply is spoken a sentence at a time WHILE Frank is still writing it. The queue,
/// prefetching and playback live in PCorpKit's ReplySpeaker, shared with the Mac; this class supplies the /speak call and the
/// iPhone's audio session.
///
/// The URL goes through BackendHost (PCorpKit), never a hardcoded loopback address: on the iPhone the backend is the Mac (over
/// Tailscale) or Render, not the phone.
@MainActor
final class VoiceOutput: ReplySpeaker {
    private var speakURL: URL { BackendHost.url(path: "/speak") }

    override func fetchAudio(for text: String) async throws -> Data {
        var request = URLRequest(url: speakURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["text": text])
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw VoiceOutputError.badResponse
        }
        return data
    }

    override func preparePlayback() throws {
        // A conversation already holds the session in call mode (.playAndRecord / .voiceChat, VoiceInput) so the mic keeps
        // listening while Frank speaks; switching to playback-only here would cut the mic off.
        guard !VoiceInput.conversationHoldsAudioSession else { return }
        // Real bug found live (2026-08-27): VoiceInput leaves the shared AVAudioSession's category set to `.record` after a
        // push-to-talk recording, and an AVAudioPlayer can't play in that category. Set playback explicitly every time.
        try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: .duckOthers)
        try AVAudioSession.sharedInstance().setActive(true, options: .notifyOthersOnDeactivation)
    }

    override func pieceFailed(_ error: Error, text: String) {
        errorMessage = "Couldn't reach Frank's voice (ElevenLabs) — check backend/.env is configured and the backend is reachable."
    }
}

private enum VoiceOutputError: Error {
    case badResponse
}
