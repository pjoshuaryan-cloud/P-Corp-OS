import CryptoKit
import Foundation
import NaturalLanguage
#if canImport(FoundationModels)
import FoundationModels
#endif
#if os(iOS)
import UserNotifications
#endif

// The journal reading itself (2026-11-07): sorting a note into a category as it's saved, and the weekly and monthly highlights. All of it runs
// on his own devices, on notes that are only ever decrypted into memory while the journal is open. Nothing here talks to the network, to Frank
// or to Anthropic. The Mac writes its summaries with Apple's on-device model (FoundationModels, which never leaves the device); the iPhone 15
// can't run that model, so it sorts with Apple's built-in language tools and shows the counted highlights until the Mac's written one syncs.

// MARK: - Periods

/// A week or a month of the journal, ending when its reminder goes: Sunday at 7pm, and the 25th at 7pm. Each one covers the time since the
/// one before, so every note falls in exactly one week and one month.
public struct JournalPeriod: Hashable, Identifiable, Sendable {
    public enum Kind: String, Codable, Sendable { case week, month }

    public let kind: Kind
    public let start: Date
    public let end: Date

    static let hour = 19

    public init(kind: Kind, start: Date, end: Date) {
        self.kind = kind
        self.start = start
        self.end = end
    }

    /// Its name for a sealed highlight: "h-week-2026-11-08", the local date it ends on.
    public var id: String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return "h-\(kind.rawValue)-\(f.string(from: end))"
    }

    public var title: String { kind == .week ? "Your thoughts this week" : "What you thought this month" }

    public var span: String {
        let f = DateFormatter()
        f.dateFormat = "d MMM"
        return "\(f.string(from: start)) – \(f.string(from: end))"
    }

    public func contains(_ date: Date) -> Bool { date >= start && date < end }

    public func previous(calendar: Calendar = .current) -> JournalPeriod {
        let earlier = kind == .week ? calendar.date(byAdding: .day, value: -7, to: start)! : calendar.date(byAdding: .month, value: -1, to: start)!
        return JournalPeriod(kind: kind, start: earlier, end: start)
    }

    /// The latest period of this kind that has ended by `now`.
    public static func latest(_ kind: Kind, before now: Date = Date(), calendar: Calendar = .current) -> JournalPeriod {
        let moment = kind == .week ? DateComponents(hour: hour, minute: 0, second: 0, weekday: 1) : DateComponents(day: 25, hour: hour, minute: 0, second: 0)
        var end = calendar.nextDate(after: now, matching: moment, matchingPolicy: .nextTime, direction: .backward)!
        if end > now { end = calendar.nextDate(after: end, matching: moment, matchingPolicy: .nextTime, direction: .backward)! }
        let start = kind == .week ? calendar.date(byAdding: .day, value: -7, to: end)! : calendar.date(byAdding: .month, value: -1, to: end)!
        return JournalPeriod(kind: kind, start: start, end: end)
    }
}

// MARK: - What a period's notes add up to, counted on the device

public struct JournalDigest: Equatable, Sendable {
    public struct Count: Equatable, Sendable {
        public let category: String
        public let notes: Int
    }

    public var notes = 0
    public var voiceNotes = 0
    public var voiceMinutes = 0
    public var categories: [Count] = []
    /// From -1 (heavy) to 1 (upbeat), from the feeling words he actually used. Nil with fewer than two of them: Apple's built-in sentiment
    /// scoring was tried and rated "I feel really anxious" as upbeat, so it isn't used.
    public var mood: Double?
    public var bestDay: Date?
    public var hardestDay: Date?
    public var themes: [String] = []
    public var standouts: [String] = []
    /// Which notes, in which versions, this was made from. A written summary from older notes doesn't match it, so it isn't shown.
    public var basis = ""

    public var moodLine: String? {
        guard let mood else { return nil }
        let feel = mood > 0.2 ? "mostly upbeat" : mood < -0.2 ? "a heavier stretch" : "mixed"
        let day = DateFormatter()
        day.dateFormat = "EEEE"
        var line = "Mood: \(feel)."
        if let bestDay, let hardestDay { line += " Best day \(day.string(from: bestDay)), hardest \(day.string(from: hardestDay))." }
        return line
    }

    public static func basis(of entries: [JournalEntry]) -> String {
        let list = entries.map { "\($0.id)|\(Int($0.updatedAt.timeIntervalSince1970 * 1000))" }.sorted().joined(separator: "\n")
        return String(SHA256.hash(data: Data(list.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24))
    }

    public static func make(_ entries: [JournalEntry], calendar: Calendar = .current) -> JournalDigest {
        var digest = JournalDigest()
        digest.notes = entries.count
        digest.basis = basis(of: entries)
        let voiced = entries.filter { $0.audioID != nil }
        digest.voiceNotes = voiced.count
        digest.voiceMinutes = Int((voiced.compactMap(\.duration).reduce(0, +) / 60).rounded())
        var counts: [String: Int] = [:]
        for e in entries { counts[e.category, default: 0] += 1 }
        digest.categories = counts.map { Count(category: $0.key, notes: $0.value) }.sorted { $0.notes != $1.notes ? $0.notes > $1.notes : $0.category < $1.category }

        var scores: [(Date, Double)] = []
        var feelingWords = 0
        for e in entries {
            let f = feeling(body(of: e))
            feelingWords += f.positive + f.negative
            if let s = f.score { scores.append((e.createdAt, s)) }
        }
        if !scores.isEmpty && feelingWords >= 2 {
            digest.mood = scores.map(\.1).reduce(0, +) / Double(scores.count)
            var byDay: [Date: [Double]] = [:]
            for (date, s) in scores { byDay[calendar.startOfDay(for: date), default: []].append(s) }
            let days = byDay.mapValues { $0.reduce(0, +) / Double($0.count) }
            if days.count >= 2, let best = days.max(by: { $0.value < $1.value }), let hardest = days.min(by: { $0.value < $1.value }), best.value - hardest.value >= 0.3 {
                digest.bestDay = best.key
                digest.hardestDay = hardest.key
            }
        }
        digest.themes = themes(in: entries)
        digest.standouts = standouts(in: entries, themes: digest.themes)
        return digest
    }

    static func body(of entry: JournalEntry) -> String {
        [entry.text, entry.transcript ?? ""].filter { !$0.isEmpty }.joined(separator: "\n")
    }

    static let upbeat: Set<String> = ["proud", "grateful", "thankful", "happy", "relieved", "calm", "excited", "loved", "content", "peaceful", "peace",
        "hopeful", "joy", "joyful", "glad", "good", "great", "amazing", "blessed", "confident", "energised", "energized", "inspired", "motivated",
        "rested", "fun", "love", "laughed", "laughing", "won", "thrilled", "satisfied", "encouraged"]
    static let heavy: Set<String> = ["anxious", "anxiety", "nervous", "worried", "worry", "scared", "afraid", "fear", "lonely", "sad", "depressed",
        "tired", "exhausted", "drained", "overwhelmed", "stressed", "stress", "frustrated", "angry", "upset", "hurt", "disappointed", "guilty",
        "ashamed", "numb", "stuck", "hopeless", "cried", "cry", "crying", "heartbroken", "jealous", "panic", "miserable", "unmotivated", "lost"]
    static let negations: Set<String> = ["not", "no", "never", "don't", "didn't", "isn't", "wasn't", "can't", "couldn't", "won't", "dont", "didnt", "isnt", "wasnt", "cant"]

    /// The feeling words in a piece of writing, with "not" and the like turning them round. Score is nil when there are none.
    static func feeling(_ text: String) -> (positive: Int, negative: Int, score: Double?) {
        let words = text.lowercased().split(whereSeparator: { !$0.isLetter && $0 != "'" }).map(String.init)
        var positive = 0, negative = 0
        for (i, w) in words.enumerated() {
            let up = upbeat.contains(w), down = heavy.contains(w)
            guard up || down else { continue }
            let flipped = words[max(0, i - 3)..<i].contains { negations.contains($0) }
            if up != flipped { positive += 1 } else { negative += 1 }
        }
        let total = positive + negative
        return (positive, negative, total > 0 ? Double(positive - negative) / Double(total) : nil)
    }

    static let ordinaryWords: Set<String> = ["today", "tomorrow", "yesterday", "thing", "things", "time", "times", "day", "days", "week", "weeks", "month", "lot", "way",
        "something", "everything", "nothing", "anything", "someone", "people", "bit", "kind", "sort", "stuff", "part", "point", "fact", "reason", "idea", "ideas",
        "feeling", "feelings", "note", "notes", "self", "finance", "morning", "night", "evening", "life", "work", "year", "years", "minute", "minutes", "hour", "hours"]

    /// The words he kept coming back to: names and nouns that turn up in more than one note (or twice in a single note, when there's only one).
    static func themes(in entries: [JournalEntry]) -> [String] {
        var notesWith: [String: Int] = [:]
        var times: [String: Int] = [:]
        var shown: [String: String] = [:]
        var alwaysCapital: [String: Bool] = [:]
        for e in entries {
            let text = [e.title, body(of: e)].joined(separator: ". ")
            let tagger = NLTagger(tagSchemes: [.nameTypeOrLexicalClass, .lemma])
            tagger.string = text
            var seen = Set<String>()
            let options: NLTagger.Options = [.omitPunctuation, .omitWhitespace, .joinNames]
            tagger.enumerateTags(in: text.startIndex..<text.endIndex, unit: .word, scheme: .nameTypeOrLexicalClass, options: options) { tag, range in
                let word = String(text[range])
                let shortCaps = word.count >= 2 && word.count <= 5 && word == word.uppercased() && word.contains(where: \.isLetter)
                let isName = tag == .personalName || tag == .placeName || tag == .organizationName || shortCaps
                guard isName || tag == .noun else { return true }
                var key = word.lowercased()
                if !isName, let lemma = tagger.tag(at: range.lowerBound, unit: .word, scheme: .lemma).0?.rawValue, !lemma.isEmpty { key = lemma.lowercased() }
                guard key.count >= (isName ? 2 : 3), !ordinaryWords.contains(key) else { return true }
                times[key, default: 0] += 1
                if shown[key] == nil { shown[key] = word }
                alwaysCapital[key] = (alwaysCapital[key] ?? true) && (word.first?.isUppercase ?? false)
                if seen.insert(key).inserted { notesWith[key, default: 0] += 1 }
                return true
            }
        }
        let several = entries.count > 1
        let wanted: (String) -> Bool = { several ? (notesWith[$0] ?? 0) >= 2 : (times[$0] ?? 0) >= 2 }
        return times.keys.filter(wanted)
            .sorted { (notesWith[$0]!, times[$0]!, $1) > (notesWith[$1]!, times[$1]!, $0) }
            .prefix(5)
            .compactMap { key in (alwaysCapital[key] ?? false) ? shown[key] : key }
    }

    /// "In your words" is for what he felt and imagined. Jobs and sums are never quoted there.
    static let standoutWeight: [String: Double] = ["Feelings": 0.35, "Ideas": 0.25, "Notes to self": -0.4, "Finance": -0.4]

    /// A few of his own sentences that stand out: strongly felt, or about what he kept coming back to. Never more than one per note.
    static func standouts(in entries: [JournalEntry], themes: [String]) -> [String] {
        let themeWords = Set(themes.map { $0.lowercased() })
        var picks: [(Date, Double, String)] = []
        for e in entries where (standoutWeight[e.category] ?? 0) >= 0 {
            let text = body(of: e)
            let tokenizer = NLTokenizer(unit: .sentence)
            tokenizer.string = text
            var best: (Double, String)?
            tokenizer.enumerateTokens(in: text.startIndex..<text.endIndex) { range, _ in
                let sentence = text[range].trimmingCharacters(in: .whitespacesAndNewlines)
                guard (20...220).contains(sentence.count) else { return true }
                let lower = sentence.lowercased()
                let mentions = themeWords.filter { lower.contains($0) }.count
                let felt = feeling(sentence)
                let score = 0.35 * Double(min(felt.positive + felt.negative, 3)) + 0.3 * Double(mentions) + Double(min(sentence.count, 160)) / 1600 + (standoutWeight[e.category] ?? 0)
                if best == nil || score > best!.0 { best = (score, sentence) }
                return true
            }
            if let best { picks.append((e.createdAt, best.0, best.1)) }
        }
        return picks.sorted { $0.1 > $1.1 }.prefix(3).sorted { $0.0 < $1.0 }.map(\.2)
    }
}

// MARK: - A written highlight, from the Mac's on-device model, kept sealed like a note

public struct JournalHighlight: Codable, Equatable, Sendable {
    public var id: String
    public var kind: JournalPeriod.Kind
    public var start: Date
    public var end: Date
    public var basis: String
    public var writtenAt: Date
    public var summary: String
    public var remember: [String]
}

/// Apple's on-device model, where the device has one (his Mac does, his iPhone 15 doesn't). Everything it's given stays on the device.
public enum JournalModel {
    static var turnedOffForTest: Bool {
        #if targetEnvironment(simulator)
        return ProcessInfo.processInfo.environment["PCORP_JOURNAL_NO_MODEL"] == "1"
        #else
        return false
        #endif
    }

    public static var available: Bool {
        if turnedOffForTest { return false }
        #if canImport(FoundationModels)
        if #available(macOS 26.0, iOS 26.0, *) {
            if case .available = SystemLanguageModel(guardrails: .permissiveContentTransformations).availability { return true }
        }
        #endif
        return false
    }

    static let writerInstructions = """
    You write short, warm, honest highlights of someone's private journal, for their eyes only. Speak to them directly as "you", never "I" or "we". \
    Use only what is in their notes and never invent anything. Don't give advice or judge. Keep their own words where you can. \
    Reply in exactly this shape and nothing else:
    SUMMARY: two to four sentences about what they did, felt and thought.
    REMEMBER:
    - up to three useful things from the notes: an idea they had, a plan, or something they said they'd do. Not feelings. Write "- none" if there are none.
    """

    /// The summary and the things worth remembering, out of the model's plain-text reply. Nil if there's no summary in it.
    static func parse(_ reply: String) -> (summary: String, remember: [String])? {
        let clean = reply.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "__", with: "")
        let lower = clean.lowercased()
        guard let s = lower.range(of: "summary:") else { return nil }
        let r = lower.range(of: "remember:", range: s.upperBound..<lower.endIndex)
        let summaryEnd = r?.lowerBound ?? lower.endIndex
        func offset(_ i: String.Index) -> String.Index { clean.index(clean.startIndex, offsetBy: lower.distance(from: lower.startIndex, to: i)) }
        var summary = String(clean[offset(s.upperBound)..<offset(summaryEnd)]).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !summary.isEmpty else { return nil }
        summary = summary.prefix(1).uppercased() + summary.dropFirst()
        var remember: [String] = []
        if let r {
            for line in clean[offset(r.upperBound)...].split(whereSeparator: \.isNewline) {
                var item = line.trimmingCharacters(in: .whitespaces)
                guard let first = item.first, "-•*".contains(first) else { continue }
                item = item.dropFirst().trimmingCharacters(in: .whitespaces)
                guard !item.isEmpty, item.lowercased().trimmingCharacters(in: .punctuationCharacters) != "none" else { continue }
                remember.append(item.prefix(1).uppercased() + item.dropFirst())
            }
        }
        return (summary, Array(remember.prefix(3)))
    }

    static let sorterInstructions = "You sort private journal notes into categories by what each note is mainly for. Reply with exactly one category name from the list given, and nothing else."

    /// A summary of the period's notes, or nil if the model isn't here or declines.
    public static func write(_ period: JournalPeriod, entries: [JournalEntry]) async -> (summary: String, remember: [String])? {
        #if canImport(FoundationModels)
        guard available, !entries.isEmpty else { return nil }
        if #available(macOS 26.0, iOS 26.0, *) {
            let day = DateFormatter()
            day.dateFormat = "EEE d MMM"
            var lines = entries.sorted { $0.createdAt < $1.createdAt }.map { e -> String in
                let words = [e.title, JournalDigest.body(of: e)].filter { !$0.isEmpty }.joined(separator: ": ")
                return "[\(day.string(from: e.createdAt)), \(e.category)] \(words.prefix(500))"
            }
            // Its context is small: a long month keeps an even spread of notes rather than only the first ones.
            while lines.joined(separator: "\n").count > 7000 && lines.count > 4 {
                lines = lines.enumerated().filter { $0.offset % 2 == 0 }.map(\.element)
            }
            let what = period.kind == .week ? "this week" : "this month"
            let prompt = "Here are their journal notes from \(what) (\(period.span)), \(entries.count) in all:\n\(lines.joined(separator: "\n"))"
            do {
                // Plain text, because Apple's looser filter for summarising your own words only covers plain-text replies, and the strict one
                // turns away harmless filmmaking words like "shoot".
                let session = LanguageModelSession(model: SystemLanguageModel(guardrails: .permissiveContentTransformations), instructions: writerInstructions)
                let reply = try await session.respond(to: prompt, options: GenerationOptions(temperature: 0.3))
                return parse(reply.content)
            } catch {
                return nil
            }
        }
        #endif
        return nil
    }

    /// Which category the model would file a note under, or nil (no model, no answer it recognises).
    static func sort(_ words: String, categories: [String], examples: [String: [String]]) async -> String? {
        #if canImport(FoundationModels)
        guard available else { return nil }
        if #available(macOS 26.0, iOS 26.0, *) {
            var guide = categories.map { name -> String in
                if let about = JournalSorter.about[name] { return "\(name): \(about)" }
                return name
            }.joined(separator: "\n")
            let shown = categories.flatMap { name in (examples[name] ?? []).prefix(2).map { "\(name) <- \($0.prefix(140))" } }
            if !shown.isEmpty { guide += "\n\nHow they've filed notes before:\n" + shown.joined(separator: "\n") }
            let prompt = "Categories:\n\(guide)\n\nNote:\n\(words.prefix(1500))\n\nCategory:"
            do {
                let session = LanguageModelSession(model: SystemLanguageModel(guardrails: .permissiveContentTransformations), instructions: sorterInstructions)
                let reply = try await session.respond(to: prompt, options: GenerationOptions(temperature: 0))
                let said = reply.content.trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters)).lowercased()
                return categories.first { $0.lowercased() == said } ?? categories.first { said.contains($0.lowercased()) }
            } catch {
                return nil
            }
        }
        #endif
        return nil
    }
}

// MARK: - Sorting a note as it's saved

public enum JournalSorter {
    /// What each starting category is for, in the model's guide.
    static let about: [String: String] = [
        "Notes to self": "a task, errand or reminder: something to do, send, buy, book, check or remember, even if it mentions a client, a bill or a cost",
        "Ideas": "an idea or possibility: something they could make, build, film, try, sell, offer or start",
        "Feelings": "how they feel: emotions, mood, worries, hopes, gratitude, relationships",
        "Finance": "mainly about money itself: amounts earned or spent, budgets, prices, payments owed, saving, debt and tax",
    ]

    /// Examples for Apple's built-in sentence matching, for the starting categories. His own filed notes count for more as they build up.
    static let seeds: [String: [String]] = [
        "Notes to self": ["Remember to call him tomorrow.", "Don't forget to buy batteries and SD cards.", "Need to send the files and book the venue.",
                          "Reminder: back up the drive before Friday.", "To do this week: email the client and fix the website.", "Pick up the parcel and renew the licence."],
        "Ideas": ["What if I built an app that does this automatically?", "Idea for a short film about my grandfather.", "A new business idea: rent out camera gear.",
                  "It could edit the reels for me.", "A concept for the next brand campaign.", "I should try shooting this in black and white.",
                  "We could start a podcast about it.", "Maybe offer a new kind of package to clients.", "A series of short videos showing how we work.",
                  "Try making the whole thing in one take.", "The software could plan this for me automatically.", "We could sell our own presets and templates."],
        "Feelings": ["I feel anxious and overwhelmed today.", "I'm so grateful and happy right now.", "Feeling lonely and tired this week.",
                     "I was angry and hurt after that conversation.", "I'm proud of myself for finishing it.", "Honestly I feel stuck and unmotivated."],
        "Finance": ["I need to pay rent and the car instalment.", "Budget for this month after bills.", "Invoice the client for the shoot.",
                    "Move money into savings and pay off the card.", "Spent too much on gear, need to cut back.", "The salary and debit orders this month."],
    ]

    static let cues: [String: [String]] = [
        "Finance": ["money", "rand", "rands", "budget", "invoice", "invoices", "pay", "paid", "payment", "payments", "salary", "debt", "savings", "save", "invest",
                    "investment", "cost", "costs", "price", "spend", "spent", "bank", "loan", "tax", "rent", "bill", "bills", "expenses", "income", "profit",
                    "cash", "debit", "afford", "broke", "fee", "fees", "quote", "deposit", "owe", "owed", "instalment", "account", "sars", "discount", "margin", "earned", "made"],
        "Feelings": ["feel", "feeling", "felt", "sad", "happy", "anxious", "anxiety", "stressed", "stress", "grateful", "angry", "upset", "tired", "exhausted",
                     "excited", "lonely", "disappointed", "loved", "hopeless", "afraid of", "can't sleep", "overwhelmed", "scared", "afraid", "hurt", "proud", "depressed", "frustrated", "cried", "cry", "hopeful", "calm",
                     "numb", "jealous", "guilty", "ashamed", "nervous", "worried", "worry", "joy", "heartbroken", "miss", "love"],
        "Ideas": ["idea", "ideas", "what if", "concept", "invent", "brainstorm", "startup", "app", "pitch", "imagine", "prototype", "could build",
                  "should make", "would be cool", "new business", "film about", "series", "we could", "i could", "it could", "could sell",
                  "could offer", "should offer", "maybe we", "maybe partner", "what about", "try a", "try shooting", "documentary", "podcast", "workshop"],
        "Notes to self": ["remember", "remind", "reminder", "don't forget", "do not forget", "need to", "must", "todo", "to-do", "to do", "call", "buy",
                          "book", "email", "pick up", "check", "send"],
    ]

    /// The category for a new note: Apple's on-device model where the device has one, otherwise sentence matching plus words that give a
    /// category away. Learns from how he's filed notes before. Falls back to the first category when there's nothing to read.
    public static func category(for words: String, categories: [String], history: [JournalEntry]) async -> String {
        let fallback = categories.first ?? "Notes to self"
        let text = words.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !categories.isEmpty else { return fallback }
        var examples: [String: [String]] = [:]
        for e in history.sorted(by: { $0.updatedAt > $1.updatedAt }) where categories.contains(e.category) {
            let w = e.words
            if !w.isEmpty, (examples[e.category]?.count ?? 0) < 40 { examples[e.category, default: []].append(w) }
        }
        if let picked = await JournalModel.sort(text, categories: categories, examples: examples) { return picked }
        return await matcher.pick(text, categories: categories, examples: examples) ?? fallback
    }

    /// Forgets anything worked out from his notes. Called when the journal locks.
    public static func forget() {
        Task { await matcher.forget() }
    }

    static let matcher = Matcher()

    /// Apple's built-in sentence embedding, kept on one actor so its model loads once and its work stays off the screen's thread.
    actor Matcher {
        private var embedding: NLEmbedding?
        private var loaded = false
        private var vectors: [String: [Double]] = [:]

        func forget() { vectors = [:] }

        private func vector(_ text: String) -> [Double]? {
            if let known = vectors[text] { return known }
            if !loaded { embedding = NLEmbedding.sentenceEmbedding(for: .english); loaded = true }
            guard let v = embedding?.vector(for: String(text.prefix(600))) else { return nil }
            vectors[text] = v
            return v
        }

        private static func cosine(_ a: [Double], _ b: [Double]) -> Double {
            var dot = 0.0, na = 0.0, nb = 0.0
            for i in 0..<min(a.count, b.count) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
            return na > 0 && nb > 0 ? dot / (na.squareRoot() * nb.squareRoot()) : 0
        }

        static func hits(_ text: String, _ cue: String) -> Bool {
            let pattern = "\\b" + NSRegularExpression.escapedPattern(for: cue) + "\\b"
            return text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
        }

        func pick(_ text: String, categories: [String], examples: [String: [String]]) -> String? {
            let note = vector(text)
            var best: (String, Double)?
            for name in categories {
                var refs = (examples[name] ?? []).prefix(40).map { $0 }
                refs += JournalSorter.seeds[name] ?? (examples[name]?.isEmpty ?? true ? [name] : [])
                var sims = note.map { n in refs.compactMap { vector($0) }.map { Matcher.cosine(n, $0) } } ?? []
                sims.sort(by: >)
                let top = sims.prefix(3)
                var score = top.isEmpty ? 0 : top.reduce(0, +) / Double(top.count)
                let cueHits = (JournalSorter.cues[name] ?? []).filter { Matcher.hits(text, $0) }.count
                score += min(0.24, 0.08 * Double(cueHits))
                if name == "Finance" {
                    // A money note nearly always says money: an amount, or a word for it. Without one, matching alone often drifts here.
                    let amount = text.range(of: #"\bR\s?\d|\d\s?k\b|\$\d|\bpercent\b|%"#, options: .regularExpression) != nil
                    if amount { score += 0.12 }
                    if !amount && cueHits == 0 { score -= 0.15 }
                }
                if name == "Feelings" {
                    let felt = JournalDigest.feeling(text)
                    score += min(0.15, 0.05 * Double(felt.positive + felt.negative))
                }
                if best == nil || score > best!.1 { best = (name, score) }
            }
            return best?.0
        }
    }
}

// MARK: - Reminders, on the iPhone

/// "Your thoughts this week" every Sunday at 7pm and "What you thought this month" on the 25th at 7pm. What they say never includes anything
/// from the journal: the highlights themselves are only ever on screen after Face ID.
public enum JournalReminders {
    static let setting = "journal.reminders"
    static let weekID = "journal.reminder.week"
    static let monthID = "journal.reminder.month"

    public static var supported: Bool {
        #if os(iOS)
        return true
        #else
        return false
        #endif
    }

    public static var enabled: Bool {
        get { UserDefaults.standard.object(forKey: setting) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: setting); apply() }
    }

    /// Sets the two repeating reminders up, or takes them down. Safe to call every time the journal opens.
    public static func apply() {
        #if os(iOS)
        let center = UNUserNotificationCenter.current()
        guard enabled else {
            center.removePendingNotificationRequests(withIdentifiers: [weekID, monthID])
            return
        }
        func add(_ id: String, _ title: String, _ body: String, _ when: DateComponents) {
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            content.threadIdentifier = "journal"
            center.add(UNNotificationRequest(identifier: id, content: content, trigger: UNCalendarNotificationTrigger(dateMatching: when, repeats: true)))
        }
        add(weekID, "Your thoughts this week", "Your weekly highlights are ready in your journal.", DateComponents(hour: JournalPeriod.hour, minute: 0, weekday: 1))
        add(monthID, "What you thought this month", "Your monthly highlights are ready in your journal.", DateComponents(day: 25, hour: JournalPeriod.hour, minute: 0))
        #endif
    }
}
