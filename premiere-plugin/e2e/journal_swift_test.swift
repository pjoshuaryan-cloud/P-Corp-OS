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
    /// Items this server turns away, the way a real one answers 413 or an older one 404.
    var refuse: Set<String> = []
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
    func kind(_ id: String) -> String { id.hasPrefix("a-") ? "audio" : id.hasPrefix("m-") ? "meta" : id.hasPrefix("h-") ? "highlight" : "entry" }
    func put(_ id: String, data: Data, version: Int) async throws -> JournalWriteResult {
        if offline { throw Offline() }
        if refuse.contains(id) { throw JournalHTTP.Failure.server(413, "too big") }
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

// ---- sorting, highlights and reminders (2026-11-07), all worked out on the device
let cal = Calendar.current
func local(_ y: Int, _ m: Int, _ d: Int, _ h: Int, _ min: Int = 0) -> Date { cal.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: min))! }
let satNight = local(2026, 11, 7, 21)
let lastWeek = JournalPeriod.latest(.week, before: satNight)
check("on a Saturday night the latest finished week ended last Sunday at 7pm", lastWeek.end == local(2026, 11, 1, 19) && lastWeek.start == local(2026, 10, 25, 19), "\(lastWeek.start) – \(lastWeek.end)")
check("and is named for the day it ended", lastWeek.id == "h-week-2026-11-01", lastWeek.id)
let justAfter = JournalPeriod.latest(.week, before: local(2026, 11, 8, 19, 1))
check("a minute after Sunday 7pm, that week is the latest", justAfter.id == "h-week-2026-11-08" && justAfter.contains(local(2026, 11, 8, 18, 59)) && !justAfter.contains(local(2026, 11, 8, 19, 0)))
check("a note at 7pm on Sunday belongs to the next week", JournalPeriod.latest(.week, before: local(2026, 11, 15, 20)).contains(local(2026, 11, 8, 19, 0)))
let month = JournalPeriod.latest(.month, before: satNight)
check("the latest finished month ran 25 Sep 7pm to 25 Oct 7pm", month.start == local(2026, 9, 25, 19) && month.end == local(2026, 10, 25, 19) && month.id == "h-month-2026-10-25", month.id)
check("a week steps back seven days, a month one month", lastWeek.previous().end == lastWeek.start && month.previous().id == "h-month-2026-09-25")
check("the server accepts the names it makes", ["h-week-2026-11-01", "h-month-2026-10-25"].allSatisfy { $0.range(of: #"^h-(week|month)-\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil })

let weekNotes = [
    JournalEntry(category: "Feelings", text: "Nervous about the JD shoot. Chest tight all evening.", now: local(2026, 11, 2, 21)),
    JournalEntry(category: "Notes to self", text: "Charge batteries and send the JD shot list.", now: local(2026, 11, 3, 8)),
    JournalEntry(category: "Feelings", transcript: "The JD shoot went really well. I'm proud of the team and relieved.", audioID: "a-1", duration: 130, now: local(2026, 11, 6, 22)),
]
let digest = JournalDigest.make(weekNotes)
check("a digest counts notes, voice notes and minutes", digest.notes == 3 && digest.voiceNotes == 1 && digest.voiceMinutes == 2, "\(digest.notes) \(digest.voiceNotes) \(digest.voiceMinutes)")
check("and notes by category, biggest first", digest.categories.first == JournalDigest.Count(category: "Feelings", notes: 2))
check("the hardest day is the nervous one, the best the proud one", digest.hardestDay == cal.startOfDay(for: local(2026, 11, 2, 21)) && digest.bestDay == cal.startOfDay(for: local(2026, 11, 6, 22)))
check("a short name he keeps using is a theme", digest.themes.contains("JD"), "\(digest.themes)")
check("its quotes are what he felt, not his to-do list", !digest.standouts.contains { $0.contains("Charge batteries") } && !digest.standouts.isEmpty, "\(digest.standouts)")
var edited = weekNotes
edited[0].updatedAt = edited[0].updatedAt.addingTimeInterval(60)
check("editing a note changes what a summary was made from", JournalDigest.basis(of: edited) != digest.basis && JournalDigest.basis(of: weekNotes) == digest.basis)
check("no mood line from fewer than two feeling words", JournalDigest.make([JournalEntry(category: "Finance", text: "Invoice JD R18,500.")]).mood == nil)
check("'not happy' counts as heavy", JournalDigest.feeling("I'm not happy with how it went").score == -1)
check("'proud' and 'relieved' count as upbeat", JournalDigest.feeling("Proud and relieved").score == 1)

let reply = JournalModel.parse("**SUMMARY:**\n\nyou were nervous, then proud.\n\n**REMEMBER:**\n- pitch the mini series\n- Invoice JD\n- none\n- a fourth\n- a fifth")
check("the Mac's written reply is read: summary capitalised, markdown dropped", reply?.summary == "You were nervous, then proud.", "\(String(describing: reply?.summary))")
check("up to three things worth remembering, 'none' left out", reply?.remember == ["Pitch the mini series", "Invoice JD", "A fourth"], "\(String(describing: reply?.remember))")
check("'none' alone means nothing to remember", JournalModel.parse("SUMMARY: A quiet week.\nREMEMBER:\n- none")?.remember == [])
check("a reply with no summary is no highlight", JournalModel.parse("Sorry, I can't help with that.") == nil)

check("Finance is one of the starting categories", JournalDefaults.categories == ["Notes to self", "Ideas", "Feelings", "Finance"])
let sortChecks: [(String, String)] = [
    ("Charge the Sony batteries and pack the lav mics tonight.", "Notes to self"), ("Text Lerato the call sheet before 9.", "Notes to self"),
    ("Return the borrowed tripod to Sipho on Friday.", "Notes to self"), ("Renew the domain for alphamode.media before April.", "Notes to self"),
    ("Clean the sensor on the A7S before Monday.", "Notes to self"), ("Send Frank the brief for the next shoot.", "Notes to self"),
    ("We could run a workshop teaching small businesses to film on their phones.", "Ideas"), ("A documentary following three taxi drivers for a day.", "Ideas"),
    ("Turn the JD behind-the-scenes into a mini series for TikTok.", "Ideas"), ("Offer clients a same-day social cut as an add-on.", "Ideas"),
    ("What about a monthly newsletter with our best frames?", "Ideas"), ("Maybe partner with a music producer for original tracks on every reel.", "Ideas"),
    ("Can't sleep. My mind won't stop racing about everything.", "Feelings"), ("Felt so loved at dinner tonight with the family.", "Feelings"),
    ("I'm disappointed in how I handled that client call.", "Feelings"), ("Worried about my dad's health.", "Feelings"),
    ("Nervous but ready for tomorrow.", "Feelings"), ("Really content tonight, nothing to fix.", "Feelings"),
    ("The Lexar card cost R1,899, put it on the business account.", "Finance"), ("We made R42k this month, best month so far.", "Finance"),
    ("Medical aid went up again, R600 more a month.", "Finance"), ("Set aside 30 percent of every payment for tax.", "Finance"),
    ("Paid the SARS bill, R4,350.", "Finance"), ("Need R20k for the new lens, saving R2k a month.", "Finance"),
]
run {
    var right = 0
    for (text, want) in sortChecks where await JournalSorter.matcher.pick(text, categories: JournalDefaults.categories, examples: [:]) == want { right += 1 }
    check("the iPhone's built-in sorting files at least 21 of 24 made-up notes right", right >= 21, "\(right)/24")
    let mine = [JournalEntry(category: "Shoots", text: "Wrapped the JD store opening, 412 clips on the Lexar.")]
    var examples: [String: [String]] = [:]
    for e in mine { examples[e.category, default: []].append(e.words) }
    let custom = await JournalSorter.matcher.pick("Wrapped the Birkenstock shoot, 300 clips on the card.", categories: JournalDefaults.categories + ["Shoots"], examples: examples)
    check("a category of his own learns from the notes he's filed in it", custom == "Shoots", "\(String(describing: custom))")
    let empty = await JournalSorter.category(for: "   ", categories: JournalDefaults.categories, history: [])
    check("a note with no words goes in the first category", empty == "Notes to self")
}

check("reminders only exist on the iPhone", !JournalReminders.supported)

run {
    let server = FakeServer()
    let engine = JournalEngine(folder: folder("refused"), transport: server)
    let key = JournalCrypto.newKey()
    let big = JournalEntry.newID(prefix: "e"), small = JournalEntry.newID(prefix: "e")
    server.refuse = [big]
    try await engine.save(big, sealed: try JournalCrypto.seal(Data("too big".utf8), id: big, key: key))
    try await engine.save(small, sealed: try JournalCrypto.seal(Data("fine".utf8), id: small, key: key))
    var failure: Error?
    do { _ = try await engine.sync() } catch { failure = error }
    check("an item the server turns away doesn't hold up the ones behind it", server.items[small] != nil)
    check("it stays queued, and the sync says so", server.items[big] == nil && (failure as? JournalEngine.SyncFailure) == .refused)
    let waiting = await engine.pendingCount
    check("only the refused one is still waiting", waiting == 1, "\(waiting)")
    server.refuse = []
    _ = try await engine.sync()
    let after = await engine.pendingCount
    check("and it goes once the server takes it", server.items[big] != nil && after == 0)
    let h = "h-week-2026-11-08"
    try await engine.save(h, sealed: try JournalCrypto.seal(Data("{}".utf8), id: h, key: key))
    _ = try await engine.sync()
    let phone = JournalEngine(folder: folder("refused-phone"), transport: server)
    _ = try await phone.sync()
    let highlightIDs = await phone.ids(prefix: "h-")
    let noteIDs = await phone.entryIDs()
    check("a highlight syncs to the other device like a note, and isn't listed as one", highlightIDs == [h] && !noteIDs.contains(h))
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
        let h = "h-week-2026-11-08"
        try await mac.save(h, sealed: try JournalCrypto.seal(Data("{\"summary\":\"a week\"}".utf8), id: h, key: realKey))
        _ = try await mac.sync()
        _ = try await phone.sync()
        let got = await phone.sealed(h)
        check("a sealed highlight goes through the real server code too", got.flatMap { try? JournalCrypto.open($0, id: h, key: realKey) } == Data("{\"summary\":\"a week\"}".utf8))
    }
} else {
    print("SKIP the real server: JOURNAL_TEST_PORT isn't set")
}

print("\nFAILS: \(fails)")
exit(fails == 0 ? 0 : 1)
