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

import json
import re

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
            if confidence not in ("high", "medium", "low"):
                continue
            opportunities.append({
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


async def scan_for_opportunities(client: AsyncAnthropic, josh_context: str) -> tuple[str, list[dict]]:
    """One-shot, non-streaming -- same shape as trade_intelligence_
    agent.py's own advisory functions, never a Frank chat tool. Returns
    (raw reply text, extracted+validated opportunities) so the caller
    can log/inspect the reasoning even when zero opportunities were
    concrete enough to extract."""
    prompt = (
        f"Here's Josh's own context (skills, existing assets, current systems): {josh_context}\n\n"
        f"Look for 1-3 real, concrete business opportunities he could realistically start, grounded in what "
        f"he already has -- not generic ideas. Search for real current market signal on anything you're not "
        f"already confident about rather than relying on general knowledge alone."
    )
    response = await client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system=VENTURES_AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        tools=[WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
    )
    reply_text = "".join(block.text for block in response.content if block.type == "text")
    return reply_text, extract_opportunities(reply_text)


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
