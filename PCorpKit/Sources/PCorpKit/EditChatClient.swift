import Foundation

/// "Describe an edit" (Cinematic Reel Autopilot phase 6a, 2026-11-18): one sentence in the POST tab becomes a planned edit.
/// `understand` sends the sentence (one Haiku call, well under a cent) and gets back a card: which shoot, style, song and length, and each step with its
/// estimated cost against the cap ($1 unless the sentence says otherwise). Nothing else is spent until `run` (Josh's Go). The run never goes past the cap;
/// it ends with the plan saved, ready for Review Moments and Build My Edit in Premiere. Desktop-only for now (6b brings it to the phone through the cloud).
public struct EditChatStep: Decodable, Identifiable, Sendable {
    public let step: String
    public let what: String
    public let usd: Double
    public let state: String?
    public let spentUsd: Double?
    public let note: String?
    public var id: String { step }
}

public struct EditChatSong: Decodable, Sendable {
    public let name: String
    public let path: String
    public let matched: Bool?
}

public struct EditChatCard: Decodable, Sendable {
    public struct Job: Decodable, Sendable { public let id: Int; public let shootName: String? }
    public struct Style: Decodable, Sendable { public let slug: String; public let name: String; public let kind: String }
    public let id: String
    public let job: Job
    public let style: Style
    public let song: EditChatSong?
    public let seconds: Double?
    public let usdCap: Double
    public let steps: [EditChatStep]
    public let usdTotal: Double
    public let overCap: Bool
    public let ready: Bool
    public let warnings: [String]
}

public struct EditChatResult: Decodable, Sendable {
    public let shots: Int
    public let seconds: Double?
    public let style: String
    public let reviewPath: String
    public let blurMoves: Int?
}

public struct EditChatRun: Decodable, Sendable {
    public let state: String
    public let steps: [EditChatStep]
    public let spentUsd: Double
    public let message: String?
    public let result: EditChatResult?
    public var isRunning: Bool { state == "running" }
}

@MainActor
public final class EditChatClient: ObservableObject {
    @Published public private(set) var card: EditChatCard?
    @Published public private(set) var run: EditChatRun?
    @Published public private(set) var message: String?
    @Published public private(set) var errorMessage: String?
    @Published public private(set) var isUnderstanding = false

    public init() {}

    private struct ErrorDetail: Decodable { let detail: String }
    private struct UnderstandReply: Decodable { let card: EditChatCard?; let message: String?; let understandUsd: Double? }
    private struct RunReply: Decodable { let run: EditChatRun? }

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func call(_ method: String, _ path: String, body: [String: Any]? = nil, timeout: TimeInterval = 120) async -> (Data?, String?) {
        var request = URLRequest(url: BackendHost.url(path: path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                return (nil, (try? JSONDecoder().decode(ErrorDetail.self, from: data))?.detail ?? "Request failed (\(http.statusCode)).")
            }
            return (data, nil)
        } catch {
            return (nil, "Couldn't reach the backend — is it running?")
        }
    }

    /// Step 1: the sentence becomes a card (or a message saying what couldn't be told). Replaces any earlier card.
    public func understand(_ text: String) async {
        isUnderstanding = true
        errorMessage = nil
        message = nil
        card = nil
        run = nil
        defer { isUnderstanding = false }
        let (data, error) = await call("POST", "/post/edit-chat/understand", body: ["text": text])
        if let error { errorMessage = error; return }
        guard let data, let reply = try? Self.decoder.decode(UnderstandReply.self, from: data) else { errorMessage = "Couldn't read the reply."; return }
        card = reply.card
        message = reply.message
    }

    /// Step 2: Josh's Go. Starts the run, then follows it until it finishes.
    public func go() async {
        guard let card else { return }
        errorMessage = nil
        let (data, error) = await call("POST", "/post/edit-chat/run", body: ["card_id": card.id])
        if let error { errorMessage = error; return }
        if let data, let reply = try? Self.decoder.decode(RunReply.self, from: data) { run = reply.run }
        while run?.isRunning == true {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            await refreshRun()
        }
    }

    public func refreshRun() async {
        let (data, _) = await call("GET", "/post/edit-chat/run", timeout: 30)
        if let data, let reply = try? Self.decoder.decode(RunReply.self, from: data) { run = reply.run }
    }

    public func clear() {
        card = nil
        run = nil
        message = nil
        errorMessage = nil
    }
}
