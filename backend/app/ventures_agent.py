"""
VENTURES Opportunity Radar (2026-09-23, Phase 1) -- structurally
separate from Frank's chat tools, same isolation as
trade_intelligence_agent.py: never registered in main.py's tools=[...]
list, reachable only via main.py's own dedicated /ventures/... REST
routes and the Mac-only _venture_scan_loop background job. This keeps
the "limited access, no unrestricted write permissions" boundary Josh
asked for structural, not just prompted -- no chat conversation can
reach around it.

Same well-defined-block extraction discipline as tonight's
trade_intelligence_agent.py's extract_trade_suggestion: the model is
asked to emit fenced ```opportunity``` JSON blocks in a fixed schema
when it has something concrete, never free-form-prose parsing (already
tried and rejected as fragile earlier tonight, for the same reason it
would be fragile here).

Real, disclosed limitation: the "no scams, no misleading marketing, no
unethical businesses" boundary (Section 2 of the original request) is
enforced here as a system-prompt instruction only -- there is no
independent, code-level check that verifies an opportunity the model
proposes is actually ethical or legal. This is the same class of
limitation as the Trade Intelligence agent's own "never assert false
precision" instruction: a real constraint on the model's behavior, not
a guarantee enforced elsewhere.
"""

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

from anthropic import AsyncAnthropic

from app.web_tools import WEB_FETCH_TOOL, WEB_SEARCH_TOOL

VENTURES_AGENT_SYSTEM_PROMPT = """You are the Venture Research Agent inside P Corp OS's VENTURES division -- a specialist that looks for real, concrete small-business/digital-product opportunities Josh could realistically start, not a generic "make money online" idea generator.

Josh's own context (skills, existing assets, current systems) is given to you below with each request -- ground your ideas in what he actually already has (existing workflows, templates, client relationships, technical skills), not generic advice that could apply to anyone.

HARD BOUNDARIES, non-negotiable:
- Never propose a scam, misleading marketing angle, or anything unethical or illegal, even if it would plausibly make money. If you're unsure whether something crosses that line, don't propose it.
- Never assert false certainty. You have no way to know for certain that a market is underserved or that people will pay for something -- say "likely," "some evidence suggests," or name your actual source, not "there is huge demand for X."
- You have no path to spend money, launch anything publicly, contact a customer, or sign anything on Josh's behalf. Every opportunity you surface is a suggestion for him to review -- acting on it, including deciding to research or build it further, is entirely his own decision.
- Rate automation_potential, owner_time_required, and confidence honestly -- a real digital product with genuine ongoing fulfillment work is not "high automation, low owner time" just because it sounds more attractive that way.

When you find a real, concrete opportunity worth surfacing, end that part of your reply with a fenced block in exactly this format (the literal language tag `opportunity`, valid JSON inside, nothing else in the block) -- you may include more than one block in a single reply if you found several distinct opportunities:
```opportunity
{"name": "...", "description": "...", "revenue_model": "...", "setup_cost": 0.0, "automation_potential": "low", "owner_time_required": "low", "confidence": "high", "risks": "...", "recommended_next_step": "..."}
```
automation_potential/owner_time_required are "low", "medium", or "high". confidence is "high", "medium", or "low". Only include a block for something genuinely concrete and reasoned through -- if nothing you found is worth surfacing, write a short explanation of why and include no blocks at all. This block is parsed by the app to create a real Opportunity record for Josh's own review -- it is never acted on automatically."""

_OPPORTUNITY_BLOCK_RE = re.compile(r"```opportunity\s*\n(.*?)\n```", re.DOTALL)


def count_opportunity_blocks(reply_text: str) -> int:
    """How many idea blocks the reply contains, readable or not (to notice ideas that were written but couldn't be used)."""
    return len(_OPPORTUNITY_BLOCK_RE.findall(reply_text))


def extract_opportunities(reply_text: str) -> list[dict]:
    """Looks for the fenced blocks VENTURES_AGENT_SYSTEM_PROMPT asks
    for -- a well-defined, deterministic marker, not prose-parsing.
    Fails closed per-block: a malformed block is skipped, not guessed
    at, and never blocks the other valid blocks in the same reply from
    being extracted."""
    opportunities: list[dict] = []
    for match in _OPPORTUNITY_BLOCK_RE.finditer(reply_text):
        try:
            data = json.loads(match.group(1))
            automation_potential = str(data.get("automation_potential", "")).lower()
            owner_time_required = str(data.get("owner_time_required", "")).lower()
            confidence = str(data.get("confidence", "")).lower()
            if automation_potential not in ("low", "medium", "high"):
                continue
            if owner_time_required not in ("low", "medium", "high"):
                continue
            # On 2026-10-11 a scan returned two real ideas without this field and both were silently thrown away. The
            # model's own confidence is the one rating that can safely default: an unrated idea is treated as LOW
            # (never claim certainty that wasn't given) and flagged, instead of losing the idea.
            confidence_defaulted = confidence not in ("high", "medium", "low")
            if confidence_defaulted:
                confidence = "low"
            opportunities.append({
                "confidence_defaulted": confidence_defaulted,
                "name": str(data["name"]),
                "description": str(data["description"]),
                "revenue_model": str(data.get("revenue_model", "")) or None,
                "setup_cost": float(data["setup_cost"]) if data.get("setup_cost") is not None else None,
                "automation_potential": automation_potential,
                "owner_time_required": owner_time_required,
                "confidence": confidence,
                "risks": str(data.get("risks", "")) or None,
                "recommended_next_step": str(data.get("recommended_next_step", "")) or None,
            })
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return opportunities


# How hard the model thinks before answering. The first real scan (2026-10-10) spent 6,251 output tokens, only ~1,600 of
# them visible, in 76.7 s with the default (high) effort and just 2 searches, so the time was mostly reasoning. "medium"
# keeps the searching and trims that. Compare the [venture_scan] log lines before/after; raise it if ideas get thinner.
SCAN_EFFORT = "medium"

# Once told what's already on his list the scan searched twice as much (2 -> 4 searches), and every search adds a lot of
# text to read: input went 29k -> 104k tokens, 56 s -> 71 s, ~10 -> ~26 cents (2026-10-11 log). So the scan gets its OWN
# copy of the search tool with a lower limit; the shared WEB_SEARCH_TOOL (5) that the other agents use is left alone.
# When the limit is reached the API refuses further searches with a "max_uses_exceeded" result and the model answers with
# what it has -- nothing raises.
SCAN_MAX_SEARCHES = 3
SCAN_WEB_SEARCH_TOOL = {**WEB_SEARCH_TOOL, "max_uses": SCAN_MAX_SEARCHES}


# ------------------------------------------------------- not proposing what Josh already has
# The scan used to be given only Josh's business data, never his list of ideas, so it kept re-proposing the same ones:
# by 2026-10-10 it had suggested "retainers" three times (one of them already DISMISSED by Josh) and the "activation
# package" twice. Text similarity can't catch that (a reworded repeat scores no higher than a different idea), so: (1) the
# scan is shown everything already on his list, with what he decided, and (2) a cheap second model reads each new idea
# against that list and drops the ones that are the same idea. If that check fails, nothing is dropped.
DEDUPE_MODEL = "claude-haiku-5-5"
MAX_EXISTING_IDEAS = 40
_STATUS_LABEL = {"new": "pending review", "dismissed": "DISMISSED by Josh (he said no)", "promoted": "already became a venture"}


def describe_existing(opportunities: list[dict], ventures: list[dict]) -> list[dict]:
    """The ideas already on Josh's list, newest first within each group, capped. Decided ones (dismissed, promoted, running
    ventures) come first because repeating those is the worst mistake; then the pending ones."""
    items = [{"kind": "venture", "status": "running venture", "name": v.get("name") or "", "description": v.get("description") or ""} for v in ventures]
    decided = [o for o in opportunities if o.get("status") in ("dismissed", "promoted")]
    pending = [o for o in opportunities if o.get("status") not in ("dismissed", "promoted")]
    for o in decided + pending:
        items.append({"kind": "opportunity", "status": _STATUS_LABEL.get(o.get("status"), o.get("status") or "pending review"),
                      "name": o.get("name") or "", "description": o.get("description") or ""})
    return [i for i in items if i["name"]][:MAX_EXISTING_IDEAS]


def _short(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def existing_ideas_block(existing: list[dict]) -> str:
    lines = [f"- [{e['status']}] {e['name']}: {_short(e['description'], 220)}" for e in existing]
    return ("Ideas already on Josh's list (every status counts):\n" + "\n".join(lines) + "\n\n"
            "Rules for this scan:\n"
            "1. Do NOT propose any idea above, or a close variant of one (same kind of customer and same core offer, even if reworded, "
            "renamed, or narrowed to named clients). A DISMISSED idea stays dismissed.\n"
            "2. Look somewhere else: a different part of his situation or a different kind of business model than the ones above.\n"
            "3. It is completely fine to surface nothing. If you cannot find something genuinely new and concrete, say so briefly "
            "instead of padding the answer with repeats.\n\n")


JUDGE_SYSTEM_PROMPT = """You compare business ideas. For each NEW idea decide whether it is essentially the same idea as one of the EXISTING ideas.
Same idea = same kind of customer AND same core offer or mechanism, even if it is reworded, renamed, priced differently, or narrowed to specific named clients. A narrower or broader version of an existing idea with the same core mechanism IS a repeat. A genuinely different customer, offer or mechanism is NOT a repeat, even in the same industry.
Reply with ONLY JSON: {"verdicts":[{"new":1,"repeat_of":3,"why":"max 15 words"}, ...]} -- one entry per NEW idea, "repeat_of" the EXISTING idea's number or null if it is not a repeat."""


def parse_judge_reply(text: str, n_new: int, n_existing: int) -> dict[int, tuple[int, str]] | None:
    """{new idea number: (existing idea number, why)} for the ones judged repeats, or None if the reply is unusable.
    Verdicts naming a number that doesn't exist are ignored (never drop an idea on a bad reference)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, list):
        return None
    out: dict[int, tuple[int, str]] = {}
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        try:
            new_i, old_i = int(v.get("new")), v.get("repeat_of")
        except (TypeError, ValueError):
            continue
        if old_i is None or isinstance(old_i, bool):
            continue
        try:
            old_i = int(old_i)
        except (TypeError, ValueError):
            continue
        if 1 <= new_i <= n_new and 1 <= old_i <= n_existing:
            out[new_i] = (old_i, str(v.get("why") or "")[:120])
    return out


async def judge_repeats(client: AsyncAnthropic, new_opps: list[dict], existing: list[dict]) -> tuple[list[dict], list[dict], bool]:
    """(kept, skipped, check_failed). Fails open: if the check can't run or its answer can't be read, every idea is kept."""
    if not new_opps or not existing:
        return new_opps, [], False
    old_lines = "\n".join(f"{i}. [{e['status']}] {e['name']} -- {_short(e['description'], 260)}" for i, e in enumerate(existing, 1))
    new_lines = "\n".join(f"{i}. {o['name']} -- {_short(o['description'], 300)} (revenue: {_short(o['revenue_model'], 120)})" for i, o in enumerate(new_opps, 1))
    try:
        response = await client.messages.create(
            model=DEDUPE_MODEL, max_tokens=800, system=JUDGE_SYSTEM_PROMPT, output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"EXISTING ideas:\n{old_lines}\n\nNEW ideas:\n{new_lines}"}],
        )
        verdicts = parse_judge_reply("".join(b.text for b in response.content if getattr(b, "type", "") == "text"), len(new_opps), len(existing))
    except Exception as exc:
        print(f"[venture_scan] repeat check failed ({type(exc).__name__}: {str(exc)[:120]}); keeping every idea")
        return new_opps, [], True
    if verdicts is None:
        print("[venture_scan] repeat check gave an unreadable answer; keeping every idea")
        return new_opps, [], True
    kept, skipped = [], []
    for i, opp in enumerate(new_opps, 1):
        if i in verdicts:
            old_i, why = verdicts[i]
            skipped.append({"name": opp["name"], "repeat_of": existing[old_i - 1]["name"], "repeat_of_status": existing[old_i - 1]["status"], "why": why})
        else:
            kept.append(opp)
    return kept, skipped, False


def _count_refused_searches(content: list) -> int:
    """How many searches the API refused because the limit was already used up (a web_search_tool_result whose content is
    an error object with error_code max_uses_exceeded; a normal result's content is a list)."""
    refused = 0
    for b in content:
        if getattr(b, "type", "") != "web_search_tool_result":
            continue
        inner = getattr(b, "content", None)
        code = inner.get("error_code") if isinstance(inner, dict) else getattr(inner, "error_code", None)
        if code == "max_uses_exceeded":
            refused += 1
    return refused


def _count_server_tools(content: list) -> tuple[int, int]:
    """(web searches, page reads) Claude made inside one request, counted from the response's own tool-use blocks."""
    searches = sum(1 for b in content if getattr(b, "type", "") == "server_tool_use" and getattr(b, "name", "") == "web_search")
    fetches = sum(1 for b in content if getattr(b, "type", "") == "server_tool_use" and getattr(b, "name", "") == "web_fetch")
    return searches, fetches


async def scan_for_opportunities(
    client: AsyncAnthropic, josh_context: str, *, metrics: dict[str, Any] | None = None, source: str = "manual",
    existing: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """One-shot, non-streaming -- same shape as trade_intelligence_
    agent.py's own advisory functions, never a Frank chat tool. Returns
    (raw reply text, extracted+validated opportunities) so the caller
    can log/inspect the reasoning even when zero opportunities were
    concrete enough to extract.

    How long the scan took and what it spent are logged on one line and, if `metrics` is given, filled in there
    (seconds, searches, page_reads, input/output tokens, stop_reason, opportunities) -- a scan is slow because it
    searches and reads pages one after another, and these numbers say how much of each it actually did."""
    prompt = (
        f"Here's Josh's own context (skills, existing assets, current systems): {josh_context}\n\n"
        + (existing_ideas_block(existing) if existing else "")
        + f"Look for 1-3 real, concrete business opportunities he could realistically start, grounded in what "
        f"he already has -- not generic ideas. Search for real current market signal on anything you're not "
        f"already confident about rather than relying on general knowledge alone.\n\n"
        f"Every ```opportunity block must contain ALL nine fields: name, description, revenue_model, setup_cost, "
        f"automation_potential, owner_time_required, confidence, risks, recommended_next_step -- including confidence "
        f"(\"high\", \"medium\" or \"low\"). A block missing any of them can't be used."
    )
    started = time.monotonic()
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system=VENTURES_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        tools=[SCAN_WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
        output_config={"effort": SCAN_EFFORT},
    )
    seconds = time.monotonic() - started
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    opportunities = extract_opportunities(reply_text)
    unreadable = count_opportunity_blocks(reply_text) - len(opportunities)  # written by the model but not usable
    defaulted = sum(1 for o in opportunities if o.get("confidence_defaulted"))
    opportunities, skipped, check_failed = await judge_repeats(client, opportunities, existing or [])
    attempts, fetches = _count_server_tools(response.content)
    refused = _count_refused_searches(response.content)
    searches = attempts - refused  # searches that actually ran
    usage = getattr(response, "usage", None)
    tokens_in, tokens_out = getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0
    stop = getattr(response, "stop_reason", None)
    # Where the output tokens went. The reply text is what we can see (~4 characters per token); whatever is left of the
    # output total is reasoning (hidden by default) plus the search queries, which are tiny.
    thinking_blocks = sum(1 for b in response.content if getattr(b, "type", "") in ("thinking", "redacted_thinking"))
    visible_tokens = len(reply_text) // 4
    hidden_tokens = max(0, tokens_out - visible_tokens)
    if metrics is not None:
        metrics.update({"seconds": round(seconds, 1), "searches": searches, "page_reads": fetches, "input_tokens": tokens_in,
                        "output_tokens": tokens_out, "stop_reason": stop, "opportunities": len(opportunities), "effort": SCAN_EFFORT,
                        "thinking_blocks": thinking_blocks, "visible_tokens_est": visible_tokens, "hidden_tokens_est": hidden_tokens,
                        "unreadable_blocks": unreadable, "confidence_defaulted": defaulted, "search_limit": SCAN_MAX_SEARCHES, "searches_refused": refused, "existing_ideas": len(existing or []), "repeats_skipped": len(skipped), "repeat_details": skipped, "repeat_check_failed": check_failed})
    print(f"[venture_scan] {source}: {seconds:.1f} s | {searches} searches{f' (limit of {SCAN_MAX_SEARCHES} reached, {refused} more refused)' if refused else ''}, {fetches} page reads | in {tokens_in:,} / out {tokens_out:,} tokens "
          f"(~{visible_tokens:,} visible, ~{hidden_tokens:,} hidden; {thinking_blocks} thinking block{'' if thinking_blocks == 1 else 's'}) | effort {SCAN_EFFORT} "
          f"| {len(opportunities)} opportunit{'y' if len(opportunities) == 1 else 'ies'}"
          + (f" | {unreadable} idea block{'' if unreadable == 1 else 's'} UNREADABLE and skipped" if unreadable else "")
          + (f" | {defaulted} without a confidence rating (saved as low)" if defaulted else "")
          + f" | stop: {stop}"
          + (f" | vs {len(existing)} existing ideas: {len(skipped)} repeat{'' if len(skipped) == 1 else 's'} skipped" + (" (repeat check FAILED, kept all)" if check_failed else "") if existing else ""))
    return reply_text, opportunities


# ------------------------------------------------------- running a scan in the background
# A scan is one long request (searches and page reads happen one after another), so it runs as a background task
# and the app polls its state instead of holding a request open -- no timeout cliff, and leaving the screen doesn't
# lose it. One scan at a time, held in this process: a backend restart forgets a running scan (nothing was saved yet)
# but never a finished one (those are saved as opportunities).

class ScanBusyError(RuntimeError):
    pass


_SCAN_RUN: dict[str, Any] | None = None


def _friendly_scan_error(exc: Exception) -> str:
    if getattr(exc, "status_code", None) in (401, 403) or "credit balance" in str(exc).lower():
        return ("Claude can't be used right now (the API credit balance is too low, or the API key was rejected). "
                "Add credits at console.anthropic.com/settings/billing, then scan again.")
    return f"The scan failed: {type(exc).__name__}: {str(exc)[:200]}"


def scan_run_state() -> dict[str, Any] | None:
    """The current/last scan run without its internals; `elapsed_seconds` counts up while it is running."""
    run = _SCAN_RUN
    if run is None:
        return None
    out = {k: v for k, v in run.items() if k not in ("task", "_t0")}
    out["metrics"] = dict(run["metrics"])
    out["created_ids"] = list(run["created_ids"])
    out["elapsed_seconds"] = round((run["_end"] if run.get("_end") is not None else time.monotonic()) - run["_t0"], 1)
    return out


def start_scan_run(work: Callable[[dict[str, Any]], Awaitable[None]], *, source: str = "manual") -> dict[str, Any]:
    """Runs `work(run)` in the background and returns the run state at once. `work` fills in run["reply"],
    run["created_ids"], run["metrics"] and optionally run["message"]. Raises ScanBusyError if one is already running."""
    global _SCAN_RUN
    if _SCAN_RUN is not None and _SCAN_RUN["state"] == "running":
        raise ScanBusyError("A scan is already running.")
    run: dict[str, Any] = {"state": "running", "source": source, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished_at": None,
                           "message": None, "reply": None, "created_ids": [], "metrics": {}, "_t0": time.monotonic(), "_end": None}

    async def go() -> None:
        try:
            await work(run)
            run["state"] = "done"
            if not run["message"]:
                n = len(run["created_ids"])
                run["message"] = f"Found {n} new opportunit{'y' if n == 1 else 'ies'}." if n else "Nothing concrete enough to surface this time."
        except Exception as exc:  # a background task must never die silently
            run["state"], run["message"] = "failed", _friendly_scan_error(exc)
            print(f"[venture_scan] {source} scan failed: {type(exc).__name__}: {str(exc)[:200]}")
        finally:
            run["_end"] = time.monotonic()
            run["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    run["task"] = asyncio.get_running_loop().create_task(go())  # kept in the dict so it isn't garbage-collected mid-run
    _SCAN_RUN = run
    return scan_run_state()


# ------------------------------------------------------- Validation Engine
# (2026-09-24, Phase 2) -- same structural isolation as scan_for_opportunities
# above: never a Frank chat tool, reachable only via POST /ventures/{id}/validate.
# One-shot, re-run-for-a-fresh-take (confirmed with Josh), not a conversational
# thread -- keeps this file's calling convention consistent with the Radar
# function above rather than importing trade_intelligence_agent.py's
# run_conversational_turn machinery for a capability that doesn't need it.

VALIDATION_AGENT_SYSTEM_PROMPT = """You are the Venture Validation Agent inside P Corp OS's VENTURES division -- you produce an honest, evidence-grounded assessment of ONE specific venture Josh is considering, not a generic feasibility pep talk.

You're given the venture's own recorded details (name, description, type, revenue model, risk/automation/confidence ratings already on file) plus Josh's own context below. Ground your evidence in real, current information about that venture's specific market -- search for it rather than relying on general knowledge alone.

HARD BOUNDARIES, non-negotiable:
- Never assert false certainty. If you don't have real evidence for a claim, say "likely," "some evidence suggests," or name your actual source -- never "there is huge demand for X" without something backing it.
- Name real unknowns and risks plainly, even ones that make the venture look weaker. A validation report that only confirms what Josh already wants to hear is worthless to him.
- You have no path to spend money, launch anything, contact a customer, or change the venture's status yourself. This report is Josh's own input to his own decision -- never a verdict that acts on itself.
- Don't manufacture a fake "go/no-go" score or numeric confidence percentage. `verdict` is a short, honest one-line summary judgment in your own words, and `confidence` is one of "high"/"medium"/"low" about how much real evidence you actually found -- not a marketing-style rating.

End your reply with exactly one fenced block in this format (the literal language tag `validation-report`, valid JSON inside, nothing else in the block):
```validation-report
{"evidence": "...", "assumptions": "...", "unknowns": "...", "risks": "...", "verdict": "...", "confidence": "medium"}
```
`evidence`/`assumptions`/`unknowns`/`risks` are each a short paragraph in your own words (not bullet-point JSON arrays -- plain prose is easier for Josh to actually read). `confidence` is "high", "medium", or "low". This block is parsed by the app to create a real, permanent validation report record -- it is never acted on automatically."""

_VALIDATION_REPORT_BLOCK_RE = re.compile(r"```validation-report\s*\n(.*?)\n```", re.DOTALL)


def extract_validation_report(reply_text: str) -> dict | None:
    """Same fail-closed discipline as extract_opportunities -- a single
    expected block here (one report per run), returns None rather than
    guessing if it's missing or malformed."""
    match = _VALIDATION_REPORT_BLOCK_RE.search(reply_text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
        confidence = str(data.get("confidence", "")).lower()
        if confidence not in ("high", "medium", "low"):
            return None
        return {
            "evidence": str(data["evidence"]),
            "assumptions": str(data["assumptions"]),
            "unknowns": str(data["unknowns"]),
            "risks": str(data["risks"]),
            "verdict": str(data["verdict"]),
            "confidence": confidence,
        }
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def run_validation(client: AsyncAnthropic, venture: dict, josh_context: str) -> tuple[str, dict | None]:
    """One-shot, non-streaming. Returns (raw reply text, extracted report
    or None) so the caller can still show Josh the raw reasoning even if
    the block failed to parse -- matching scan_for_opportunities' own
    "never silently discard the reply" behavior."""
    venture_summary = (
        f"Name: {venture['name']}\nDescription: {venture.get('description') or '(none yet)'}\n"
        f"Type: {venture.get('type') or '(not set)'}\nRevenue model: {venture.get('revenue_model') or '(not set)'}\n"
        f"Status: {venture['status']}\nOwner time: {venture.get('owner_time') or '(not set)'}\n"
        f"Automation level: {venture.get('automation_level') or '(not set)'}\n"
        f"Risk level: {venture.get('risk_level') or '(not set)'}\nConfidence: {venture.get('confidence') or '(not set)'}\n"
        f"Notes: {venture.get('notes') or '(none)'}"
    )
    prompt = (
        f"Here's the venture to validate:\n{venture_summary}\n\n"
        f"Here's Josh's own context (skills, existing assets, current systems): {josh_context}\n\n"
        f"Produce a real validation report: what evidence actually supports this working, what assumptions "
        f"it's resting on, what's genuinely unknown, and what could make it fail. Search for real current "
        f"market signal specific to this venture rather than relying on general knowledge alone."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system=VALIDATION_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_validation_report(reply_text)


# ---------------------------------------------------------- Venture Builder
# (2026-09-24, Phase 2) -- same isolation/one-shot shape as above. No web
# tools: this is synthesis from the venture's own already-known fields
# (positioning/SOP drafting), not new market research -- that's Validation's
# job, not Builder's.

BUILDER_AGENT_SYSTEM_PROMPT = """You are the Venture Builder Agent inside P Corp OS's VENTURES division -- you turn a venture Josh has already decided is worth pursuing into a real concept and a concrete first operating checklist, not vague encouragement.

You're given the venture's own recorded details plus Josh's own context below.

HARD BOUNDARIES, non-negotiable:
- You have no path to spend money, launch anything publicly, contact a customer, register a business, or sign anything on Josh's behalf. Everything you produce here is a draft for him to review, edit, and act on himself.
- Don't invent a fake brand identity, market data, or customer testimonials to make the concept sound more polished -- concept and positioning copy should be honest, working drafts, not fabricated proof.
- Checklist steps must be concrete and actually actionable by Josh (or something he'd delegate) -- never a vague step like "grow the business" or "get customers," always something with a clear, checkable definition of done.

End your reply with exactly one fenced block in this format (the literal language tag `venture-concept`, valid JSON inside, nothing else in the block):
```venture-concept
{"concept_summary": "...", "positioning_copy": "...", "sop_steps": ["...", "...", "..."]}
```
`concept_summary` is a short paragraph describing what this venture actually is and how it works. `positioning_copy` is a short piece of real draft marketing/positioning language Josh could use as a starting point (not a slogan-only one-liner -- a few real sentences). `sop_steps` is an ordered list of 3-8 concrete, checkable first steps to actually get this venture running -- these become real checklist items Josh will work through before launch. This block is parsed by the app to update the venture's own concept fields and create real checklist items -- it is never acted on automatically."""

_VENTURE_CONCEPT_BLOCK_RE = re.compile(r"```venture-concept\s*\n(.*?)\n```", re.DOTALL)


def extract_venture_concept(reply_text: str) -> dict | None:
    """Same fail-closed discipline as the other extractors here."""
    match = _VENTURE_CONCEPT_BLOCK_RE.search(reply_text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
        sop_steps = [str(step) for step in data["sop_steps"]]
        if not sop_steps:
            return None
        return {
            "concept_summary": str(data["concept_summary"]),
            "positioning_copy": str(data["positioning_copy"]),
            "sop_steps": sop_steps,
        }
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def build_venture_content(client: AsyncAnthropic, venture: dict, josh_context: str) -> tuple[str, dict | None]:
    """One-shot, non-streaming. No web tools -- this synthesizes from the
    venture's own already-known fields, not new market research."""
    venture_summary = (
        f"Name: {venture['name']}\nDescription: {venture.get('description') or '(none yet)'}\n"
        f"Type: {venture.get('type') or '(not set)'}\nRevenue model: {venture.get('revenue_model') or '(not set)'}\n"
        f"Status: {venture['status']}\nOwner time: {venture.get('owner_time') or '(not set)'}\n"
        f"Automation level: {venture.get('automation_level') or '(not set)'}\nNotes: {venture.get('notes') or '(none)'}"
    )
    prompt = (
        f"Here's the venture to build out:\n{venture_summary}\n\n"
        f"Here's Josh's own context (skills, existing assets, current systems): {josh_context}\n\n"
        f"Draft a concept summary, positioning copy, and a concrete first operating checklist to actually "
        f"get this running."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system=BUILDER_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_venture_concept(reply_text)


# --------------------------------------------------------- Financial Analyst
# (2026-09-24, Phase 4) -- same structural isolation as every agent above:
# never a Frank chat tool, reachable only via POST /ventures/{id}/financial-
# analysis. Pure narration, no fenced block, no persistence -- same
# "compute deterministically elsewhere, only narrate here" discipline as
# trade_intelligence_agent.py's narrate_trade_breakdown: this function never
# recomputes compute_customer_metrics' numbers, only explains what they mean.

FINANCIAL_AGENT_SYSTEM_PROMPT = """You are the Financial Analyst Agent inside P Corp OS's VENTURES division -- you explain what a venture's real, already-computed numbers actually mean, in plain language. You never recompute or second-guess the numbers you're given; they come from a real, deterministic ledger of logged customer revenue events.

HARD BOUNDARIES, non-negotiable:
- Never invent a number that wasn't given to you. If a metric is missing or null (not enough data yet), say so plainly -- don't estimate or smooth over it.
- Never assert false certainty about a trend from a small sample. One or two customers is not a real trend -- say so directly, same honesty a competent human analyst would show.
- You have no path to spend money, change pricing, or contact a customer. This is commentary for Josh's own decision, never an instruction that acts on itself.

Write a short, direct narration (a few sentences to a short paragraph) of what the given numbers mean for this venture right now -- is it actually making money, is churn a real concern, is the cost of acquiring a customer sane relative to what they're worth. No fenced block is needed here -- just write the analysis directly."""


async def narrate_financial_health(client: AsyncAnthropic, venture: dict, metrics: dict, josh_context: str) -> str:
    """One-shot, non-streaming. Returns plain narration text -- nothing
    to extract or persist, matching narrate_trade_breakdown's own shape
    (this file's other narration-only precedent)."""
    average_ltv_text = f"R{metrics['average_ltv']:.2f}" if metrics["average_ltv"] is not None else "not enough data yet"
    average_cac_text = f"R{metrics['average_cac']:.2f}" if metrics["average_cac"] is not None else "not enough data yet"
    metrics_summary = (
        f"Active customers: {metrics['active_customers']}\nChurned customers: {metrics['churned_customers']}\n"
        f"Churn rate: {metrics['churn_rate'] if metrics['churn_rate'] is not None else 'not enough data yet'}\n"
        f"Total revenue (all-time): R{metrics['total_revenue']:.2f}\n"
        f"Revenue, last 30 days: R{metrics['revenue_last_30d']:.2f}\n"
        f"Average LTV: {average_ltv_text}\n"
        f"Average CAC: {average_cac_text} "
        f"(based on {metrics['customers_with_recorded_cac']} of {metrics['total_customers']} customers with a recorded cost)"
    )
    prompt = (
        f"Venture: {venture['name']} ({venture.get('type') or 'type not set'})\n\n"
        f"Its real, already-computed customer/revenue numbers:\n{metrics_summary}\n\n"
        f"Josh's own context: {josh_context}\n\n"
        f"Explain what these numbers actually mean for this venture right now."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,  # short narration by design, but some headroom is cheap
        system=FINANCIAL_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


# ---------------------------------------------------------- Marketing Content
# (2026-09-24, Phase 4) -- same isolation as above. Persists (Josh will want
# to look back at past drafts), unlike Financial Analyst's ephemeral narration.

MARKETING_AGENT_SYSTEM_PROMPT = """You are the Marketing Content Agent inside P Corp OS's VENTURES division -- you draft ongoing marketing copy for a venture that's already been built, using its own real concept and positioning (if drafted) as the foundation.

HARD BOUNDARIES, non-negotiable:
- You have no path to actually post, publish, or send anything -- everything you write is a draft for Josh's own review before it goes anywhere.
- Never invent fake testimonials, fake numbers, or claims Josh hasn't actually established about this venture.
- Match the venture's own real positioning (if it has one) rather than inventing a new voice each time.

End your reply with exactly one fenced block in this format (the literal language tag `marketing-content`, valid JSON inside, nothing else in the block):
```marketing-content
{"content": "..."}
```
`content` is the actual draft copy requested, ready for Josh to edit and use -- not a description of what you'd write. This block is parsed by the app to create a real, permanent marketing-content record -- it is never posted or sent automatically."""

_MARKETING_CONTENT_BLOCK_RE = re.compile(r"```marketing-content\s*\n(.*?)\n```", re.DOTALL)


def extract_marketing_content(reply_text: str) -> dict | None:
    match = _MARKETING_CONTENT_BLOCK_RE.search(reply_text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
        return {"content": str(data["content"])}
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def generate_marketing_content(
    client: AsyncAnthropic, venture: dict, content_type: str, josh_context: str
) -> tuple[str, dict | None]:
    """One-shot, non-streaming. content_type shapes the prompt, not the
    schema -- the response is always just the one `content` field."""
    content_type_prompts = {
        "social_post": "a short social media post announcing or promoting this venture",
        "launch_announcement": "a longer launch announcement, suitable for an email or a personal network post",
        "ad_copy": "short paid-ad copy (a headline plus a couple of lines of body text)",
    }
    venture_summary = (
        f"Name: {venture['name']}\nDescription: {venture.get('description') or '(none yet)'}\n"
        f"Concept: {venture.get('concept_summary') or '(not drafted yet)'}\n"
        f"Positioning: {venture.get('positioning_copy') or '(not drafted yet)'}"
    )
    prompt = (
        f"Here's the venture:\n{venture_summary}\n\n"
        f"Here's Josh's own context: {josh_context}\n\n"
        f"Write {content_type_prompts.get(content_type, 'a piece of marketing content')} for this venture."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        # 8192, not 2048 -- a launch_announcement can run long, and the
        # duplicated fenced-block copy needs its own headroom too, same
        # failure class found live for generate_operations_sop above.
        max_tokens=8192,
        system=MARKETING_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_marketing_content(reply_text)


# ------------------------------------------------------------ Operations/SOP
# (2026-09-24, Phase 4) -- same isolation as above. Overwrites a single
# current value (a living document), explicitly distinct from Venture
# Builder's own one-time "first checklist to launch."

OPERATIONS_AGENT_SYSTEM_PROMPT = """You are the Operations Agent inside P Corp OS's VENTURES division -- you write the ongoing, day-to-day operating procedure for a venture that's actually running, not a one-time launch checklist (that's a different agent's job).

HARD BOUNDARIES, non-negotiable:
- Write for a venture that already exists and has real customers or is actively being sold -- recurring operating steps, not "how to start."
- You have no path to actually perform any of these steps, hire anyone, or spend money -- this is a reference document for Josh (or whoever he delegates it to) to follow.
- Keep it concrete and specific to this venture's own real type/automation level -- never generic "run your business well" filler.

End your reply with exactly one fenced block in this format (the literal language tag `operations-sop`, valid JSON inside, nothing else in the block):
```operations-sop
{"sop": "..."}
```
`sop` is the actual operating procedure text, written as something Josh could genuinely follow or hand to someone else. This block is parsed by the app to update the venture's own current operating procedure -- it replaces whatever was there before, since this is meant to be the venture's one current reference, not a dated history."""

_OPERATIONS_SOP_BLOCK_RE = re.compile(r"```operations-sop\s*\n(.*?)\n```", re.DOTALL)


def extract_operations_sop(reply_text: str) -> dict | None:
    match = _OPERATIONS_SOP_BLOCK_RE.search(reply_text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
        return {"sop": str(data["sop"])}
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


async def generate_operations_sop(client: AsyncAnthropic, venture: dict, josh_context: str) -> tuple[str, dict | None]:
    """One-shot, non-streaming."""
    venture_summary = (
        f"Name: {venture['name']}\nDescription: {venture.get('description') or '(none yet)'}\n"
        f"Type: {venture.get('type') or '(not set)'}\nStatus: {venture['status']}\n"
        f"Automation level: {venture.get('automation_level') or '(not set)'}\n"
        f"Concept: {venture.get('concept_summary') or '(not drafted yet)'}"
    )
    prompt = (
        f"Here's the venture:\n{venture_summary}\n\n"
        f"Here's Josh's own context: {josh_context}\n\n"
        f"Write the ongoing operating procedure for actually running this venture day-to-day."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        # 8192, not 4096 -- a real bug found live tonight: a comprehensive
        # SOP plus its own duplicated fenced-block copy genuinely exceeded
        # 4096 tokens and got cut off mid-JSON, same failure class already
        # fixed once tonight for Trade Intelligence's own run_conversational_turn.
        max_tokens=8192,
        system=OPERATIONS_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_operations_sop(reply_text)


# -------------------------------------------------------- Automation Scout
# (2026-09-24, Phase 4) -- same isolation as above. Multi-block, fail-closed
# per block, same discipline as extract_opportunities.

AUTOMATION_AGENT_SYSTEM_PROMPT = """You are the Automation Scout Agent inside P Corp OS's VENTURES division -- you look at a specific, real venture and suggest concrete steps that could realistically be automated, given what it actually is and how it currently runs.

HARD BOUNDARIES, non-negotiable:
- Suggest only real, concrete automations (a specific tool, workflow, or integration) -- never vague advice like "automate more of your business."
- You have no path to actually set up, buy, or connect anything -- every suggestion is for Josh's own review and action.
- Be honest about effort: a suggestion that would take longer to set up than it saves isn't a good one -- say so rather than padding the list.

When you find a real, concrete automation opportunity worth suggesting, end that part of your reply with a fenced block in exactly this format (the literal language tag `automation-suggestion`, valid JSON inside, nothing else in the block) -- you may include more than one block if you found several distinct opportunities:
```automation-suggestion
{"title": "...", "description": "...", "suggested_approach": "..."}
```
Only include a block for something genuinely concrete and worth doing -- if nothing you found is worth suggesting, say so and include no blocks at all. This block is parsed by the app to create a real suggestion record for Josh's own review -- it is never acted on automatically."""

_AUTOMATION_SUGGESTION_BLOCK_RE = re.compile(r"```automation-suggestion\s*\n(.*?)\n```", re.DOTALL)


def extract_automation_suggestions(reply_text: str) -> list[dict]:
    """Same fail-closed-per-block discipline as extract_opportunities."""
    suggestions: list[dict] = []
    for match in _AUTOMATION_SUGGESTION_BLOCK_RE.finditer(reply_text):
        try:
            data = json.loads(match.group(1))
            suggestions.append({
                "title": str(data["title"]),
                "description": str(data["description"]),
                "suggested_approach": str(data.get("suggested_approach", "")) or None,
            })
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return suggestions


async def scout_automation_opportunities(
    client: AsyncAnthropic, venture: dict, josh_context: str
) -> tuple[str, list[dict]]:
    """One-shot, non-streaming."""
    venture_summary = (
        f"Name: {venture['name']}\nDescription: {venture.get('description') or '(none yet)'}\n"
        f"Type: {venture.get('type') or '(not set)'}\nStatus: {venture['status']}\n"
        f"Automation level (self-rated): {venture.get('automation_level') or '(not set)'}\n"
        f"Operating procedure: {venture.get('operations_sop') or '(not drafted yet)'}"
    )
    prompt = (
        f"Here's the venture:\n{venture_summary}\n\n"
        f"Here's Josh's own context: {josh_context}\n\n"
        f"Look for 1-3 real, concrete steps in running this venture that could be automated."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,  # same headroom fix as generate_operations_sop above, same failure class
        system=AUTOMATION_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_automation_suggestions(reply_text)
