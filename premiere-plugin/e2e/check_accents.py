"""Compare the newest 'Edit <ISO>' sequence in a saved .prproj against edit_plan_latest.json (shots + accents).
usage: check_accents.py <project.prproj> [sequence-name-prefix] [edit_plan_latest.json]"""
import json, sys
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_reference as pr

proj = sys.argv[1]
prefix = sys.argv[2] if len(sys.argv) > 2 else "JD Sports - MOA Store Opening - Edit "
names = sorted(n for n in pr.sequence_names(proj) if n.startswith(prefix))
seq_name = names[-1]
print("sequence:", seq_name)
ref = pr.extract_reference_edit(proj, seq_name)
plan = json.load(open(sys.argv[3] if len(sys.argv) > 3 else "/Volumes/Joshx SSD/JD Sports/JD Sports - MOA Store Opening/10_PREMIERE/edit_plans/edit_plan_latest.json"))
FPS = plan["fps"]
acc = plan["accents"]
fr = lambda s: round(s * FPS)
problems = []

def bad(msg):
    problems.append(msg)
    print("  PROBLEM:", msg)

# --- video tracks: re-extract by raw track so we see V1..V4 separately
import gzip, xml.etree.ElementTree as ET
root, ids = pr._load(proj)
seq = next(s for s in root.iter("Sequence") if (n := s.find("Name")) is not None and n.text == seq_name)
tracks = {"V": [], "A": []}
for tg in seq.findall("TrackGroups/TrackGroup"):
    group = ids.get(tg.find("Second").attrib.get("ObjectRef", ""))
    if group is None or group.tag not in ("VideoTrackGroup", "AudioTrackGroup"):
        continue
    for tr in group.findall("TrackGroup/Tracks/Track"):
        track = ids[tr.attrib["ObjectURef"]]
        items = []
        for r in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
            item = ids[r.attrib["ObjectRef"]]
            timing = item.find("ClipTrackItem/TrackItem")
            sub = ids[item.find("ClipTrackItem/SubClip").attrib["ObjectRef"]]
            clip = ids[sub.find("Clip").attrib["ObjectRef"]]
            items.append({
                "name": sub.find("Name").text,
                "s": round(pr._ticks(timing, "Start") / pr.TICKS_PER_SECOND * FPS),
                "e": round(pr._ticks(timing, "End") / pr.TICKS_PER_SECOND * FPS),
                "s_exact": pr._ticks(timing, "Start"), "e_exact": pr._ticks(timing, "End"),
                "in": pr._ticks(clip, "Clip/InPoint") / pr.TICKS_PER_SECOND,
                "out": pr._ticks(clip, "Clip/OutPoint") / pr.TICKS_PER_SECOND,
                "effects": pr._effects(item, ids), "params": pr._effect_params(item, ids), "sub": sub,
            })
        tracks["V" if group.tag == "VideoTrackGroup" else "A"].append(items)
V, A = tracks["V"], tracks["A"]
print("tracks:", {f"V{i+1}": len(t) for i, t in enumerate(V)}, {f"A{i+1}": len(t) for i, t in enumerate(A)})
tpf = pr.TICKS_PER_SECOND // FPS

# ---- V1 shots
print("\n[V1 shots]")
off = 0
for it, shot in zip(V[0], plan["shots"]):
    if it["s_exact"] != shot["start_frame"] * tpf or it["e_exact"] - it["s_exact"] != shot["duration_frames"] * tpf:
        off += 1; bad(f"shot {shot['index']}: at {it['s']}-{it['e']} fr, plan {shot['start_frame']}+{shot['duration_frames']}")
print(f"  {len(V[0])} on V1 vs {len(plan['shots'])} planned, {off} off the plan's frames")
fallback = [it["name"] for it in V[0] if "_h" in it["name"].split("_")[-1:][0] or it["name"].endswith("_h")]
print("  fallback '_h' subclips:", fallback or "none")
print("  sample names:", [it["name"] for it in V[0][:3]])

# BoundariesAreHard on the subclips behind V1
masters = {m.attrib.get("ObjectUID"): m for m in root.iter("MasterClip")}
hard = soft = unread = 0
for it in V[0]:
    mc = masters.get(it["sub"].find("MasterClip").attrib.get("ObjectURef")) if it["sub"].find("MasterClip") is not None else None
    if mc is None: unread += 1; continue
    src = ids[ids[mc.find("Clips/Clip").attrib["ObjectRef"]].find("Clip/Source").attrib["ObjectRef"]]
    flag = src.find("MediaSource/Content/BoundariesAreHard")
    if flag is not None and (flag.text or "").strip().lower() == "false": soft += 1
    else: hard += 1
print(f"  subclips with BoundariesAreHard=false (stretchable): {soft} | hard/absent: {hard} | unreadable: {unread}")

# per-shot effects on V1
print("\n[V1 per-shot effects]")
want = {e["shot_index"]: e for e in acc["shot_effects"]}
for it, shot in zip(V[0], plan["shots"]):
    w = want.get(shot["index"])
    got = it["effects"]
    if w is None:
        if got: bad(f"shot {shot['index']} has unplanned effects {got}")
        continue
    if w["effect"] not in got:
        bad(f"shot {shot['index']}: wanted {w['effect']}, found {got}")
        continue
    if w["params"]:
        gp = it["params"].get(w["effect"], {})
        for k, v in w["params"].items():
            if abs(gp.get(k, -9999) - v) > 0.01: bad(f"shot {shot['index']}: {k} = {gp.get(k)} (want {v})")
n_ok = sum(1 for it, s in zip(V[0], plan["shots"]) if s["index"] in want and want[s["index"]]["effect"] in it["effects"])
print(f"  planned {len(want)} | present {n_ok}")

# ---- V2 overlays
print("\n[V2 adjustment layers]")
planned = [*acc["flashes"], *acc["zoom_hits"]]
got = sorted(V[1], key=lambda x: x["s"])
print(f"  {len(got)} on V2 vs {len(planned)} planned")
by_start = {}
for it in got: by_start.setdefault(it["s"], []).append(it)
for p in sorted(planned, key=lambda x: x["start_frame"]):
    cands = by_start.get(p["start_frame"], [])
    if not cands:
        near = [i for i in got if abs(i["s"] - p["start_frame"]) <= 3]
        bad(f"{p['kind']} planned at frame {p['start_frame']} not found on V2" + (f" (nearest: {[(n['s'], n['e']-n['s']) for n in near]})" if near else ""))
        continue
    it = cands[0]
    length = it["e"] - it["s"]
    msgs = []
    if length != p["frames"]: msgs.append(f"length {length} fr (planned {p['frames']})")
    if it["name"] != "Adjustment Layer": msgs.append(f"clip name {it['name']!r}")
    if p["effect"] not in it["effects"]: msgs.append(f"effect missing: found {it['effects']}")
    else:
        gp = it["params"].get(p["effect"], {})
        for k, v in p["params"].items():
            if k in ("Slices",): continue
            if abs(gp.get(k, -9999) - v) > 0.01: msgs.append(f"{k}={gp.get(k)} (want {v})")
    status = "OK " if not msgs else "BAD"
    print(f"  {status} {p['kind']:9s} @ {p['start_frame']:4d} x{p['frames']}  -> found {it['s']}-{it['e']} {it['effects']} {it['params'].get(p['effect'], {})}" + (f"  !! {'; '.join(msgs)}" if msgs else ""))
    if msgs: problems.append(f"{p['kind']}@{p['start_frame']}: {'; '.join(msgs)}")
extra = [i for i in got if i["s"] not in {p["start_frame"] for p in planned}]
if extra: bad(f"unplanned items on V2: {[(i['name'], i['s'], i['e']) for i in extra]}")

# ---- V4 logo
print("\n[V4 logo]")
lg = acc["logo"]
for it in V[3] if len(V) > 3 else []:
    print(f"  {it['name']} {it['s']}-{it['e']} ({it['e']-it['s']} fr) | planned {lg['start_frame']} x{lg['frames']}")
    if it["s"] != lg["start_frame"] or it["e"] - it["s"] != lg["frames"]: bad("logo timing differs from plan")
if len(V) < 4 or not V[3]: bad("no logo on V4")
print("  V3:", len(V[2]) if len(V) > 2 else "n/a", "items")

# ---- audio
print("\n[audio]")
for ti, tr in enumerate(A, 1):
    for it in sorted(tr, key=lambda x: x["s"]):
        print(f"  A{ti} {it['name'][:44]:44s} {it['s']:4d}-{it['e']:4d} ({it['e']-it['s']:3d} fr)  source {it['in']:.2f}-{it['out']:.2f}")
sfx = acc["sfx"]
for p in sfx:
    tr = A[p["track"] - 1] if len(A) >= p["track"] else []
    match = [i for i in tr if i["s"] == p["start_frame"]]
    if not match:
        near = [(i["name"], i["s"], i["e"] - i["s"]) for i in tr if abs(i["s"] - p["start_frame"]) <= 4]
        bad(f"sfx {p['name']} planned A{p['track']} @ {p['start_frame']} not found" + (f" (nearby: {near})" if near else ""))
        continue
    it = match[0]
    ok = (it["e"] - it["s"]) == p["frames"]
    print(f"  {'OK ' if ok else 'BAD'} sfx {p['name'][:30]:30s} A{p['track']} @ {p['start_frame']} x{p['frames']} -> found {it['s']}-{it['e']} source in {it['in']:.2f}")
    if not ok: bad(f"sfx {p['name']} length {it['e']-it['s']} (planned {p['frames']})")

print("\n=== SUMMARY ===")
print("problems:", len(problems))
for p in problems: print(" -", p)
