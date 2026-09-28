"""
POST (2026-09-27, Phase 8b) -- visual analysis: real, honest Claude
vision judgment on sampled representative frames from a video file.

A genuine, disclosed architectural shift for this division: every prior
POST phase (2 media intelligence, 4 proxies, 5 color intelligence) was
deliberately deterministic, "no LLM in the path" -- real camera-framing/
composition/focus judgment needs actual visual understanding this
codebase has no local capability for. This reuses the exact same
proven pattern Trade Intelligence's own `analyze_chart` already uses
(`trade_intelligence_agent.py`): `build_content_block` for real image
content blocks, the shared `run_conversational_turn` one-shot call, no
tools, no fenced-block parsing (this is plain narrative advisory text
for Josh to read, never data this app makes further decisions from).

Real, disclosed cost difference from every other POST phase: this
spends real Claude API tokens per file analyzed, unlike every other
phase (100% local/free via ffprobe/ffmpeg) -- must always be a
deliberate, explicit, manual trigger from the desktop UI, never
automatic and never Frank-reachable.
"""

from anthropic import AsyncAnthropic

from app.trade_intelligence_agent import run_conversational_turn

VISUAL_ANALYSIS_SYSTEM_PROMPT = """You are a post-production assistant describing the real visual content of sampled video frames for a filmmaker, to help them quickly triage footage before editing.

HARD BOUNDARIES:
- Describe only what is actually visible in the frames given to you -- framing (wide/medium/close-up), composition, apparent focus/sharpness, exposure as shown, and any notable motion blur or visual issues.
- Never claim to know the shot's creative intent, never recommend which take is "better" than another, and never make an editing decision -- selecting or rejecting footage stays entirely the filmmaker's own judgment.
- If a frame is ambiguous, unclear, or you're not confident about something, say so directly rather than guessing.
- These are a handful of sampled still frames, not the full motion of the clip -- state this limitation plainly (e.g. "based on these sampled frames") rather than implying you've seen the whole shot."""


async def analyze_frames(client: AsyncAnthropic, image_blocks: list[dict], filename: str) -> str:
    """One-shot, non-streaming, no tools -- same call shape as
    trade_intelligence_agent.py's own analyze_chart, reusing its exact
    shared run_conversational_turn helper rather than duplicating a
    second messages.create() call site. Returns plain narrative text."""
    prompt_text = (
        f"These are {len(image_blocks)} sampled frame(s) from the video file \"{filename}\", taken at different "
        "points across the clip. Describe the real framing, composition, apparent focus, and any notable visual "
        "issues you can actually see -- keep it concrete and grounded in what's in front of you, not generic advice."
    )
    history = [{"role": "user", "content": [*image_blocks, {"type": "text", "text": prompt_text}]}]
    return await run_conversational_turn(client, VISUAL_ANALYSIS_SYSTEM_PROMPT, history, max_tokens=1024)
