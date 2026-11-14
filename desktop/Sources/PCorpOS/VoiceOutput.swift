import AVFoundation
import Foundation
import PCorpKit

/// Text-to-speech for Frank's replies -- the output half of "talking to Frank," alongside VoiceInput.swift's input.
/// Confirmed decision (2026-07-28): only replies to a voice-triggered turn are spoken aloud, and Josh starting to talk
/// interrupts playback immediately, same as cutting off a person mid-sentence.
///
/// 2026-11-14, conversational voice: the reply is now spoken a sentence at a time WHILE Frank is still writing it (the queue,
/// prefetching and playback live in PCorpKit's ReplySpeaker, shared with the iPhone). Before, nothing played until the whole
/// reply was written, sent to ElevenLabs and downloaded. This class supplies the /speak call and the step-by-step error message.
///
/// Uses ElevenLabs (via the backend's `/speak` proxy, app/main.py) rather than on-device `AVSpeechSynthesizer` -- a real,
/// confirmed upgrade: "Tom (Enhanced)" is the only downloadable en-US male voice on this Mac and it read as robotic. The
/// API key stays server-side (backend/.env) -- this class only ever talks to the local backend, never to ElevenLabs directly.
@MainActor
final class VoiceOutput: ReplySpeaker {
    // Goes through the same shared builder every other client uses (2026-09-09), so an environment switch reaches this too.
    private var speakURL: URL { BackendHost.url(path: "/speak") }

    /// Speaks once the backend is actually answering requests, for a line spoken at launch (the greeting). The backend and the
    /// app start together at login (or the backend is restarted), and the backend takes ~25 s before it listens -- speaking
    /// straight away got "connection refused" and left an error on the orb for the whole session. `BackendClient.isConnected`
    /// can't be the signal: it turns true when the socket attempt STARTS, not when it succeeds (2026-10-15). Any HTTP reply to
    /// /health counts as answering (a 422 for a missing token still proves the server is up). If anything else speaks or stops
    /// in the meantime, the waiting greeting is dropped. After the timeout it speaks anyway so a real failure still surfaces.
    func speakWhenBackendReady(_ text: String, timeoutSeconds: Double = 120) {
        let startedGeneration = replyGeneration
        Task {
            let deadline = Date().addingTimeInterval(timeoutSeconds)
            while Date() < deadline {
                guard replyGeneration == startedGeneration else { return }
                if await Self.backendIsAnswering() { break }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
            guard replyGeneration == startedGeneration else { return }
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

    override func fetchAudio(for text: String) async throws -> Data {
        // Which step is running, so a failure says WHAT failed instead of one catch-all message (2026-10-13).
        var step = "building the request"
        do {
            var request = URLRequest(url: speakURL)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(["text": text])
            step = "contacting the backend"
            let (data, response) = try await URLSession.shared.data(for: request)
            step = "reading the backend's reply"
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw VoiceOutputError.badResponse((response as? HTTPURLResponse)?.statusCode)
            }
            return data
        } catch {
            throw VoiceFetchFailure(step: step, underlying: error)
        }
    }

    override func pieceFailed(_ error: Error, text: String) {
        let step = (error as? VoiceFetchFailure)?.step ?? "playing the audio"
        let underlying = (error as? VoiceFetchFailure)?.underlying ?? error
        let ns = underlying as NSError
        errorMessage = "Frank's voice failed while \(step): \(underlying.localizedDescription) (\(ns.domain) \(ns.code))"
        // NSError's description embeds the full request URL, which carries the auth token -- strip it before it touches disk.
        let safe = "\(underlying) | \(ns.domain) \(ns.code)".replacingOccurrences(of: #"token=[^&\s,")]*"#, with: "token=…", options: .regularExpression)
        Self.appendDebugLine("speak failed while \(step): \(safe) | host \(speakURL.host ?? "?"):\(speakURL.port ?? 0)")
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
}

private struct VoiceFetchFailure: Error, LocalizedError {
    let step: String
    let underlying: Error
    var errorDescription: String? { underlying.localizedDescription }
}

private enum VoiceOutputError: Error, LocalizedError {
    case badResponse(Int?)

    var errorDescription: String? {
        switch self {
        case .badResponse(let code): return "the backend answered \(code.map(String.init) ?? "with no HTTP status")"
        }
    }
}
