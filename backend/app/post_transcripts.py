"""
POST (2026-09-27, Phase 6) -- dialogue transcription. Premiere Pro has
its own real, documented, on-device transcription API reachable via
UXP (`ppro.Transcript`, confirmed via Adobe's own current reference
docs and a real hands-on spike against Josh's installed Premiere Beta
build) -- real word-level timing, real confidence scores, and real
speaker diarization, running locally via an installed language pack
(free, included with Josh's Creative Cloud subscription, no per-minute
API cost). This means Phase 6 needs NO new STT integration of its own:
the plugin does the actual transcription and reports Adobe's own real
JSON back here; this file only summarizes and reformats that real
output, matching compute_media_report's own "deterministic Python
aggregation, no LLM in the path" discipline -- Premiere already did the
real transcription work, this never re-derives or second-guesses it.

Adobe's own published JSON schema (confirmed via the real spec file at
AdobeDocs/uxp-premiere-pro-samples, and independently confirmed live
via the hands-on spike -- the two matched exactly):
    { "language": str, "segments": [Segment], "speakers": [Speaker] }
    Segment: { "speaker": uuid, "start": float, "duration": float, "words": [Word] }
    Word: { "text": str, "start": float, "duration": float, "confidence": float,
             "type": "word"|"punctuation", "eos": bool, "tags": ["profanity"|"filler", ...] }
    Speaker: { "id": uuid, "name": str }  -- confirmed live: Premiere's own
              default, unlabeled speaker name is literally "Unknown", not
              "Speaker 1" as might be assumed.
"""

from typing import Any


def summarize_transcript(transcript_json: dict) -> dict:
    """Real counts from Adobe's own real per-word tags -- never
    estimated, never re-run through any model. word_count only counts
    'word'-type entries (excludes standalone punctuation tokens)."""
    segments = transcript_json.get("segments", [])
    speakers = transcript_json.get("speakers", [])
    word_count = 0
    has_profanity = False
    has_filler_words = False
    for segment in segments:
        for word in segment.get("words", []):
            if word.get("type") == "word":
                word_count += 1
            tags = word.get("tags") or []
            if "profanity" in tags:
                has_profanity = True
            if "filler" in tags:
                has_filler_words = True
    return {
        "language": transcript_json.get("language"),
        "word_count": word_count,
        "speaker_count": len(speakers),
        "has_profanity": has_profanity,
        "has_filler_words": has_filler_words,
    }


def format_readable_transcript(transcript_json: dict) -> str:
    """Plain, speaker-grouped text for display -- never a word-by-word
    timeline UI (that's real caption-editing territory, out of scope).
    Consecutive segments from the same speaker are merged into one
    paragraph; punctuation-type tokens are appended directly to the
    preceding word with no extra space, matching normal text
    conventions."""
    speakers_by_id = {s["id"]: s.get("name") or "Unknown" for s in transcript_json.get("speakers", [])}
    lines: list[str] = []
    current_speaker = None
    current_words: list[str] = []

    def flush() -> None:
        if current_words:
            lines.append(f"{speakers_by_id.get(current_speaker, 'Unknown')}: {''.join(current_words)}")

    for segment in transcript_json.get("segments", []):
        speaker = segment.get("speaker")
        if speaker != current_speaker:
            flush()
            current_speaker = speaker
            current_words = []
        for word in segment.get("words", []):
            text = word.get("text", "")
            if word.get("type") == "punctuation" or not current_words:
                current_words.append(text)
            else:
                current_words.append(f" {text}")
    flush()
    return "\n\n".join(lines)


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = round(max(seconds, 0) * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_srt(transcript_json: dict, max_words_per_caption: int = 8, max_caption_seconds: float = 4.0) -> str:
    """Re-chunks the real word-level timing into readable caption
    blocks -- a whole Segment can span many seconds/a full sentence,
    too long for one subtitle card. max_words_per_caption/
    max_caption_seconds are stated, adjustable chunking parameters, not
    a claim about ideal subtitle pacing. Standard SRT format: sequential
    index, 'HH:MM:SS,mmm --> HH:MM:SS,mmm', text, blank line."""
    blocks: list[tuple[float, float, str]] = []
    chunk_words: list[dict] = []

    def flush_chunk() -> None:
        if not chunk_words:
            return
        start = chunk_words[0]["start"]
        last = chunk_words[-1]
        end = last["start"] + last["duration"]
        text_parts: list[str] = []
        for w in chunk_words:
            if w["type"] == "punctuation" or not text_parts:
                text_parts.append(w["text"])
            else:
                text_parts.append(f" {w['text']}")
        blocks.append((start, end, "".join(text_parts)))

    for segment in transcript_json.get("segments", []):
        for word in segment.get("words", []):
            if chunk_words:
                chunk_start = chunk_words[0]["start"]
                would_exceed_time = (word["start"] + word["duration"] - chunk_start) > max_caption_seconds
                word_count_so_far = sum(1 for w in chunk_words if w["type"] == "word")
                if would_exceed_time or word_count_so_far >= max_words_per_caption:
                    flush_chunk()
                    chunk_words = []
            chunk_words.append(word)
            if word.get("eos"):
                flush_chunk()
                chunk_words = []
    flush_chunk()

    lines: list[str] = []
    for index, (start, end, text) in enumerate(blocks, start=1):
        lines.append(str(index))
        lines.append(f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)
