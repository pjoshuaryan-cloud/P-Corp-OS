"""Conversational voice (2026-11-14).

Josh: talking to Frank felt like "send a voice message, wait for a long reply". Two backend pieces make it a back-and-forth:

1. VOICE_STYLE_NOTE -- added to Frank's instructions only on a turn Josh SPOKE (the app sends "voice": true). Frank answers like
   he's on a call: short, no lists or markdown, one thing at a time, and a question back when it helps. The text still shows on
   screen as usual.

2. turn_check -- the "has he finished?" check. At a pause, the app sends what Josh has said so far; a small, fast model
   (Claude Haiku 5.5) answers "finished" or "unfinished". The app combines that with the pause length and the words themselves
   (PCorpKit ConversationalVoice.swift, TurnTaking) so Frank doesn't cut Josh off mid-thought, but answers quickly when he's done.
   OFF unless VOICE_TURN_CHECK_ENABLED is set: it is API spend, and Josh approves spend first. When off, the app decides from the
   pause and the words alone. Estimated cost: ~300 input + ~3 output tokens per check at $0.10 / $0.50 per million tokens
   ~= $0.00003 a check, a few cents per thousand pauses.
"""
from __future__ import annotations

import asyncio
import os

from anthropic import AsyncAnthropic

VOICE_STYLE_NOTE = """

## This turn was spoken
Josh said this out loud and will HEAR your reply (read by a text-to-speech voice), in a back-and-forth conversation. Talk like
you're on a call with him:
- Keep it short: usually one to three sentences. Give the answer first, then stop.
- No lists, headings, tables, bullet points, markdown, links or emoji -- they can't be heard. Say things in plain sentences.
- One thing at a time. If there is more, offer it ("Want the rest?") instead of saying it all.
- If you need something from him to continue, ask one short question and stop.
- Numbers and times as people say them ("about two fifty", "half past three").
- If a tool will take a moment, say one short line first ("Let me check the calendar.").
- If he asked for something long (a document, an email, a plan), make it with your tools as usual and say in a sentence what you did.
"""

TURN_CHECK_MODEL = "claude-haiku-5-5"
TURN_CHECK_TIMEOUT_SECONDS = 2.5
MAX_TRANSCRIPT_CHARS = 1500

TURN_CHECK_SYSTEM = """You help a voice assistant named Frank know when to speak. Josh is talking to Frank and has just paused.
You get what Josh has said so far (live speech-to-text, so punctuation may be missing or wrong) and, for context, the last
thing Frank said. Decide if Josh has finished his turn and is waiting for Frank, or is mid-thought and will keep talking.

FINISHED: a complete request, question or statement that Frank can answer now.
MORE: the sentence or thought is unfinished, he is listing things and hasn't closed the list, he trailed off on a filler or
connecting word, or he announced more is coming ("two things", "and also", "the other thing is").
When unsure, answer MORE: cutting Josh off is worse than waiting a moment.

Answer with one word: FINISHED or MORE."""


def turn_check_enabled() -> bool:
    return os.environ.get("VOICE_TURN_CHECK_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _verdict_from(text: str) -> str | None:
    word = text.strip().upper()
    if word.startswith("FINISHED"):
        return "finished"
    if word.startswith("MORE"):
        return "unfinished"
    return None


async def turn_check(transcript: str, frank_last: str | None, client: AsyncAnthropic | None = None) -> dict:
    """{"enabled": bool, "verdict": "finished" | "unfinished" | None}. Never raises: any failure (off, no key, slow, odd answer)
    returns verdict None, and the app falls back to the pause and the words alone."""
    if not turn_check_enabled():
        return {"enabled": False, "verdict": None}
    transcript = (transcript or "").strip()[-MAX_TRANSCRIPT_CHARS:]
    if not transcript:
        return {"enabled": True, "verdict": None}
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {"enabled": True, "verdict": None}
        client = AsyncAnthropic(api_key=api_key)
    context = (frank_last or "").strip()[-400:]
    user = (f"Frank last said: {context}\n\n" if context else "") + f"Josh so far: {transcript}"
    try:
        response = await asyncio.wait_for(
            client.messages.create(
                model=TURN_CHECK_MODEL,
                max_tokens=5,
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                system=TURN_CHECK_SYSTEM,
                messages=[{"role": "user", "content": user}],
            ),
            timeout=TURN_CHECK_TIMEOUT_SECONDS,
        )
    except Exception as error:  # slow, rate-limited, refused, network: the app decides without it
        print(f"[voice turn-check] no verdict: {type(error).__name__}: {error}")
        return {"enabled": True, "verdict": None}
    if getattr(response, "stop_reason", None) == "refusal":
        return {"enabled": True, "verdict": None}
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return {"enabled": True, "verdict": _verdict_from(text)}
