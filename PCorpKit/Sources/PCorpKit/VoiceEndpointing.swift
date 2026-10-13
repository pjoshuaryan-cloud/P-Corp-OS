import Foundation

/// Decides when push-to-talk should stop listening (2026-10-11).
///
/// Why this exists: the iPhone's voice input used to stop 1.2 s after the mic last heard anything above a FIXED volume
/// (0.002), numbers carried over from the Mac and never checked on the phone. Any pause longer than that mid-sentence
/// ended the recording and sent half a thought ("Frank I want you to"). A fixed volume is also wrong in the other
/// direction: in a noisy room the "silence" never drops below it, so the recording would never stop by itself.
///
/// This version:
///   * learns the room, continuously: the background level is the quietest quarter of the last `windowSeconds` of audio
///     (speech has gaps; the quiet quarter is the room), and "voice" is what is clearly above it (`floorMultiplier` times
///     that, clamped between `minThreshold` and `maxThreshold`). A quiet room, a noisy one, or a room that changes while
///     you talk all work;
///   * also counts the recognizer producing NEW WORDS as proof you are still talking, so a mic level that was misjudged
///     (a very quiet voice from the first instant) can't make it stop early or never stop;
///   * waits `pauseSeconds` of silence after you have spoken, and longer (`danglingPauseSeconds`) when what it has so far
///     ends mid-thought: a trailing "to", "and", "the", a comma, or nothing transcribed yet;
///   * gives up after `noSpeechSeconds` if it never hears you, and after `maxSeconds` regardless.
///
/// Pure logic (no audio, no clock of its own): the caller feeds it the level and the elapsed time, so it can be tested.
public struct VoiceEndpointer {
    public struct Settings {
        public var calibrationSeconds: TimeInterval = 0.4
        public var windowSeconds: TimeInterval = 3.0
        public var minThreshold: Double = 0.002
        public var maxThreshold: Double = 0.02
        public var floorMultiplier: Double = 3.0
        public var pauseSeconds: TimeInterval = 2.5
        public var danglingPauseSeconds: TimeInterval = 4.0
        public var noSpeechSeconds: TimeInterval = 10.0
        public var maxSeconds: TimeInterval = 60.0
        public init() {}
    }

    public enum StopReason: Equatable {
        case pause(seconds: TimeInterval)
        case noSpeech
        case timeLimit
    }

    public let settings: Settings
    public private(set) var threshold: Double
    public private(set) var hasDetectedSpeech = false
    private var window: [(t: TimeInterval, rms: Double)] = []
    private var lastWordCount = 0
    private var lastVoiceAt: TimeInterval = 0

    public init(settings: Settings = Settings()) {
        self.settings = settings
        self.threshold = settings.minThreshold
    }

    /// Words that can't end a sentence, so one of them last means more is coming. (Words that CAN end one -- "it", "you",
    /// "this", "me" -- are left out on purpose: they'd make every finished sentence wait the long pause.)
    static let danglingWords: Set<String> = [
        "to", "and", "the", "a", "an", "my", "your", "our", "their", "his", "her", "its", "of", "for", "with", "so", "but", "because",
        "in", "on", "at", "if", "when", "then", "or", "as", "than", "by", "from", "into", "about", "also", "which", "would", "could",
        "should", "i", "i'd", "i'll", "i'm", "i've", "um", "uh", "er", "umm", "uhh", "hmm",
    ]

    /// True when the text so far looks like it stopped mid-thought (or hasn't arrived yet).
    public static func looksUnfinished(_ transcript: String) -> Bool {
        let text = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let last = text.last else { return true }  // nothing transcribed yet: the recognizer may just be catching up
        if ".?!…".contains(last) { return false }
        if ",;:-–—".contains(last) { return true }
        let word = text.split(whereSeparator: { $0.isWhitespace }).last.map { String($0).lowercased().trimmingCharacters(in: .punctuationCharacters.subtracting(CharacterSet(charactersIn: "'’"))) } ?? ""
        return danglingWords.contains(word.replacingOccurrences(of: "’", with: "'"))
    }

    /// Call for every audio buffer. `rms` is the buffer's level, `elapsed` seconds since recording began, `transcript` what
    /// has been recognized so far. Returns a reason when listening should stop.
    public mutating func feed(rms: Double, elapsed: TimeInterval, transcript: String) -> StopReason? {
        if elapsed >= settings.maxSeconds { return .timeLimit }

        // New words from the recognizer = you are talking (counted by words, not letters: punctuation or a corrected
        // spelling arriving after you stopped must not restart the wait).
        let words = transcript.split(whereSeparator: { $0.isWhitespace }).count
        if words > lastWordCount {
            lastWordCount = words
            hasDetectedSpeech = true
            lastVoiceAt = elapsed
        }

        window.append((elapsed, rms))
        window.removeAll { elapsed - $0.t > settings.windowSeconds }
        if elapsed < settings.calibrationSeconds { return nil }  // too early to know the room
        let sorted = window.map(\.rms).sorted()
        let floor = sorted[min(sorted.count - 1, sorted.count / 4)]  // the quietest quarter ~ the room
        threshold = min(max(floor * settings.floorMultiplier, settings.minThreshold), settings.maxThreshold)

        if rms > threshold {
            hasDetectedSpeech = true
            lastVoiceAt = elapsed
        }

        if !hasDetectedSpeech {
            return elapsed >= settings.noSpeechSeconds ? .noSpeech : nil
        }
        let limit = Self.looksUnfinished(transcript) ? settings.danglingPauseSeconds : settings.pauseSeconds
        return elapsed - lastVoiceAt > limit ? .pause(seconds: limit) : nil
    }
}
