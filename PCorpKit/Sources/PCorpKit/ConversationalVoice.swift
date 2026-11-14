import Foundation

// Conversational voice (2026-11-14). Josh: talking to Frank felt like "send a voice message, wait for a long reply".
// He wants a back-and-forth: Frank should know when he's talking, when he's paused to think, and when he's done; not cut
// him off during a long answer, but jump in when it's clearly his turn; and stop talking when Josh talks over him.
//
// Everything in this file is pure logic (no audio, no network, no clock of its own) so it can be tested, and the Mac and
// iPhone apps share it. The apps feed it what the mic and the recognizer report.

// MARK: - Reading Frank's reply out loud as it is written

/// Turns Frank's reply into text worth speaking: markdown, links, code and bracketed system notes removed.
public enum SpokenText {
    public static func speakable(_ text: String) -> String {
        var s = text
        // Code blocks are for reading, not hearing.
        s = s.replacingOccurrences(of: #"```[\s\S]*?(```|$)"#, with: " ", options: .regularExpression)
        // "[connection error: ...]" / "[backend error: ...]" notes the app adds to the transcript.
        s = s.replacingOccurrences(of: #"\[[^\]\n]*(error|Error)[^\]\n]*\]"#, with: " ", options: .regularExpression)
        // [title](url) -> title; bare links -> "the link".
        s = s.replacingOccurrences(of: #"\[([^\]\n]+)\]\([^)\s]+\)"#, with: "$1", options: .regularExpression)
        s = s.replacingOccurrences(of: #"https?://\S+"#, with: "the link", options: .regularExpression)
        // Headings, bullets, numbered items, quotes at the start of a line.
        s = s.replacingOccurrences(of: #"(?m)^\s{0,3}(#{1,6}\s+|[-*•+]\s+|\d{1,3}[.)]\s+|>\s?)"#, with: "", options: .regularExpression)
        // Emphasis and inline code markers.
        s = s.replacingOccurrences(of: #"(\*\*|__|\*|`|~~)"#, with: "", options: .regularExpression)
        s = s.replacingOccurrences(of: #"(?m)^\s*[-=|:]{3,}\s*$"#, with: " ", options: .regularExpression)  // rules / table lines
        s = s.replacingOccurrences(of: "|", with: ", ")
        s = s.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// True when there is nothing to say out loud (only punctuation or symbols).
    static func isSilent(_ text: String) -> Bool {
        !text.unicodeScalars.contains { CharacterSet.alphanumerics.contains($0) }
    }
}

/// Hands out Frank's reply a sentence at a time while it is still being written, so he starts speaking after the first
/// sentence instead of after the whole reply. Feed it the WHOLE reply so far each time it grows; it returns only the newly
/// finished pieces, already cleaned for speaking.
public struct SpeechChunker {
    /// A piece shorter than this is held and joined to the next one ("Sure." on its own sounds clipped), except the first.
    public var minimumChars = 24
    private var consumed = 0          // characters of the raw reply already handed out
    private var heldBack = ""         // a too-short piece waiting for the next
    private var handedOutAny = false
    private var inCodeBlock = false

    public init() {}

    private static let abbreviations: Set<String> = ["mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "approx", "no", "jan", "feb", "aug", "sept", "oct", "nov", "dec"]

    /// New pieces to speak, given the whole reply so far.
    public mutating func feed(_ fullText: String) -> [String] {
        let chars = Array(fullText)
        if chars.count < consumed { consumed = 0; heldBack = ""; inCodeBlock = false }  // the reply was replaced: start again
        var out: [String] = []
        var start = consumed
        var i = consumed
        while i < chars.count {
            // Code blocks: never cut inside one; the whole block is dropped when spoken.
            if chars[i] == "`", i + 2 < chars.count, chars[i + 1] == "`", chars[i + 2] == "`" {
                inCodeBlock.toggle()
                i += 3
                continue
            }
            if inCodeBlock { i += 1; continue }
            if Self.isBoundary(chars, at: i) {
                let end = i + 1
                emit(String(chars[start..<end]), into: &out, final: false)
                start = end
                consumed = end
            }
            i += 1
        }
        return out
    }

    /// Whatever is left once the reply is complete.
    public mutating func flush(_ fullText: String) -> [String] {
        var out = feed(fullText)
        let chars = Array(fullText)
        let rest = consumed < chars.count ? String(chars[consumed...]) : ""
        consumed = chars.count
        emit(rest, into: &out, final: true)
        return out
    }

    private mutating func emit(_ raw: String, into out: inout [String], final: Bool) {
        let piece = SpokenText.speakable(raw)
        let joined = [heldBack, piece].filter { !$0.isEmpty }.joined(separator: " ")
        if joined.isEmpty || SpokenText.isSilent(joined) {
            if final { heldBack = "" }
            return
        }
        if !final && handedOutAny && joined.count < minimumChars {
            heldBack = joined
            return
        }
        heldBack = ""
        handedOutAny = true
        out.append(joined)
    }

    /// A sentence ends at . ! ? … followed by a space or line break, or at a line break (list items, paragraphs).
    static func isBoundary(_ chars: [Character], at i: Int) -> Bool {
        let c = chars[i]
        if c == "\n" { return i > 0 }
        guard ".!?…".contains(c) else { return false }
        guard i + 1 < chars.count else { return false }       // the next character hasn't arrived: can't tell yet
        let next = chars[i + 1]
        guard next == " " || next == "\n" else { return false }  // a closing quote or bracket: the sentence ends at a later break
        if c == "." {
            if i > 0, chars[i - 1].isNumber { return false }  // "1." list numbers, "R2.5" (the "." of 2.5 is followed by a digit anyway)
            var j = i - 1
            var word = ""
            while j >= 0, chars[j].isLetter || chars[j] == "." { word = String(chars[j]) + word; j -= 1 }
            if abbreviations.contains(word.lowercased()) { return false }
            if word.count == 1, word.first?.isUppercase == true { return false }  // initials: "J. Peters"
        }
        return true
    }
}

// MARK: - Knowing when Josh has finished

/// Decides, at each moment of silence, whether Josh has finished and it's Frank's turn. A fixed timer can't tell "thinking"
/// from "done", so this looks at WHAT was said as well as how long the pause is:
///   * an unfinished-sounding end ("…and the other thing is", "…because") waits up to `unfinishedPause`, however long;
///   * a question ("…what do you think?") is answered after `questionPause` -- Frank jumps in, even mid-ramble;
///   * a finished-sounding end waits `likelyDonePause`, or only `finishedPause` once the small model has confirmed it;
///   * the longer Josh has been talking, the more patience (`longTalkExtra`) -- except after a question.
public enum TurnTaking {
    public struct Settings {
        public var minimumPause: TimeInterval = 0.7
        public var questionPause: TimeInterval = 0.8
        public var finishedPause: TimeInterval = 0.9
        public var likelyDonePause: TimeInterval = 1.5
        public var unfinishedPause: TimeInterval = 4.0
        public var longTalkSeconds: TimeInterval = 15
        public var longTalkExtra: TimeInterval = 1.0
        /// When to ask the small model, so its answer is back by the time the pause is long enough to act on.
        public var askModelAfter: TimeInterval = 0.4
        public init() {}
    }

    public enum Verdict: String, Codable, Equatable { case finished, unfinished }

    /// True when Frank should answer now.
    public static func shouldRespond(pause: TimeInterval, transcript: String, talkedSeconds: TimeInterval,
                                     verdict: Verdict?, settings: Settings = Settings()) -> Bool {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, pause >= settings.minimumPause else { return false }
        let extra = talkedSeconds > settings.longTalkSeconds ? settings.longTalkExtra : 0
        if VoiceEndpointer.looksUnfinished(text) {
            return pause >= settings.unfinishedPause + extra
        }
        if endsOnMaybeUnfinishedWord(text) && verdict != .finished {
            return pause >= settings.unfinishedPause + extra   // "…the other thing is" -- unless the model heard "that's what it is"
        }
        if looksLikeQuestion(text) {
            return pause >= settings.questionPause
        }
        switch verdict {
        case .finished: return pause >= settings.finishedPause + extra / 2
        case .unfinished: return pause >= settings.unfinishedPause + extra
        case nil: return pause >= settings.likelyDonePause + extra
        }
    }

    /// True when it's worth asking the small model about this pause (the obvious cases don't need it).
    public static func worthAskingModel(pause: TimeInterval, transcript: String, settings: Settings = Settings()) -> Bool {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard pause >= settings.askModelAfter, text.split(separator: " ").count >= 2 else { return false }
        return !VoiceEndpointer.looksUnfinished(text) && !looksLikeQuestion(text)
    }

    /// Words that USUALLY mean more is coming but can end a sentence ("that's what it is"). Apple's recognizer often leaves the
    /// full stop off while you talk, so these wait the long pause unless the small model says the sentence is finished.
    static let maybeUnfinishedWords: Set<String> = ["is", "was", "are", "were", "be", "like", "just", "that", "think", "want", "need", "going", "gonna", "maybe", "probably", "basically", "where", "what", "how", "why", "who"]

    static func endsOnMaybeUnfinishedWord(_ text: String) -> Bool {
        guard let last = text.last, !".?!…".contains(last) else { return false }
        return normalisedWords(text).last.map { maybeUnfinishedWords.contains($0) } ?? false
    }

    private static let fillers: Set<String> = ["so", "and", "okay", "ok", "frank", "hey", "but", "also", "um", "uh", "like", "well", "alright", "right", "oh"]

    private static let questionStarts = ["what", "whats", "what's", "how", "hows", "how's", "why", "when", "where", "who", "which",
                                         "can you", "could you", "would you", "will you", "should i", "should we", "do you", "did you",
                                         "is it", "is there", "are we", "are you", "have you", "any idea", "can we", "shall we"]
    private static let questionEnds = ["right", "you know what i mean", "what do you think", "thoughts", "make sense", "agreed", "yeah"]

    /// The last sentence is a question to Frank: ends in "?", starts like one, or ends like one ("…, right").
    public static func looksLikeQuestion(_ transcript: String) -> Bool {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasSuffix("?") { return true }
        let last = text.split(whereSeparator: { ".!?\n".contains($0) }).last.map(String.init) ?? text
        let allWords = normalisedWords(last)
        let words = Array(allWords.drop(while: { fillers.contains($0) }))   // "so can you…", "okay what's…"
        guard !words.isEmpty else { return false }
        let joined = words.joined(separator: " ")
        if joined.hasPrefix("what a ") || joined.hasPrefix("how nice") { return false }   // exclamations
        if questionStarts.contains(where: { joined.hasPrefix($0 + " ") }) && words.count >= 3 { return true }
        let whole = allWords.joined(separator: " ")
        return questionEnds.contains(where: { whole.hasSuffix(" " + $0) }) && allWords.count >= 4
    }
}

/// Lower-case words with punctuation removed (apostrophes kept).
func normalisedWords(_ text: String) -> [String] {
    text.lowercased()
        .replacingOccurrences(of: "’", with: "'")
        .split(whereSeparator: { $0.isWhitespace || ",.;:!?…\"()-–—".contains($0) })
        .map { String($0).trimmingCharacters(in: CharacterSet(charactersIn: "'")) }
        .filter { !$0.isEmpty }
}

// MARK: - Josh talking over Frank

/// While Frank is speaking, the mic stays on so Josh can cut in. On the Mac's speakers the mic also hears Frank, so the
/// recognizer transcribes HIS words too. This separates the two by the words themselves: anything Frank is saying (or just
/// said) is his echo; other words are Josh. Small acknowledgements ("yeah", "mm", "okay") don't stop Frank -- people say
/// those while listening. "Stop", "wait", "hold on" stop him straight away.
public enum EchoFilter {
    static let acknowledgements: Set<String> = ["yeah", "yes", "yep", "yup", "mm", "mhm", "mmm", "hmm", "uh", "um", "uhm", "okay", "ok",
                                                "right", "sure", "huh", "uh-huh", "ah", "oh", "nice", "cool", "wow", "alright", "true", "exactly"]
    static let stopWords: Set<String> = ["stop", "wait", "hold", "hang", "pause", "frank", "sorry", "actually", "no"]

    /// How many of the most recent heard words are looked at. Josh talking over Frank gives a RUN of his own words; the
    /// recognizer mishearing Frank's echo gives the odd stray word. Counting only recent words keeps strays from adding up
    /// over a long reply into a false interruption.
    static let recentWords = 5
    static let wordsNeeded = 3

    /// Words too common to say whose they are ("to", "the"): left out of the count either way.
    static let neutral: Set<String> = ["to", "the", "a", "an", "is", "are", "was", "and", "of", "in", "on", "it", "it's", "so", "we",
                                       "i", "you", "that", "this", "for", "at", "be", "with", "but", "or", "if", "as", "my", "your", "do"]

    /// For each meaningful heard word (its index among all heard words): is it Josh's (not Frank's echo, not a passing "yeah")?
    static func marks(heard: String, frankSaid: String) -> [(index: Int, word: String, mine: Bool)] {
        let frank = Set(normalisedWords(frankSaid))
        return normalisedWords(heard).enumerated().compactMap { index, word in
            neutral.contains(word) ? nil : (index, word, !frank.contains(word) && !acknowledgements.contains(word))
        }
    }

    /// True when Josh has started talking over Frank: at least `wordsNeeded` of the last `recentWords` heard words are his,
    /// or "stop" / "wait" / "hold on" among the last three.
    public static func isBargeIn(heard: String, frankSaid: String) -> Bool {
        let m = marks(heard: heard, frankSaid: frankSaid)
        let recent = m.suffix(recentWords)
        if m.suffix(3).contains(where: { $0.mine && stopWords.contains($0.word) }) { return true }
        return recent.filter(\.mine).count >= wordsNeeded
    }

    /// The index (in heard words) where Josh's part starts: the first of his words in the recent window.
    public static func joshStartIndex(heard: String, frankSaid: String) -> Int? {
        marks(heard: heard, frankSaid: frankSaid).suffix(recentWords).first(where: \.mine)?.index
    }

    /// What the mic heard, from Josh's first word on (so his opening words aren't lost when he cuts in).
    public static func joshsPart(heard: String, frankSaid: String) -> String {
        guard let first = joshStartIndex(heard: heard, frankSaid: frankSaid) else { return "" }
        let tokens = heard.split(whereSeparator: { $0.isWhitespace })
        // normalisedWords splits on a little more than whitespace; map back by counting normalised words per token.
        var seen = 0
        for (i, token) in tokens.enumerated() {
            let n = normalisedWords(String(token)).count
            if seen + n > first { return tokens[i...].joined(separator: " ") }
            seen += n
        }
        return ""
    }

    /// Number of words (as counted here) in a piece of text.
    public static func wordCount(_ text: String) -> Int { normalisedWords(text).count }
}

// MARK: - Ending the conversation by voice

public enum ConversationExit: Equatable {
    case none
    /// He only said goodbye: end without sending anything.
    case endOnly
    /// He said something, then goodbye: send it, and end once Frank has answered.
    case sendThenEnd

    static let phrases = ["that's all", "that's it", "that is all", "that'll be all", "thanks frank", "thank you frank", "goodbye",
                          "bye frank", "stop listening", "end conversation", "end the conversation", "we're done", "i'm done", "talk later"]

    public static func check(_ transcript: String) -> ConversationExit {
        let words = normalisedWords(transcript)
        let joined = words.joined(separator: " ")
        guard let phrase = phrases.first(where: { joined.hasSuffix($0) }) else { return .none }
        let before = words.count - phrase.split(separator: " ").count
        return before <= 2 ? .endOnly : .sendThenEnd   // "okay, that's all" / "thanks, that's all" are just goodbyes
    }
}
