import CryptoKit
import Foundation

/// One journal note, as only his devices ever see it: sealed with JournalCrypto before it's stored anywhere, here or on the server.
public struct JournalEntry: Codable, Identifiable, Equatable, Sendable {
    public var id: String
    public var createdAt: Date
    public var updatedAt: Date
    public var category: String
    public var title: String
    public var text: String
    /// What a voice note said, worked out on the device itself. Nil if it couldn't be, which never sends it anywhere else to try.
    public var transcript: String?
    public var audioID: String?
    public var duration: Double?

    public init(category: String, title: String = "", text: String = "", transcript: String? = nil, audioID: String? = nil, duration: Double? = nil, now: Date = Date()) {
        id = JournalEntry.newID(prefix: "e")
        createdAt = now
        updatedAt = now
        self.category = category
        self.title = title
        self.text = text
        self.transcript = transcript
        self.audioID = audioID
        self.duration = duration
    }

    public static func newID(prefix: String) -> String {
        prefix + "-" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    /// The words a list and a search go by: what he typed, then what he said.
    public var words: String {
        [title, text, transcript ?? ""].filter { !$0.isEmpty }.joined(separator: "\n")
    }

    public func matches(_ query: String) -> Bool {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return needle.isEmpty || words.range(of: needle, options: [.caseInsensitive, .diacriticInsensitive]) != nil || category.range(of: needle, options: .caseInsensitive) != nil
    }
}

public enum JournalDefaults {
    public static let categories = ["Notes to self", "Ideas", "Feelings", "Finance"]
    public static let categoriesID = "m-categories"
}

public struct JournalCategoryList: Codable, Equatable, Sendable {
    public var names: [String]
}

public struct JournalIndexItem: Decodable, Equatable, Sendable {
    public let id: String
    public let kind: String
    public let size: Int
    public let version: Int
    public let deleted: Bool
}

public enum JournalWriteResult: Equatable, Sendable {
    case saved(Int)
    case conflict(Int)
}

public enum JournalSetupResult: Equatable, Sendable {
    case ok
    case otherKey
}

/// How the journal reaches the server. A protocol so the sync can be tested without one.
public protocol JournalTransport: Sendable {
    func state() async throws -> String?
    func setUp(keyCheck: String) async throws -> JournalSetupResult
    func index() async throws -> [JournalIndexItem]
    func get(_ id: String) async throws -> Data?
    func put(_ id: String, data: Data, version: Int) async throws -> JournalWriteResult
    func delete(_ id: String, version: Int) async throws -> JournalWriteResult
}

/// The journal on one device: sealed copies of every item in a folder of its own, what's still to send, and the sync with the server. It never
/// holds the key, and never writes anything readable: callers seal before saving and open after reading. Changes made with no signal wait here
/// and go when there is some. When both devices change the same note, the last one sent wins.
public actor JournalEngine {
    struct Pending: Codable, Equatable {
        var id: String
        var delete: Bool
    }

    struct State: Codable {
        var versions: [String: Int] = [:]
        var deleted: Set<String> = []
        var outbox: [Pending] = []
    }

    public struct SyncReport: Equatable, Sendable {
        public var sent = 0
        public var received = 0
        public var removed = 0
    }

    private let folder: URL
    private let transport: JournalTransport
    private var state: State

    public init(folder: URL, transport: JournalTransport) {
        self.folder = folder
        self.transport = transport
        try? FileManager.default.createDirectory(at: folder.appendingPathComponent("items"), withIntermediateDirectories: true)
        if let data = try? Data(contentsOf: folder.appendingPathComponent("state.json")), let saved = try? JSONDecoder().decode(State.self, from: data) {
            state = saved
        } else {
            state = State()
        }
    }

    // ---- this device's copies

    private func path(_ id: String) -> URL {
        folder.appendingPathComponent("items").appendingPathComponent(id + ".sealed")
    }

    private func writeProtected(_ data: Data, to url: URL) throws {
        #if os(iOS)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        #else
        try data.write(to: url, options: .atomic)
        #endif
    }

    private func persist() throws {
        try writeProtected(try JSONEncoder().encode(state), to: folder.appendingPathComponent("state.json"))
    }

    public func sealed(_ id: String) -> Data? {
        try? Data(contentsOf: path(id))
    }

    public func entryIDs() -> [String] { ids(prefix: "e-") }

    /// The items kept here whose names start this way: "e-" notes, "h-" highlights.
    public func ids(prefix: String) -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.appendingPathComponent("items").path)) ?? []
        return names.filter { $0.hasPrefix(prefix) && $0.hasSuffix(".sealed") }.map { String($0.dropLast(".sealed".count)) }.filter { !state.deleted.contains($0) }
    }

    public var pendingCount: Int { state.outbox.count }

    /// Keeps a sealed item here and queues it for the server, as a newer version than any copy seen so far.
    public func save(_ id: String, sealed: Data) throws {
        try writeProtected(sealed, to: path(id))
        state.versions[id, default: 0] += 1
        state.deleted.remove(id)
        state.outbox.removeAll { $0.id == id }
        state.outbox.append(Pending(id: id, delete: false))
        try persist()
    }

    /// Removes an item here for good and queues its deletion.
    public func remove(_ id: String) throws {
        try? FileManager.default.removeItem(at: path(id))
        state.versions[id, default: 0] += 1
        state.deleted.insert(id)
        state.outbox.removeAll { $0.id == id }
        state.outbox.append(Pending(id: id, delete: true))
        try persist()
    }

    /// A sealed item, from here or, the first time it's wanted (a recording made on the other device), from the server.
    public func fetch(_ id: String) async throws -> Data? {
        if let here = sealed(id) { return here }
        guard !state.deleted.contains(id), let data = try await transport.get(id) else { return nil }
        try writeProtected(data, to: path(id))
        return data
    }

    /// Forgets everything on this device, for a device being taken off the journal. The server's copy is untouched.
    public func wipe() throws {
        try? FileManager.default.removeItem(at: folder)
        try FileManager.default.createDirectory(at: folder.appendingPathComponent("items"), withIntermediateDirectories: true)
        state = State()
    }

    // ---- the sync

    /// Sends what's waiting, then takes in what the other device changed. Notes and the category list come down straight away; a recording only when it's played.
    public func sync() async throws -> SyncReport {
        var report = SyncReport()
        // An item the server turns away (too big, or a kind an older server doesn't know yet) stays queued for next time, but doesn't hold
        // up everything queued behind it. No signal stops the whole sync, as before.
        var refused: [Pending] = []
        while let next = state.outbox.first(where: { !refused.contains($0) }) {
            do {
                try await send(next)
            } catch JournalHTTP.Failure.server(let status, _) where (400..<500).contains(status) && status != 401 && status != 403 {
                refused.append(next)
                continue
            }
            state.outbox.removeAll { $0 == next }
            try persist()
            report.sent += 1
        }
        for item in try await transport.index() {
            let known = state.versions[item.id] ?? 0
            guard item.version > known else { continue }
            if item.deleted {
                try? FileManager.default.removeItem(at: path(item.id))
                state.deleted.insert(item.id)
                report.removed += 1
            } else if item.kind == "audio" {
                try? FileManager.default.removeItem(at: path(item.id))   // fetched again when it's played
                state.deleted.remove(item.id)
            } else if let data = try await transport.get(item.id) {
                try writeProtected(data, to: path(item.id))
                state.deleted.remove(item.id)
                report.received += 1
            } else {
                continue
            }
            state.versions[item.id] = item.version
            try persist()
        }
        if !refused.isEmpty { throw SyncFailure.refused }
        return report
    }

    public enum SyncFailure: Error, Equatable {
        case keptChanging
        /// The server turned something away. It's still kept here and queued.
        case refused
    }

    private func send(_ pending: Pending) async throws {
        var version = state.versions[pending.id] ?? 1
        for _ in 0..<3 {
            let result: JournalWriteResult
            if pending.delete {
                result = try await transport.delete(pending.id, version: version)
            } else {
                guard let data = sealed(pending.id) else { return }   // removed here since: its deletion is queued after it
                result = try await transport.put(pending.id, data: data, version: version)
            }
            switch result {
            case .saved(let stored):
                state.versions[pending.id] = stored
                return
            case .conflict(let stored):
                version = stored + 1   // the other device changed it too: this, the later change, wins
                state.versions[pending.id] = version
            }
        }
        throw SyncFailure.keptChanging   // stays queued for the next sync rather than being dropped
    }
}
