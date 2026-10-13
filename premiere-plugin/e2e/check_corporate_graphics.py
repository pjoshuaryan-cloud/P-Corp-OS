"""After Josh runs Assemble Edit on a corporate story plan WITH brand graphics: verify, from the SAVED .prproj (not the panel log), that
the b-roll, the brand cards (V2), the logo bug (V3) and the caption images (V4) are where the plan says.

    python check_corporate_graphics.py <project.prproj> <edit_plan_latest.json> [sequence name]

Without a sequence name, the newest "<shoot> - Edit <ISO time>" sequence is used. Reads via post_reference.extract_reference_edit. It can't see
whether an item is DISABLED (the plugin log reports that itself); everything else is compared frame by frame."""
import json, re, sys
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_reference as pr


def compare(plan: dict, ref: dict) -> list[tuple[bool, str]]:
    fps = plan["fps"]
    fr = lambda sec: round(sec * fps)
    out: list[tuple[bool, str]] = []
    ok = lambda cond, msg: out.append((bool(cond), msg))
    # V1: the b-roll
    shots = [s for s in ref["shots"] if s["track"] == 1]
    planned = plan["shots"]
    ok(len(shots) == len(planned), f"V1: {len(shots)} shots on the timeline, plan has {len(planned)}")
    bad = [(i + 1, fr(s["start"]), p["start_frame"]) for i, (s, p) in enumerate(zip(shots, planned)) if fr(s["start"]) != p["start_frame"] or abs(fr(s["end"]) - (p["start_frame"] + p["duration_frames"])) > 1]
    ok(not bad, f"V1: every shot at its planned start/length (off: {bad[:4]})")
    g = plan.get("graphics")
    if not g:
        ok(True, "the plan has no graphics block, nothing more to check")
        return out
    images = ref["graphics"]
    expected: list[tuple[str, int, dict]] = []
    for c in g.get("cards", []):
        expected.append(("card " + c["role"], g["tracks"]["cards"], c))
    if g.get("logo_bug"):
        expected.append(("logo bug", g["tracks"]["logo_bug"], g["logo_bug"]))
    for c in (g.get("captions") or {}).get("burned_in", []):
        expected.append(("caption", g["tracks"]["captions"], c))
    used = set()
    missing, wrong_end, wrong_track = [], [], []
    for what, track, item in expected:
        name = item["file"].split("/")[-1]
        cands = [(i, im) for i, im in enumerate(images) if i not in used and im["name"] == name and abs(fr(im["start"]) - item["start_frame"]) <= 1]
        if not cands:
            missing.append((what, item["start_frame"], name[:34]))
            continue
        i, im = cands[0]
        used.add(i)
        end = fr(im["end"])
        planned_end = item["start_frame"] + item["frames"]
        while abs(end - planned_end) > 1 and end < planned_end:  # only when it falls SHORT: a still that wouldn't stretch is continued with copies -- chain those pieces
            nxt = next(((j, c) for j, c in enumerate(images) if j not in used and c["name"] == name and c["track"] == im["track"] and abs(fr(c["start"]) - end) <= 1), None)
            if not nxt:
                break
            used.add(nxt[0])
            end = fr(nxt[1]["end"])
        if im["track"] != track:
            wrong_track.append((what, item["start_frame"], f"V{im['track']} not V{track}"))
        if abs(end - (item["start_frame"] + item["frames"])) > 1:
            wrong_end.append((what, item["start_frame"], f"ends {end}, planned {item['start_frame'] + item['frames']}"))
    ok(not missing, f"every planned image is on the timeline ({len(expected) - len(missing)} of {len(expected)} found; missing: {missing[:5]})")
    ok(not wrong_track, f"each image is on the planned track (V2 cards, V3 logo bug, V4 captions) (wrong: {wrong_track[:5]})")
    ok(not wrong_end, f"each image ends at its planned frame, within one frame (off: {wrong_end[:5]})")
    extra = [im for i, im in enumerate(images) if i not in used and im["name"].startswith("corp_")]
    ok(not extra, f"no stray brand images left over from this run ({len(extra)} extra: {[e['name'][:30] for e in extra[:3]]})")
    pieces = {}
    for im in images:
        pieces.setdefault((im["name"], im["track"]), []).append((fr(im["start"]), fr(im["end"])))
    for (name, track), spans in pieces.items():
        if len(spans) > 1 and name.startswith("corp_card_"):
            out.append((True, f"note: {name[:34]} on V{track} is in {len(spans)} pieces {sorted(spans)} (the plugin continued it because the image wouldn't stretch)"))
    return out


if __name__ == "__main__":
    prproj, plan_path = sys.argv[1], sys.argv[2]
    plan = json.load(open(plan_path))
    names = pr.sequence_names(prproj)
    seq = sys.argv[3] if len(sys.argv) > 3 else max((n for n in names if re.search(r" - Edit \d{4}-\d\d-\d\dT", n)), key=lambda n: re.search(r"Edit (\S+)", n).group(1))
    print(f"project {prproj.split('/')[-1]} | sequence {seq!r} | plan {plan_path.split('/')[-1]} ({len(plan['shots'])} shots, graphics: {bool(plan.get('graphics'))})")
    results = compare(plan, pr.extract_reference_edit(prproj, seq))
    for good, msg in results:
        print(("PASS " if good else "FAIL ") + msg)
    print("\nALL PASSED" if all(g for g, _ in results) else f"\n{sum(1 for g, _ in results if not g)} FAILED")
