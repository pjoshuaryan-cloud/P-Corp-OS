"""The Opportunity Radar's brief (2026-11-11): Josh wants ventures that mostly run on their own, are cheap and quick to start, and
can be in any field. The scan is told so, and ideas its own ratings say don't fit are dropped and named, never shown. A fake Claude
only: nothing is spent and no real data is read.
  cd premiere-plugin/e2e && ../../backend/.venv/bin/python ventures_brief_test.py"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import ventures_agent as va  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{str(detail)[:300]}]" if not cond and detail else ""))
    fails += 0 if cond else 1


def idea(name, automation="high", owner="low", cost=500.0):
    return {"name": name, "description": f"{name} description", "revenue_model": "sales", "setup_cost": cost,
            "automation_potential": automation, "owner_time_required": owner, "confidence": "medium",
            "risks": "some", "recommended_next_step": "try it"}


check("an automatic, cheap, low-time idea fits", va.fits_brief(idea("Template shop"))[0])
check("medium automation still fits", va.fits_brief(idea("Course", automation="medium", owner="medium"))[0])
check("one that's mostly by hand doesn't", va.fits_brief(idea("Wedding films", automation="low")) == (False, "it would mostly need doing by hand"))
check("one that needs a lot of his time doesn't", not va.fits_brief(idea("Agency", owner="high"))[0])
check("one costing more than R5,000 to start doesn't", va.fits_brief(idea("Gear rental", cost=40000)) == (False, "it would cost about R40,000 to start"))
check("exactly R5,000 still fits", va.fits_brief(idea("Edge", cost=5000))[0])


class FakeMessages:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)], usage=SimpleNamespace(input_tokens=10, output_tokens=10), stop_reason="end_turn")


def block(o):
    return "```opportunity\n" + json.dumps(o) + "\n```"


reply = "Found three.\n" + "\n".join(block(o) for o in [idea("Notion template shop"), idea("Event videography", automation="low", owner="high"), idea("Vending machines", cost=60000)])
fake = SimpleNamespace(messages=FakeMessages(reply))
metrics = {}
_, kept = asyncio.run(va.scan_for_opportunities(fake, "Josh's context", metrics=metrics, source="test"))
check("only the idea that fits the brief is kept", [o["name"] for o in kept] == ["Notion template shop"], kept)
check("the two that don't are named with why", [(o["name"], o["reason"]) for o in metrics["off_brief"]] == [("Event videography", "it would mostly need doing by hand"), ("Vending machines", "it would cost about R60,000 to start")], metrics.get("off_brief"))
prompt = fake.messages.calls[0]["messages"][0]["content"]
check("the scan is told what he wants, in his own words", "run automatically, easy to start, and don't only have to be related to video production" in prompt)
check("and that his skills are a head start, not a limit", "head start where they fit, NOT a limit" in prompt and "look well beyond that" in prompt)
check("and to say what still needs him", "nothing is fully passive" in prompt)
check("and nothing exploitative passes as automatic", "dropshipping of junk" in prompt and "fake reviews" in prompt)
check("the old 'grounded in what he already has' instruction is gone", "grounded in what" not in prompt and "ground your ideas in what he actually already has" not in va.VENTURES_AGENT_SYSTEM_PROMPT)

main_src = (ROOT / "backend" / "app" / "main.py").read_text()
check("the scan, daily or Scan Now, gets the new framing", "build_ventures_josh_context(postgres_conn, for_scan=True)" in main_src and main_src.count("for_scan=True") == 1)
check("the other Ventures agents keep the business-data framing", main_src.count("build_ventures_josh_context(postgres_conn)") == 6)
check("left-out ideas are named in the scan's result, never silently", "didn't fit your brief" in main_src)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
