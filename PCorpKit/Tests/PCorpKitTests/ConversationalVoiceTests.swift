import Foundation
import XCTest
@testable import PCorpKit

// Conversational voice (2026-11-14): the shared logic both apps use -- reading Frank's reply aloud as it is written,
// knowing when Josh has finished, telling Josh from Frank's echo, ending by voice -- and the playback queue, played for real
// with a fake voice (short tones; no network, no ElevenLabs).
//   cd PCorpKit && swift test

private func check(_ name: String, _ cond: Bool, _ detail: Any = "", file: StaticString = #filePath, line: UInt = #line) {
    XCTAssertTrue(cond, "\(name)   [\(detail)]", file: file, line: line)
}

final class ConversationalVoiceTests: XCTestCase {
    func testSharedLogic() {

        // ---- speakable
        check("markdown is stripped", SpokenText.speakable("**Two things:**\n- Book the *venue*\n- Call [Sam](https://x.com)") == "Two things: Book the venue Call Sam", SpokenText.speakable("**Two things:**\n- Book the *venue*\n- Call [Sam](https://x.com)"))
        check("code blocks and error notes are not read", SpokenText.speakable("Here.\n```py\nx=1\n```\n[backend error: boom]") == "Here.")
        check("numbered list markers go", SpokenText.speakable("1. First\n2) Second") == "First Second")

        // ---- chunker: streams sentence by sentence
        var c = SpeechChunker()
        var got: [String] = []
        let reply = "Sure. The JD shoot is on the 25th, so we have eleven days. Want me to block prep time on Monday? I can also remind you about the iPhone rebuild."
        var partial = ""
        for ch in reply { partial.append(ch); got += c.feed(partial) }
        check("the first sentence is handed out on its own, as soon as it ends", got.first == "Sure.", got)
        check("nothing is handed out before a sentence has ended", { var d = SpeechChunker(); return d.feed("The JD shoot is on the").isEmpty }())
        got += c.flush(reply)
        check("every word is spoken exactly once, in order", got.joined(separator: " ") == reply, got)
        check("the last sentence comes with flush", got.last == "I can also remind you about the iPhone rebuild.", got)
        var d = SpeechChunker()
        let money = "It costs R2.5 million. Dr. Smith said e.g. Friday. Ok."
        let pieces = d.feed(money) + d.flush(money)
        check("decimals, Dr. and e.g. don't split a sentence", pieces == ["It costs R2.5 million.", "Dr. Smith said e.g. Friday.", "Ok."], pieces)
        var e = SpeechChunker()
        let list = "Three things:\n1. Venue\n2. Crew\n3. Music\nThat's it."
        let lp = e.feed(list) + e.flush(list)
        check("list lines are spoken without their numbers", lp.joined(separator: " ") == "Three things: Venue Crew Music That's it.", lp)
        var f = SpeechChunker()
        let code = "Run this:\n```\nswift build\n```\nThen restart."
        let cp = f.feed(code) + f.flush(code)
        check("code is skipped, the text around it isn't", cp.joined(separator: " ") == "Run this: Then restart.", cp)

        // ---- turn taking
        let T = TurnTaking.self
        check("a short breath doesn't end a turn", !T.shouldRespond(pause: 0.5, transcript: "Book the venue for Friday.", talkedSeconds: 3, verdict: .finished))
        check("a confirmed finished sentence is answered in under a second", T.shouldRespond(pause: 0.75, transcript: "Book the venue for Friday.", talkedSeconds: 3, verdict: .finished))
        check("without the model, a finished sentence waits 1.3 s", !T.shouldRespond(pause: 1.1, transcript: "Book the venue for Friday.", talkedSeconds: 3, verdict: nil) && T.shouldRespond(pause: 1.3, transcript: "Book the venue for Friday.", talkedSeconds: 3, verdict: nil))
        check("mid-thought ('and the other thing is') waits through a 3 s pause", !T.shouldRespond(pause: 3.0, transcript: "Book the venue and the other thing is", talkedSeconds: 5, verdict: nil) && !T.shouldRespond(pause: 3.0, transcript: "Book the venue and the other thing is", talkedSeconds: 5, verdict: .unfinished))
        check("but not forever", T.shouldRespond(pause: 4.0, transcript: "Book the venue and the other thing is", talkedSeconds: 5, verdict: nil))
        check("the model saying 'unfinished' buys time", !T.shouldRespond(pause: 2.5, transcript: "So I was thinking about the shoot", talkedSeconds: 5, verdict: .unfinished))
        check("a long answer gets more patience", !T.shouldRespond(pause: 2.0, transcript: "That's how the day went.", talkedSeconds: 40, verdict: nil) && T.shouldRespond(pause: 2.5, transcript: "That's how the day went.", talkedSeconds: 40, verdict: nil))
        check("a question gets answered quickly, even after a long ramble (Frank jumps in)", T.shouldRespond(pause: 0.8, transcript: "blah blah for ages. What do you think?", talkedSeconds: 50, verdict: nil))
        check("a question without a question mark still counts", T.looksLikeQuestion("so can you move the meeting to Friday") && T.looksLikeQuestion("we should push it, right"))
        check("a statement is not a question", !T.looksLikeQuestion("book the venue for Friday") && !T.looksLikeQuestion("what a day"))
        check("the model is only asked when it's unclear", T.worthAskingModel(pause: 0.5, transcript: "Book the venue for Friday", settings: .init()) && !T.worthAskingModel(pause: 0.5, transcript: "Book the venue and") && !T.worthAskingModel(pause: 0.5, transcript: "What time is it?") && !T.worthAskingModel(pause: 0.2, transcript: "Book the venue"))

        check("'that's what it is' is answered once the model says it's finished", T.shouldRespond(pause: 1.0, transcript: "that's what it is", talkedSeconds: 4, verdict: .finished))
        check("and the model is asked about it", T.worthAskingModel(pause: 0.5, transcript: "that's what it is"))
        check("'what time is it' is a question", T.looksLikeQuestion("okay what time is it"))
        // ---- echo / barge-in
        let frank = "The JD shoot is on the twenty fifth, so we have eleven days to prepare."
        check("Frank's own words coming back through the mic aren't an interruption", !EchoFilter.isBargeIn(heard: "the JD shoot is on the twenty fifth so we have", frankSaid: frank))
        check("'yeah, mm' while he talks doesn't stop him", !EchoFilter.isBargeIn(heard: "the JD shoot yeah mm okay", frankSaid: frank))
        check("three of Josh's own words in a row do", EchoFilter.isBargeIn(heard: "the JD shoot is moved to Thursday instead", frankSaid: frank) && !EchoFilter.isBargeIn(heard: "the JD shoot is moved to", frankSaid: frank))
        check("stray misheard words spread over a long reply don't add up to an interruption", !EchoFilter.isBargeIn(heard: "the JD shoot bun is on the twenty fifth so we hat have eleven dames to prepare the", frankSaid: frank))
        check("'wait' alone does", EchoFilter.isBargeIn(heard: "so we have wait", frankSaid: frank))
        check("Josh's opening words are kept when he cuts in", EchoFilter.joshsPart(heard: "the JD shoot is moved to Thursday actually", frankSaid: frank) == "moved to Thursday actually", EchoFilter.joshsPart(heard: "the JD shoot is moved to Thursday actually", frankSaid: frank))

        // ---- ending
        check("'that's all' ends without sending", ConversationExit.check("Okay, that's all.") == .endOnly)
        check("'thanks Frank' ends", ConversationExit.check("Thanks Frank") == .endOnly)
        check("a request then 'that's all' sends, then ends", ConversationExit.check("Book the venue for Friday, that's all") == .sendThenEnd)
        check("an ordinary sentence doesn't end anything", ConversationExit.check("That's all the footage from Monday, what next?") == .none)

        // ---- endpointer still behaves, and reports timing
        var ep = VoiceEndpointer()
        var t = 0.0
        while t < 1.0 { _ = ep.feed(rms: 0.0005, elapsed: t, transcript: ""); t += 0.02 }
        while t < 2.0 { _ = ep.feed(rms: 0.02, elapsed: t, transcript: "hello"); t += 0.02 }
        check("first and last voice times are reported", (ep.firstVoiceAt ?? 0) >= 0.99 && (ep.firstVoiceAt ?? 0) < 1.05 && ep.lastVoiceAt >= 1.97, (ep.firstVoiceAt as Any, ep.lastVoiceAt))
    }

    @MainActor
    func testPlaybackQueue() async {

        // 1. A reply written in pieces is spoken in order, starting before it's complete.
        let v = FakeVoice()
        var finished = 0
        v.onReplyFinished = { finished += 1 }
        v.beginReply()
        check("waiting for the first sentence counts as speaking, not playing", v.isSpeaking && !v.isPlaying)
        v.enqueue("One.")
        let startedEarly = await waitUntil(2) { v.isPlaying }
        check("the first sentence plays while the rest is still being written", startedEarly && v.spokenText == "One.", v.spokenText)
        v.enqueue("Two."); v.enqueue("Three."); v.enqueue("Four.")
        v.endReply()
        _ = await waitUntil(5) { !v.isSpeaking }
        check("every piece is spoken once, in order", v.spokenText == "One. Two. Three. Four." && v.fetched == ["One.", "Two.", "Three.", "Four."], (v.spokenText, v.fetched))
        check("one fetch at a time (pieces are fetched ahead while one plays)", v.maxInFlight == 1, v.maxInFlight)
        check("the end of the reply is reported once", finished == 1, finished)

        // 2. Stopping (Josh talks over Frank) silences him at once and isn't reported as finished.
        let s = FakeVoice()
        var sFinished = 0
        s.onReplyFinished = { sFinished += 1 }
        s.beginReply(); s.enqueue("Alpha."); s.enqueue("Bravo."); s.enqueue("Charlie.")
        _ = await waitUntil(2) { s.isPlaying }
        s.stop()
        check("stop silences him straight away", !s.isSpeaking && !s.isPlaying)
        try? await Task.sleep(nanoseconds: 800_000_000)
        check("nothing more plays after a stop, even audio already fetched", s.spokenText == "Alpha." && !s.isPlaying, s.spokenText)
        check("a stopped reply isn't reported as finished", sFinished == 0)
        s.enqueue("Delta.")
        check("pieces arriving after a stop are ignored", !s.isSpeaking)

        // 3. A piece whose voice fails is skipped; the rest still play.
        let f = FakeVoice()
        f.fail = ["Bad."]
        f.beginReply(); f.enqueue("Good."); f.enqueue("Bad."); f.enqueue("Fine."); f.endReply()
        _ = await waitUntil(5) { !f.isSpeaking }
        check("a failed piece is skipped and the rest is spoken", f.spokenText == "Good. Fine." && f.errorMessage != nil, (f.spokenText, f.errorMessage as Any))

        // 4. An empty reply (only tool work, nothing to say) still ends, so the conversation passes back to Josh.
        let e = FakeVoice()
        var eFinished = 0
        e.onReplyFinished = { eFinished += 1 }
        e.beginReply(); e.endReply()
        check("a reply with nothing to say ends straight away", !e.isSpeaking && eFinished == 1)

        // 5. A new reply replaces one in progress; the old one's late audio never plays.
        let r = FakeVoice()
        r.delay = 400_000_000
        r.beginReply(); r.enqueue("Old.")
        try? await Task.sleep(nanoseconds: 100_000_000)
        r.beginReply(); r.enqueue("New."); r.endReply()
        _ = await waitUntil(5) { !r.isSpeaking }
        check("a superseded reply's late audio never plays", r.spokenText == "New.", r.spokenText)

        // 6. Streaming end to end: chunker + speaker on a reply arriving a few characters at a time.
        let x = FakeVoice()
        var chunker = SpeechChunker()
        let reply = "Got it. I moved the JD prep to Monday at nine. Want me to tell the crew?"
        x.beginReply()
        var partial = ""
        var firstAudioAt: Int?
        for (i, ch) in reply.enumerated() {
            partial.append(ch)
            for p in chunker.feed(partial) { x.enqueue(p) }
            try? await Task.sleep(nanoseconds: 15_000_000)
            if firstAudioAt == nil, x.isPlaying { firstAudioAt = i }
        }
        for p in chunker.flush(reply) { x.enqueue(p) }
        x.endReply()
        _ = await waitUntil(5) { !x.isSpeaking }
        check("streamed reply: speaking starts before Frank finishes writing", (firstAudioAt ?? reply.count) < reply.count / 2, firstAudioAt as Any)
        check("streamed reply: all of it is spoken, in order", x.spokenText == reply, x.spokenText)
    }
}

/// A short quiet tone as WAV data (no network, no ElevenLabs).
private func wav(seconds: Double) -> Data {
    let rate = 16000, n = Int(Double(rate) * seconds)
    var d = Data()
    func u32(_ v: UInt32) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 4)) }
    func u16(_ v: UInt16) { var x = v.littleEndian; d.append(Data(bytes: &x, count: 2)) }
    d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + n * 2)); d.append("WAVEfmt ".data(using: .ascii)!)
    u32(16); u16(1); u16(1); u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
    d.append("data".data(using: .ascii)!); u32(UInt32(n * 2))
    for i in 0..<n { u16(UInt16(bitPattern: Int16(sin(Double(i) * 0.05) * 300))) }
    return d
}

@MainActor private final class FakeVoice: ReplySpeaker {
    var fetched: [String] = []
    var inFlight = 0, maxInFlight = 0
    var fail: Set<String> = []
    var delay: UInt64 = 150_000_000
    override func fetchAudio(for text: String) async throws -> Data {
        fetched.append(text); inFlight += 1; maxInFlight = max(maxInFlight, inFlight)
        defer { inFlight -= 1 }
        try await Task.sleep(nanoseconds: delay)
        if fail.contains(text) { throw NSError(domain: "fake", code: 1) }
        return wav(seconds: 0.25)
    }
}

@MainActor private func waitUntil(_ seconds: Double, _ cond: () -> Bool) async -> Bool {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { if cond() { return true }; try? await Task.sleep(nanoseconds: 20_000_000) }
    return cond()
}

