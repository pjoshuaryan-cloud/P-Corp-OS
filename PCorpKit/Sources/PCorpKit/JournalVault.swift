import CryptoKit
import Foundation
import LocalAuthentication

/// The private journal on one device (2026-11-07): setting it up, unlocking it with Face ID or Touch ID, keeping it open only while he's using
/// it, and reading and writing his notes. The key is in memory only while it's open, and the notes are decrypted only into memory: locking
/// forgets both. Nothing here is shared with Frank, and nothing leaves the device unsealed.
@MainActor
public final class JournalVault: ObservableObject {
    public enum Phase: Equatable {
        case checking
        /// No journal anywhere yet.
        case fresh
        /// A journal exists, but this device hasn't got its key: enter the recovery key, or scan it from the Mac.
        case elsewhere
        /// A new journal's recovery key, shown once before anything else.
        case writeDown(String)
        case locked
        case open
        /// No key here, and no signal to find out whether a journal exists.
        case offline
    }

    @Published public private(set) var phase: Phase = .checking
    @Published public private(set) var entries: [JournalEntry] = []
    @Published public private(set) var categories: [String] = JournalDefaults.categories
    @Published public private(set) var syncNote: String?
    @Published public private(set) var busy = false
    /// While Face ID or Touch ID is asking. The prompt takes focus, which mustn't count as leaving the journal.
    @Published public private(set) var authenticating = false
    @Published public var message: String?
    /// A quiet word about something that went right, like where a note was filed.
    @Published public var notice: String?
    /// Highlights his Mac wrote, by period name, decrypted into memory only while the journal is open.
    @Published public private(set) var stored: [String: JournalHighlight] = [:]
    /// Periods the Mac is writing a summary for right now.
    @Published public private(set) var writingHighlights: Set<String> = []
    private var digests: [String: JournalDigest] = [:]

    /// Locks itself after this long without being touched.
    public static let autoLock: TimeInterval = 5 * 60

    /// False from starting a journal until he says he's written its recovery key down, so leaving the app part-way (to write it down, say)
    /// brings him back to it rather than past it. Only a yes or no; nothing about the journal.
    private static let confirmedFlag = "journal.recoveryKeyWrittenDown"
    private var recoveryKeyUnconfirmed: Bool {
        get { UserDefaults.standard.object(forKey: Self.confirmedFlag) as? Bool == false }
        set { if newValue { UserDefaults.standard.set(false, forKey: Self.confirmedFlag) } else { UserDefaults.standard.removeObject(forKey: Self.confirmedFlag) } }
    }

    private var key: SymmetricKey?
    private var lastTouched = Date()
    private var lockWatch: Task<Void, Never>?
    private let engine: JournalEngine
    private let transport: JournalTransport
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    public init(folder: URL = JournalVault.defaultFolder, transport: JournalTransport = JournalHTTP()) {
        self.transport = transport
        engine = JournalEngine(folder: folder, transport: transport)
    }

    nonisolated public static var defaultFolder: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("P Corp Journal", isDirectory: true)
    }

    // ---- getting in

    public func load() async {
        message = nil
        if key != nil { phase = .open; return }
        if JournalKeychain.hasKey() { phase = .locked; return }
        do {
            phase = try await transport.state() == nil ? .fresh : .elsewhere
        } catch {
            phase = .offline
        }
    }

    /// Starts a journal: a new key, registered with the server first so a second device can't start one of its own, then kept in this device's Keychain.
    public func start() async {
        busy = true
        defer { busy = false }
        let newKey = JournalCrypto.newKey()
        do {
            if try await transport.setUp(keyCheck: JournalCrypto.keyCheck(newKey)) == .otherKey {
                phase = .elsewhere
                message = "You already have a journal. Enter its recovery key to open it here."
                return
            }
            try JournalKeychain.store(newKey)
        } catch {
            message = "It needs signal to start. Try again when there's some."
            return
        }
        // Anything already in this device's folder belongs to an older journal whose key is gone: unreadable, and its record of versions
        // would stop this one taking in the other device's changes.
        try? await engine.wipe()
        recoveryKeyUnconfirmed = true
        key = newKey
        touch()
        phase = .writeDown(JournalCrypto.recoveryCode(for: newKey))
    }

    public func wroteItDown() async {
        guard key != nil else { phase = .locked; return }
        recoveryKeyUnconfirmed = false
        await opened()
    }

    /// Opens the journal on this device with its recovery key, typed in or scanned from the Mac.
    public func restore(code: String) async {
        busy = true
        defer { busy = false }
        let found: SymmetricKey
        do {
            found = try JournalCrypto.key(fromRecoveryCode: code)
        } catch {
            message = "That recovery key isn't right. Check each group of five."
            return
        }
        do {
            let stored = try await transport.state()
            if stored == nil {
                guard try await transport.setUp(keyCheck: JournalCrypto.keyCheck(found)) == .ok else {
                    message = "That recovery key doesn't match your journal."
                    return
                }
            } else if stored != JournalCrypto.keyCheck(found) {
                message = "That recovery key doesn't match your journal."
                return
            }
            try JournalKeychain.store(found)
        } catch {
            message = "It needs signal to check the recovery key. Try again when there's some."
            return
        }
        recoveryKeyUnconfirmed = false
        key = found
        await opened()
    }

    public func unlock() async {
        message = nil
        authenticating = true
        let check = await JournalAuth.check(reason: "Open your private journal")
        authenticating = false
        guard JournalAuth.passed(check) else { return }
        let found: SymmetricKey
        do {
            found = try JournalKeychain.load(using: check)
        } catch {
            message = "This device's key is missing. Enter your recovery key to open the journal here."
            phase = .elsewhere
            return
        }
        key = found
        if recoveryKeyUnconfirmed {
            touch()
            phase = .writeDown(JournalCrypto.recoveryCode(for: found))
            return
        }
        await opened()
    }

    private func opened() async {
        phase = .open
        touch()
        await readAll()
        await refresh()
        JournalReminders.apply()
        await tidyHighlights()
    }

    /// Forgets the key and every decrypted note. What's saved stays saved, sealed.
    public func lock() {
        lockWatch?.cancel()
        lockWatch = nil
        key = nil
        entries = []
        stored = [:]
        digests = [:]
        message = nil
        notice = nil
        JournalSorter.forget()
        if phase == .open || { if case .writeDown = phase { return true } else { return false } }() {
            phase = JournalKeychain.hasKey() ? .locked : .elsewhere
        }
    }

    /// Something he did, so the five minutes start again.
    public func touch() {
        lastTouched = Date()
        guard lockWatch == nil, key != nil else { return }
        lockWatch = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                guard let self else { return }
                if Date().timeIntervalSince(self.lastTouched) >= Self.autoLock {
                    self.lock()
                    return
                }
            }
        }
    }

    public var isOpen: Bool { key != nil && phase == .open }

    // ---- reading and writing

    private func readAll() async {
        guard let key else { return }
        var found: [JournalEntry] = []
        for id in await engine.entryIDs() {
            guard let sealed = await engine.sealed(id), let plain = try? JournalCrypto.open(sealed, id: id, key: key), let entry = try? decoder.decode(JournalEntry.self, from: plain) else { continue }
            found.append(entry)
        }
        entries = found.sorted { $0.createdAt > $1.createdAt }
        var highlights: [String: JournalHighlight] = [:]
        for id in await engine.ids(prefix: "h-") {
            guard let sealed = await engine.sealed(id), let plain = try? JournalCrypto.open(sealed, id: id, key: key), let h = try? decoder.decode(JournalHighlight.self, from: plain) else { continue }
            highlights[id] = h
        }
        stored = highlights
        if let sealed = await engine.sealed(JournalDefaults.categoriesID), let plain = try? JournalCrypto.open(sealed, id: JournalDefaults.categoriesID, key: key), let list = try? decoder.decode(JournalCategoryList.self, from: plain), !list.names.isEmpty {
            categories = list.names
        } else {
            categories = JournalDefaults.categories
        }
    }

    /// Sends what's waiting and takes in the other device's changes.
    public func refresh() async {
        guard key != nil else { return }
        do {
            _ = try await engine.sync()
            syncNote = nil
        } catch {
            syncNote = await engine.pendingCount > 0 ? "Saved on this device. It goes to your other device when there's signal." : "No signal. Showing what's on this device."
        }
        await readAll()
    }

    private func keep(_ id: String, _ plain: Data) async throws {
        guard let key else { throw JournalKeychain.Failure.missing }
        try await engine.save(id, sealed: try JournalCrypto.seal(plain, id: id, key: key))
    }

    /// Saves a note. With `sort`, it's filed first by what it says, on this device (JournalSorter).
    public func save(_ entry: JournalEntry, sort: Bool = false) async {
        touch()
        var changed = entry
        if sort {
            changed.category = await JournalSorter.category(for: changed.words, categories: categories, history: entries.filter { $0.id != entry.id })
            notice = "Filed under \(changed.category). Tap the note to move it."
        }
        changed.updatedAt = Date()
        do {
            try await keep(changed.id, try encoder.encode(changed))
        } catch {
            message = "That couldn't be saved."
            return
        }
        entries.removeAll { $0.id == changed.id }
        entries.insert(changed, at: 0)
        entries.sort { $0.createdAt > $1.createdAt }
        await refresh()
    }

    /// A voice note: its words worked out on this device, its recording sealed, and the temporary file deleted whatever happens.
    /// A nil category files it by what was said.
    public func addVoiceNote(file: URL, duration: TimeInterval, category: String?, title: String) async {
        touch()
        busy = true
        defer {
            JournalRecorder.discard(file)
            busy = false
        }
        let words = await JournalTranscriber.transcribe(file)
        guard let audio = try? Data(contentsOf: file) else {
            message = "The recording couldn't be read."
            return
        }
        let audioID = JournalEntry.newID(prefix: "a")
        do {
            try await keep(audioID, audio)
        } catch {
            message = "The recording couldn't be saved."
            return
        }
        await save(JournalEntry(category: category ?? categories.first ?? "Notes to self", title: title, transcript: words, audioID: audioID, duration: duration), sort: category == nil)
    }

    public func delete(_ entry: JournalEntry) async {
        touch()
        do {
            try await engine.remove(entry.id)
            if let audioID = entry.audioID { try await engine.remove(audioID) }
        } catch {
            message = "That couldn't be deleted."
            return
        }
        entries.removeAll { $0.id == entry.id }
        // A summary that drew on a deleted note goes too, so nothing of it is left. The Mac writes a fresh one from what's left.
        for h in stored.values where entry.createdAt >= h.start && entry.createdAt < h.end {
            try? await engine.remove(h.id)
            stored[h.id] = nil
        }
        await refresh()
    }

    // ---- highlights

    public func notes(in period: JournalPeriod) -> [JournalEntry] {
        entries.filter { period.contains($0.createdAt) }
    }

    /// What a period's notes add up to, counted on this device. Kept until a note in it changes.
    public func digest(_ period: JournalPeriod) -> JournalDigest {
        let notes = notes(in: period)
        let basis = JournalDigest.basis(of: notes)
        if let known = digests[period.id], known.basis == basis { return known }
        let made = JournalDigest.make(notes)
        digests[period.id] = made
        return made
    }

    /// The Mac's written highlight for a period, only while it still matches the notes in it.
    public func written(_ period: JournalPeriod) -> JournalHighlight? {
        guard let h = stored[period.id], h.basis == JournalDigest.basis(of: notes(in: period)) else { return nil }
        return h
    }

    /// Finished weeks or months that have notes in them, newest first.
    public func periods(_ kind: JournalPeriod.Kind, now: Date = Date()) -> [JournalPeriod] {
        guard let earliest = entries.map(\.createdAt).min() else { return [] }
        var found: [JournalPeriod] = []
        var period = JournalPeriod.latest(kind, before: now)
        var steps = 0
        while period.end > earliest && steps < 600 {
            if entries.contains(where: { period.contains($0.createdAt) }) { found.append(period) }
            period = period.previous()
            steps += 1
        }
        return found
    }

    /// Has the Mac's on-device model write a period's highlight, and keeps it sealed so the iPhone gets it too. Does nothing where there's
    /// no model, when there's already a current one, or when the period has no notes.
    public func writeHighlight(_ period: JournalPeriod) async {
        guard key != nil, JournalModel.available, written(period) == nil, !writingHighlights.contains(period.id) else { return }
        let notes = notes(in: period)
        guard !notes.isEmpty else { return }
        let basis = JournalDigest.basis(of: notes)
        writingHighlights.insert(period.id)
        defer { writingHighlights.remove(period.id) }
        guard let made = await JournalModel.write(period, entries: notes) else { return }
        // Locked, or a note in the period changed, while it was writing: what it wrote isn't wanted.
        guard key != nil, JournalDigest.basis(of: self.notes(in: period)) == basis else { return }
        let highlight = JournalHighlight(id: period.id, kind: period.kind, start: period.start, end: period.end, basis: basis, writtenAt: Date(), summary: made.summary, remember: made.remember)
        do {
            try await keep(highlight.id, try encoder.encode(highlight))
        } catch {
            return
        }
        stored[highlight.id] = highlight
        await refresh()
    }

    /// Highlights of periods whose notes are all gone are deleted, and the Mac writes the latest week's and month's.
    private func tidyHighlights() async {
        for h in stored.values where notes(in: JournalPeriod(kind: h.kind, start: h.start, end: h.end)).isEmpty {
            try? await engine.remove(h.id)
            stored[h.id] = nil
        }
        guard JournalModel.available else { return }
        for kind in [JournalPeriod.Kind.week, .month] {
            if let latest = periods(kind).first { await writeHighlight(latest) }
        }
    }

    /// A voice note's recording, decrypted into memory only.
    public func audio(for entry: JournalEntry) async -> Data? {
        touch()
        guard let key, let id = entry.audioID else { return nil }
        guard let sealed = try? await engine.fetch(id) else {
            message = "That recording needs signal the first time it's played here."
            return nil
        }
        return try? JournalCrypto.open(sealed, id: id, key: key)
    }

    public func setCategories(_ names: [String]) async {
        touch()
        let cleaned = names.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        var unique: [String] = []
        for name in cleaned where !unique.contains(where: { $0.caseInsensitiveCompare(name) == .orderedSame }) { unique.append(name) }
        guard !unique.isEmpty else { return }
        do {
            try await keep(JournalDefaults.categoriesID, try encoder.encode(JournalCategoryList(names: unique)))
        } catch {
            message = "The categories couldn't be saved."
            return
        }
        categories = unique
        await refresh()
    }

    /// The recovery key, after asking for Face ID or Touch ID again.
    public func recoveryCode() async -> String? {
        touch()
        authenticating = true
        let check = await JournalAuth.check(reason: "Show your journal's recovery key")
        authenticating = false
        guard JournalAuth.passed(check), let found = try? JournalKeychain.load(using: check) else { return nil }
        return JournalCrypto.recoveryCode(for: found)
    }

    /// Takes the journal off this device only: its key and its sealed copies. Your other device and the server keep everything.
    public func forgetThisDevice() async {
        // This device's copy is the only copy of anything it hasn't sent yet, so it can't be removed until that's gone.
        await refresh()
        if await engine.pendingCount > 0 {
            message = "Some notes haven't reached your other device yet. Try again when there's signal, or they'd be lost."
            return
        }
        authenticating = true
        let check = await JournalAuth.check(reason: "Remove the journal from this device")
        authenticating = false
        guard JournalAuth.passed(check) else { return }
        lock()
        JournalKeychain.remove()
        recoveryKeyUnconfirmed = false
        try? await engine.wipe()
        phase = .elsewhere
    }
}
