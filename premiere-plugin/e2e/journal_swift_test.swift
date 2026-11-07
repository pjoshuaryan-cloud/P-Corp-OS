// Tests for the journal's encryption and sync (PCorpKit JournalCrypto.swift, JournalStore.swift, JournalSecurity.swift's JournalHTTP). No test target exists in the package, so this
// compiles those files with a small runner (swiftc only allows top-level code in a file called main.swift, hence the copy). Two devices are two folders; the server is an
// in-memory stand-in with the backend's rules, and then, if JOURNAL_TEST_PORT is set, the real backend code on a throwaway server with a made-up token:
//   cd premiere-plugin/e2e && mkdir -p /tmp/journalswift && cp journal_swift_test.swift /tmp/journalswift/main.swift && cd ../../PCorpKit/Sources/PCorpKit && \
//   swiftc JournalCrypto.swift JournalStore.swift JournalSecurity.swift BackendHost.swift AuthToken.swift /tmp/journalswift/main.swift -o /tmp/journalswift/run && /tmp/journalswift/run
import CryptoKit
import Foundation

var fails = 0
func check(_ name: String, _ ok: Bool, _ detail: String = "") {
    print((ok ? "PASS " : "FAIL ") + name + (ok || detail.isEmpty ? "" : "   [\(detail)]"))
    if !ok { fails += 1 }
}

// ---- encryption
let key = JournalCrypto.newKey()
let other = JournalCrypto.newKey()
let note = Data("I want to build something that lasts.".utf8)
let sealed = try! JournalCrypto.seal(note, id: "e-1", key: key)
check("a sealed note doesn't contain its words", sealed.range(of: Data("lasts".utf8)) == nil)
check("it opens with its key and name", (try? JournalCrypto.open(sealed, id: "e-1", key: key)) == note)
check("not with another key", (try? JournalCrypto.open(sealed, id: "e-1", key: other)) == nil)
check("not passed off under another note's name", (try? JournalCrypto.open(sealed, id: "e-2", key: key)) == nil)
var tampered = sealed
tampered[tampered.count - 1] ^= 1
check("not if a single bit changed", (try? JournalCrypto.open(tampered, id: "e-1", key: key)) == nil)
check("sealing twice gives different bytes", (try! JournalCrypto.seal(note, id: "e-1", key: key)) != sealed)
check("the key check is the same every time for a key", JournalCrypto.keyCheck(key) == JournalCrypto.keyCheck(key) && JournalCrypto.keyCheck(key).count == 64)
check("and different for another key", JournalCrypto.keyCheck(key) != JournalCrypto.keyCheck(other))

// ---- the recovery key
let code = JournalCrypto.recoveryCode(for: key)
let groups = code.split(separator: "-")
check("the recovery key is groups of five", groups.count == 11 && groups.dropLast().allSatisfy { $0.count == 5 }, code)
check("in letters nobody misreads", !code.contains(where: { "ILOU".contains($0) }), code)
check("it gives back the same key", (try? JournalCrypto.key(fromRecoveryCode: code)).map { JournalCrypto.keyData($0) } == JournalCrypto.keyData(key))
check("typed in lower case with spaces", (try? JournalCrypto.key(fromRecoveryCode: code.lowercased().replacingOccurrences(of: "-", with: " "))).map { JournalCrypto.keyData($0) } == JournalCrypto.keyData(key))
check("with O typed for 0 and I for 1", code.contains("0") || code.contains("1") ? (try? JournalCrypto.key(fromRecoveryCode: code.replacingOccurrences(of: "0", with: "O").replacingOccurrences(of: "1", with: "I"))).map { JournalCrypto.keyData($0) } == JournalCrypto.keyData(key) : true)
var typo = Array(code)
let at = typo.firstIndex(where: { $0 != "-" })!
typo[at] = typo[at] == "A" ? "B" : "A"
check("a typo is caught, not turned into a wrong key", (try? JournalCrypto.key(fromRecoveryCode: String(typo))) == nil)
check("so is a missing group", (try? JournalCrypto.key(fromRecoveryCode: groups.dropLast().joined(separator: "-"))) == nil)
check("and nonsense", (try? JournalCrypto.key(fromRecoveryCode: "hello")) == nil)
var codes = Set<String>()
for _ in 0..<200 { codes.insert(JournalCrypto.recoveryCode(for: JournalCrypto.newKey())) }
check("every key gets its own recovery key", codes.count == 200)
var allRoundTrip = true
for _ in 0..<200 {
    let k = JournalCrypto.newKey()
    if (try? JournalCrypto.key(fromRecoveryCode: JournalCrypto.recoveryCode(for: k))).map({ JournalCrypto.keyData($0) }) != JournalCrypto.keyData(k) { allRoundTrip = false }
}
check("200 random keys all come back from their recovery keys", allRoundTrip)
// The "type its last group" check reads what he types the same way the recovery key itself is read.
check("a group typed in lower case with spaces matches", JournalCrypto.tidied(" h457r ") == "H457R")
check("O typed for 0 matches", JournalCrypto.tidied("m447o") == "M4470")
check("I and L typed for 1 match", JournalCrypto.tidied("i8lnl") == "181N1")
var lastGroupsMatch = true
for c in codes {
    let last = String(c.split(separator: "-").last!)
    let sloppy = last.lowercased().replacingOccurrences(of: "0", with: "o").replacingOccurrences(of: "1", with: "l")
    if JournalCrypto.tidied(sloppy) != last { lastGroupsMatch = false }
}
check("every last group still matches when typed sloppily", lastGroupsMatch)

// ---- two devices and a server with the backend's rules
final class FakeServer: JournalTransport, @unchecked Sendable {
    var items: [String: (data: Data?, version: Int, kind: String)] = [:]
    var check: String?
    var offline = false
    var gets = 0
    struct Offline: Error {}
    func state() async throws -> String? { if offline { throw Offline() }; return check }
    func setUp(keyCheck: String) async throws -> JournalSetupResult {
        if offline { throw Offline() }
        if check == nil { check = keyCheck }
        return check == keyCheck ? .ok : .otherKey
    }
    func index() async throws -> [JournalIndexItem] {
        if offline { throw Offline() }
        return items.map { JournalIndexItem(id: $0.key, kind: $0.value.kind, size: $0.value.data?.count ?? 0, version: $0.value.version, deleted: $0.value.data == nil) }
    }
    func get(_ id: String) async throws -> Data? { if offline { throw Offline() }; gets += 1; return items[id]?.data }
    func kind(_ id: String) -> String { id.hasPrefix("a-") ? "audio" : id.hasPrefix("m-") ? "meta" : "entry" }
    func put(_ id: String, data: Data, version: Int) async throws -> JournalWriteResult {
        if offline { throw Offline() }
        let stored = items[id]?.version ?? 0
        guard version > stored else { return .conflict(stored) }
        items[id] = (data, version, kind(id))
        return .saved(version)
    }
    func delete(_ id: String, version: Int) async throws -> JournalWriteResult {
        if offline { throw Offline() }
        let stored = items[id]?.version ?? 0
        guard version > stored else { return .conflict(stored) }
        items[id] = (nil, version, kind(id))
        return .saved(version)
    }
}

func folder(_ name: String) -> URL {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("journal-swift-test-\(getpid())").appendingPathComponent(name)
    try? FileManager.default.removeItem(at: url)
    return url
}

func run(_ body: @escaping () async throws -> Void) {
    let done = DispatchSemaphore(value: 0)
    Task {
        do { try await body() } catch { check("no unexpected error", false, "\(error)") }
        done.signal()
    }
    done.wait()
}

run {
    let server = FakeServer()
    let phoneFolder = folder("phone"), macFolder = folder("mac")
    let phone = JournalEngine(folder: phoneFolder, transport: server)
    let mac = JournalEngine(folder: macFolder, transport: server)
    let first = try JournalCrypto.seal(Data("first".utf8), id: "e-aaa", key: key)
    try await phone.save("e-aaa", sealed: first)
    let onDisk = try Data(contentsOf: phoneFolder.appendingPathComponent("items/e-aaa.sealed"))
    check("this device keeps only the sealed copy", onDisk == first && onDisk.range(of: Data("first".utf8)) == nil)
    let state = try String(contentsOf: phoneFolder.appendingPathComponent("state.json"), encoding: .utf8)
    check("and its own records hold names and versions, never words", !state.contains("first"))
    _ = try await phone.sync()
    check("it reaches the server sealed", server.items["e-aaa"]?.data == first && server.items["e-aaa"]?.version == 1)
    let report = try await mac.sync()
    let macIDs = await mac.entryIDs()
    check("the other device gets it", macIDs == ["e-aaa"] && report.received == 1)
    check("and it opens there with the same key", (try? JournalCrypto.open(await mac.sealed("e-aaa")!, id: "e-aaa", key: key)) == Data("first".utf8))

    try await mac.save("e-aaa", sealed: try JournalCrypto.seal(Data("edited on the mac".utf8), id: "e-aaa", key: key))
    _ = try await mac.sync()
    _ = try await phone.sync()
    let edited = await phone.sealed("e-aaa")
    check("an edit on one device reaches the other", edited.flatMap { try? JournalCrypto.open($0, id: "e-aaa", key: key) } == Data("edited on the mac".utf8))

    server.offline = true
    try await phone.save("e-bbb", sealed: try JournalCrypto.seal(Data("no signal".utf8), id: "e-bbb", key: key))
    var threw = false
    do { _ = try await phone.sync() } catch { threw = true }
    let waiting = await phone.pendingCount
    let phoneIDs = await phone.entryIDs()
    check("with no signal the note waits on the phone", threw && waiting == 1 && phoneIDs.contains("e-bbb"))
    let reopened = JournalEngine(folder: phoneFolder, transport: server)
    let stillWaiting = await reopened.pendingCount
    check("and still waits after the app is closed and opened", stillWaiting == 1)
    server.offline = false
    _ = try await reopened.sync()
    let afterSignal = await reopened.pendingCount
    check("then goes when there's signal", afterSignal == 0 && server.items["e-bbb"]?.version == 1)

    // both change the same note before either syncs
    try await reopened.save("e-aaa", sealed: try JournalCrypto.seal(Data("phone's change".utf8), id: "e-aaa", key: key))
    try await mac.save("e-aaa", sealed: try JournalCrypto.seal(Data("mac's change".utf8), id: "e-aaa", key: key))
    _ = try await reopened.sync()
    _ = try await mac.sync()
    _ = try await reopened.sync()
    let phoneCopy = await reopened.sealed("e-aaa")
    let onPhone = phoneCopy.flatMap { try? JournalCrypto.open($0, id: "e-aaa", key: key) }
    let onServer = try? JournalCrypto.open(server.items["e-aaa"]!.data!, id: "e-aaa", key: key)
    check("when both change one note, the last one sent wins on both", onPhone == Data("mac's change".utf8) && onServer == onPhone, String(decoding: onPhone ?? Data(), as: UTF8.self))
    let leftPhone = await reopened.pendingCount
    let leftMac = await mac.pendingCount
    check("and nothing is left waiting", leftPhone == 0 && leftMac == 0)

    // deleting
    try await mac.remove("e-bbb")
    _ = try await mac.sync()
    let removed = try await reopened.sync()
    let afterDelete = await reopened.entryIDs()
    check("a deletion reaches the other device", !afterDelete.contains("e-bbb") && removed.removed == 1)
    check("and its file is gone there", !FileManager.default.fileExists(atPath: phoneFolder.appendingPathComponent("items/e-bbb.sealed").path))
    check("the server keeps only a tombstone", server.items["e-bbb"]?.data == nil)

    // recordings: only fetched when played
    let audio = try JournalCrypto.seal(Data(repeating: 7, count: 200_000), id: "a-ccc", key: key)
    try await mac.save("a-ccc", sealed: audio)
    _ = try await mac.sync()
    let before = server.gets
    _ = try await reopened.sync()
    let notYet = await reopened.sealed("a-ccc")
    check("a recording made on the other device isn't downloaded until it's played", server.gets == before && notYet == nil)
    let played = try await reopened.fetch("a-ccc")
    check("then it is", played == audio && server.gets == before + 1)
    let again = try await reopened.fetch("a-ccc")
    check("and stays for next time", again == audio && server.gets == before + 1)

    // forgetting this device
    try await reopened.wipe()
    let wipedIDs = await reopened.entryIDs()
    let wipedPending = await reopened.pendingCount
    check("taking the journal off a device leaves nothing on it", wipedIDs.isEmpty && wipedPending == 0)
    _ = try await reopened.sync()
    let caughtUp = await reopened.entryIDs()
    check("and it can catch up again from the server", Set(caughtUp) == ["e-aaa"])
    check("the server still has everything", server.items["e-aaa"]?.data != nil)
}

// ---- the real backend code, on a throwaway server
if let port = ProcessInfo.processInfo.environment["JOURNAL_TEST_PORT"].flatMap(Int.init) {
    BackendHost.environment = .local
    BackendHost.localHost = "127.0.0.1"
    BackendHost.localPort = port
    AuthToken.provider = { "test-token" }
    run {
        let http = JournalHTTP()
        let empty = try await http.state()
        check("the throwaway server starts with no journal", empty == nil)
        let realKey = JournalCrypto.newKey()
        let firstSetup = try await http.setUp(keyCheck: JournalCrypto.keyCheck(realKey))
        check("a device sets one up", firstSetup == .ok)
        let secondSetup = try await http.setUp(keyCheck: JournalCrypto.keyCheck(JournalCrypto.newKey()))
        check("a second key is refused", secondSetup == .otherKey)
        let stored = try await http.state()
        check("the check comes back for the next device", stored == JournalCrypto.keyCheck(realKey))
        let phone = JournalEngine(folder: folder("http-phone"), transport: http)
        let mac = JournalEngine(folder: folder("http-mac"), transport: http)
        let id = JournalEntry.newID(prefix: "e")
        let audioID = JournalEntry.newID(prefix: "a")
        try await phone.save(id, sealed: try JournalCrypto.seal(Data("through the real server".utf8), id: id, key: realKey))
        try await phone.save(audioID, sealed: try JournalCrypto.seal(Data(repeating: 1, count: 2_000_000), id: audioID, key: realKey))
        _ = try await phone.sync()
        _ = try await mac.sync()
        let arrived = await mac.sealed(id)
        check("a note goes through the real server code and opens on the other device", arrived.flatMap { try? JournalCrypto.open($0, id: id, key: realKey) } == Data("through the real server".utf8))
        let recording = try await mac.fetch(audioID)
        check("a 2 MB recording too, when it's played", recording.flatMap { try? JournalCrypto.open($0, id: audioID, key: realKey) }?.count == 2_000_000)
        try await mac.save(id, sealed: try JournalCrypto.seal(Data("edit".utf8), id: id, key: realKey))
        try await phone.save(id, sealed: try JournalCrypto.seal(Data("phone edit".utf8), id: id, key: realKey))
        _ = try await mac.sync()
        _ = try await phone.sync()
        _ = try await mac.sync()
        let settled = await mac.sealed(id)
        check("both editing one note settles on the last one sent, through the real server", settled.flatMap { try? JournalCrypto.open($0, id: id, key: realKey) } == Data("phone edit".utf8))
        try await phone.remove(id)
        _ = try await phone.sync()
        _ = try await mac.sync()
        let macAfter = await mac.entryIDs()
        check("a deletion goes through it too", !macAfter.contains(id))
    }
} else {
    print("SKIP the real server: JOURNAL_TEST_PORT isn't set")
}

print("\nFAILS: \(fails)")
exit(fails == 0 ? 0 : 1)
