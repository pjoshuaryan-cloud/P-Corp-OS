"""Tests for backend/app/post_chat_edit.py ("Describe an edit", reel autopilot phase 6a): understanding a sentence (with a FAKE Claude), resolving the song,
the costed card, and the run that never goes past the cap (with fake steps). No API call, no files, no database."""
import asyncio, json, sys
from types import SimpleNamespace
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_chat_edit as chat

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

JOBS = [{"id": 50, "shoot_name": "JD Sports - Midlands", "created_at": "2026-11-12"}, {"id": 51, "shoot_name": "Birkenstock pop-up", "created_at": "2026-11-02"}]
REF = [{"slug": "usual-pace", "friendly_title": "Your usual pace", "blurb": "your own rhythm"}, {"slug": "jd-sports-store-opening", "friendly_title": "JD Sports store opening"}]
LIB = [{"slug": "rabit-haus-event-recap", "name": "Rabit Haus event recap", "intent": "A 30-40 s recap", "buildable": True, "sections": ["open", "place"]},
       {"slug": "dialogue-interview", "name": "Dialogue", "intent": "x", "buildable": False, "sections": []},
       {"slug": "usual-pace", "name": "dupe", "intent": "x", "buildable": True, "sections": []}]
STYLES = chat.style_choices(REF, LIB)
check("style choices: the saved references first, then buildable library styles; unbuildable and duplicate slugs left out",
      [s["slug"] for s in STYLES] == ["usual-pace", "jd-sports-store-opening", "rabit-haus-event-recap"] and STYLES[2]["sections"] and STYLES[2]["kind"] == "library", STYLES)
prompt = chat.prompt_for("Rabit Haus recap of the JD shoot", JOBS, STYLES)
check("the prompt lists the shoots and the styles to choose from, and his sentence", "50: JD Sports - Midlands (2026-11-12)" in prompt and "rabit-haus-event-recap: Rabit Haus event recap" in prompt
      and prompt.endswith("His sentence: Rabit Haus recap of the JD shoot"))

def reply(**kw):
    return json.dumps({"job_id": 50, "style": "rabit-haus-event-recap", "song": "3 2 1", "seconds": 35, "usd_cap": None, "unclear": "", **kw})
r = chat.parse_reply(reply(), JOBS, STYLES)
check("parse: shoot, style, song and length kept; no cap given -> the $1 default, marked as not given", r == {"job_id": 50, "style": "rabit-haus-event-recap", "song": "3 2 1", "seconds": 35.0,
      "usd_cap": 1.0, "cap_given": False, "unclear": ""}, r)
r = chat.parse_reply("sure: " + reply(job_id=99, style="made-up", seconds=600, usd_cap=500), JOBS, STYLES)
check("an invented shoot or style, a silly length or cap are dropped, never guessed", r["job_id"] is None and r["style"] is None and r["seconds"] is None and r["usd_cap"] == 1.0 and not r["cap_given"], r)
check("a cap he gave is kept", chat.parse_reply(reply(usd_cap=2), JOBS, STYLES)["usd_cap"] == 2.0)
for bad in ("no json", "{oops}"):
    try:
        chat.parse_reply(bad, JOBS, STYLES); ok = False
    except chat.ChatEditError:
        ok = True
    check(f"an unreadable reply is a plain error ({bad!r})", ok)

class FakeClaude:
    def __init__(self, text):
        self.text, self.calls = text, []
        self.messages = SimpleNamespace(create=self.create)
    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)], stop_reason="end_turn", usage=SimpleNamespace(input_tokens=700, output_tokens=40))
fc = FakeClaude(reply())
req = asyncio.run(chat.understand(fc, "Rabit Haus recap of the JD shoot, 3 2 1, 35 seconds", JOBS, STYLES))
check("understand: one Haiku call, thinking off, low effort", len(fc.calls) == 1 and fc.calls[0]["model"] == "claude-haiku-5-5" and fc.calls[0]["thinking"] == {"type": "disabled"}
      and fc.calls[0]["output_config"] == {"effort": "low"})
check("understand reports what the call used", req["usage"] == {"calls": 1, "in": 700, "out": 40} and req["job_id"] == 50)
for text, jobs in (("   ", JOBS), ("recap", [])):
    try:
        asyncio.run(chat.understand(fc, text, jobs, STYLES)); ok = False
    except chat.ChatEditError:
        ok = True
    check(f"nothing typed or no shoots -> a plain message and no call ({text!r})", ok and len(fc.calls) == 1)

SONGS = [{"path": "/m/new.mp3", "name": "Newest Track.mp3"}, {"path": "/m/321.mp3", "name": "3, 2, 1.mp3"}]
check("the song he named is found by its words", chat.resolve_song(SONGS, "3 2 1")["name"] == "3, 2, 1.mp3" and chat.resolve_song(SONGS, "3 2 1")["matched"])
check("no match -> the newest song, marked as not matched", chat.resolve_song(SONGS, "dance anthem")["name"] == "Newest Track.mp3" and not chat.resolve_song(SONGS, "dance anthem")["matched"])
check("no song named -> the newest", chat.resolve_song(SONGS, None)["path"] == "/m/new.mp3" and chat.resolve_song([], "x") is None)

RH = STYLES[2]
DESC = {"missing": 12, "estimate": {"usd_list_price": 0.12, "usd_at_most": 0.3}}
ROLES = {"sorted": True, "up_to_date": True, "described_moments": 390, "estimate": {"usd": 0.067}}
card = chat.build_card(request={**req, "usd_cap": 1.0}, job=JOBS[0], style=RH, song=chat.resolve_song(SONGS, "3 2 1"), describe=DESC, roles=ROLES)
check("card: describe the new clips, re-sort the roles (new clips bring new moments), then plan", [s["step"] for s in card["steps"]] == ["describe", "sort_roles", "plan"], card["steps"])
check("costs: describe at list price, sorting scaled to the new moments, planning free; total inside the cap -> ready",
      card["steps"][0]["usd"] == 0.12 and abs(card["steps"][1]["usd"] - round(0.067 * 450 / 390, 3)) < 1e-9 and card["steps"][2]["usd"] == 0 and card["ready"] and not card["over_cap"], card)
card2 = chat.build_card(request={**req, "usd_cap": 1.0}, job=JOBS[0], style=RH, song=SONGS[0], describe={"missing": 0}, roles=ROLES)
check("nothing to describe and roles up to date -> just the free plan step", [s["step"] for s in card2["steps"]] == ["plan"] and card2["usd_total"] == 0)
card3 = chat.build_card(request={**req, "usd_cap": 0.05}, job=JOBS[0], style=RH, song=SONGS[1], describe=DESC, roles=ROLES)
check("over the cap -> not ready, and says so", card3["over_cap"] and not card3["ready"])
card4 = chat.build_card(request={**req, "song": "dance anthem"}, job=JOBS[0], style=STYLES[0], song=chat.resolve_song(SONGS, "dance anthem"), describe={"missing": 0}, roles=None)
check("a reference style never sorts roles; an unmatched song is a warning", [s["step"] for s in card4["steps"]] == ["plan"] and any("No song matched" in w for w in card4["warnings"]))
card5 = chat.build_card(request=req, job=JOBS[0], style=STYLES[0], song=None, describe={"missing": 0}, roles=None)
check("no song at all -> not ready, with the reason", not card5["ready"] and any("no song" in w for w in card5["warnings"]))

# the run
async def run_card(card, costs, fail_at=None):
    done = []
    def runner(name):
        async def go(step, c):
            if name == fail_at:
                raise RuntimeError(f"{name} broke")
            done.append(name)
            return {"usd": costs.get(name, 0.0), "note": f"{name} ok", **({"result": {"shots": 48}} if name == "plan" else {})}
        return go
    chat.start(card, {n: runner(n) for n in ("describe", "sort_roles", "plan")})
    await chat._RUN["task"]
    return done, chat.run_state()
done, st = asyncio.run(run_card(card, {"describe": 0.11, "sort_roles": 0.07}))
check("a run inside the cap does every step in order and adds up the real spend", done == ["describe", "sort_roles", "plan"] and st["state"] == "done" and st["spent_usd"] == 0.18
      and st["result"] == {"shots": 48}, st)
check("...and says what to do next", "Build My Edit" in st["message"])
tight = dict(card, usd_cap=0.15)
done, st = asyncio.run(run_card(tight, {"describe": 0.11}))
check("the run stops before a step that would go past the cap, and does nothing after it", done == ["describe"] and st["state"] == "stopped"
      and [s["state"] for s in st["steps"]] == ["done", "skipped", "waiting"] and "cap" in st["message"], st)
done, st = asyncio.run(run_card(card, {}, fail_at="sort_roles"))
check("a failing step stops the run with its message", st["state"] == "failed" and "sort_roles broke" in st["message"] and [s["state"] for s in st["steps"]][:2] == ["done", "failed"], st)
check("the run state never exposes the task", "task" not in chat.run_state())

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
