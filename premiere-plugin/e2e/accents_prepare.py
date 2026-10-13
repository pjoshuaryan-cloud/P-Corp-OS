"""Adds accents (with STAND-IN sound effects made here, because the real library is on the unmounted SSD) to a scratch job's saved plan.
usage: accents_prepare.py <job id>   -- never touches the real cached SFX index."""
import sys, os, json, asyncio, subprocess, pathlib
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_accents as pa
from app.post_style import profile_from_references
from app.post_edit_plan import plan_to_json
sys.path.insert(0, "."); import e2e_api as a
jid = int(sys.argv[1]); job = a.job(jid); root = pathlib.Path(job["destination_root"])
lib = pathlib.Path("e2e/sfx_lib").resolve(); (lib / "Hits").mkdir(parents=True, exist_ok=True); (lib / "Whooshes").mkdir(parents=True, exist_ok=True)
FF = "/opt/homebrew/bin/ffmpeg"
def make(path, graph, dur):
    if not path.exists():
        subprocess.run([FF, "-nostdin", "-y", "-f", "lavfi", "-i", graph, "-t", str(dur), "-ar", "48000", "-ac", "2", str(path)], check=True, capture_output=True)
for i in range(1, 7):
    make(lib / "Hits" / f"standin_hit_{i}.wav", f"anoisesrc=d=1.4:c={'pink' if i % 2 else 'white'}:a=0.8:seed={i},afade=t=in:d=0.01,afade=t=out:st=0.05:d={0.5 + 0.1 * i}", 1.4)
    make(lib / "Whooshes" / f"standin_whoosh_{i}.wav", f"anoisesrc=d=2.0:c=pink:a=0.7:seed={10 + i},afade=t=in:st=0:d={0.9 + 0.05 * i},afade=t=out:st={1.0 + 0.05 * i}:d=0.5", 2.0)
pa.SFX_INDEX_PATH = pathlib.Path("e2e/sfx_index_test.json").resolve()   # NOT the real cache
index = asyncio.run(pa.build_sfx_index(str(lib)))
print("stand-in SFX indexed:", len(index), "| e.g.", {k: index[0][k] for k in ("name", "role", "seconds", "peak_seconds", "tail_seconds")}, {k: index[-1][k] for k in ("name", "role", "seconds", "peak_seconds", "tail_seconds")})
planp = root / "10_PREMIERE" / "edit_plans" / "edit_plan_latest.json"; plan = json.loads(planp.read_text())
style = profile_from_references(["jd-sports-moa-draft-01"]).accents
acc = pa.plan_accents(plan, style, seed=11, logo_path=str(root / "06_GRAPHICS" / "logo.png"), sfx_index=index)
plan["accents"] = acc; planp.write_text(plan_to_json(plan))
print({k: (len(v) if isinstance(v, list) else v) for k, v in acc.items() if k != "notes"}); print("notes:", acc.get("notes"))
