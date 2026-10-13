"""Verify a multicam talking-head edit from the SAVED .prproj: each V1 shot's SOURCE FILE and in-point, the same conversation moment across cameras, the dialogue on A2.
usage: check_multicam.py <project.prproj> <edit_plan_latest.json> <json mapping camera file name -> seconds of conversation at its t=0> [sequence]"""
import json, re, sys
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_reference as pr

def source_file(sub, ids):
    """Walks the project's object graph from a subclip to the media file it plays."""
    seen, frontier = set(), [sub]
    for _ in range(10):
        nxt = []
        for el in frontier:
            for e in el.iter():
                if e.tag == "ActualMediaFilePath" and e.text: return e.text
                for k in ("ObjectRef", "ObjectURef"):
                    r = e.attrib.get(k)
                    if r and r not in seen and r in ids: seen.add(r); nxt.append(ids[r])
        frontier = nxt
    return None

def check(prproj, plan, offsets, seq_name=None):
    fps = plan["fps"]; tpf = pr.TICKS_PER_SECOND / fps; out = []
    ok = lambda c, m: out.append((bool(c), m))
    names = [n for n in pr.sequence_names(prproj) if " - Edit " in n]
    seq_name = seq_name or max(names, key=lambda n: re.search(r"Edit (\S+)", n).group(1))
    root, ids = pr._load(prproj)
    seq = next(s for s in root.iter("Sequence") if (n := s.find("Name")) is not None and n.text == seq_name)
    video, audio = [], []
    for tg in seq.findall("TrackGroups/TrackGroup"):
        group = ids.get(tg.find("Second").attrib.get("ObjectRef", ""))
        if group is None or group.tag not in ("VideoTrackGroup", "AudioTrackGroup"): continue
        for tr in group.findall("TrackGroup/Tracks/Track"):
            track = ids[tr.attrib["ObjectURef"]]; items = []
            for r in track.findall("ClipTrack/ClipItems/TrackItems/TrackItem"):
                item = ids[r.attrib["ObjectRef"]]; timing = item.find("ClipTrackItem/TrackItem")
                sub = ids[item.find("ClipTrackItem/SubClip").attrib["ObjectRef"]]; clip = ids[sub.find("Clip").attrib["ObjectRef"]]
                items.append({"start": pr._ticks(timing, "Start"), "end": pr._ticks(timing, "End"), "in": pr._ticks(clip, "Clip/InPoint") / pr.TICKS_PER_SECOND,
                              "file": (source_file(sub, ids) or "").split("/")[-1], "name": sub.find("Name").text})
            (video if group.tag == "VideoTrackGroup" else audio).append(items)
    v1 = video[0]; shots = plan["shots"]
    ok(len(v1) == len(shots), f"V1: {len(v1)} shots on the timeline, plan has {len(shots)}")
    ok(all(it["start"] == round(s["start_frame"] * tpf) and abs(it["end"] - it["start"] - s["duration_frames"] * tpf) < 2 for it, s in zip(v1, shots)), "V1: every shot at its planned start and length (to the tick)")
    ok(all(it["file"] == s["name"] for it, s in zip(v1, shots)), f"every shot plays the planned CAMERA FILE: {[it['file'] for it in v1]}")
    ok(all(abs(it["in"] - s["source_in"]) <= 1.0 / fps for it, s in zip(v1, shots)), f"every shot starts at the planned in-point (within a frame): {[round(it['in'], 2) for it in v1]} vs {[s['source_in'] for s in shots]}")
    t0 = plan["dialogue"]["starts_at_interview_seconds"]
    errs = [abs((it["in"] + offsets[it["file"]]) - (offsets["CAM_A.mp4"] + t0 + s["start_frame"] / fps)) for it, s in zip(v1, shots)]
    ok(max(errs) < 1.5 / fps, f"EVERY shot plays the SAME conversation moment whichever camera it uses (max error {max(errs) * 1000:.0f} ms, one frame is {1000 / fps:.0f} ms)")
    ok(all(a["file"] != b["file"] for a, b in zip(v1, v1[1:])), "the camera changes at every cut")
    a2 = audio[1] if len(audio) > 1 else []
    ok(len(a2) == 1 and a2[0]["file"].endswith("_dialogue.wav") and a2[0]["start"] == 0 and abs(a2[0]["end"] - plan["duration_frames"] * tpf) < 2, f"A2: one dialogue track from 0 to the full length: {[(a['file'], a['start'], round(a['end'] / pr.TICKS_PER_SECOND, 2)) for a in a2]}")
    return seq_name, out

if __name__ == "__main__":
    prproj, plan_path, offsets = sys.argv[1], json.load(open(sys.argv[2])), json.loads(sys.argv[3])
    seq, results = check(prproj, plan_path, offsets, sys.argv[4] if len(sys.argv) > 4 else None)
    print("sequence:", seq)
    for good, msg in results: print(("PASS " if good else "FAIL ") + msg)
    print("\nALL PASSED" if all(g for g, _ in results) else f"\n{sum(1 for g, _ in results if not g)} FAILED")
