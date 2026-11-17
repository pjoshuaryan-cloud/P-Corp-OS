"""Tests for backend/app/post_assets.py (Cinematic Reel Autopilot phase 1: template + transition catalogues).
Uses made-up .mogrt files in a temp folder and never writes the real catalogues (out_path=None)."""
import json, sys, tempfile, zipfile, os
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import post_assets as a

FAILS = 0
def check(cond, msg):
    global FAILS
    print(("PASS " if cond else "FAIL ") + msg)
    FAILS += 0 if cond else 1

def mogrt(path, name, seconds_value, scale, w, h, tpf, controls, app="aefx"):
    d = {"authorApp": app, "capsuleName": name, "capsuleNameLocalized": {"strDB": [{"localeString": "en_US", "str": name}]},
         "clientControls": controls,
         "sourceInfoLocalized": {"en_US": {"duration": {"scale": scale, "value": seconds_value}, "framerate": {"ticksperframe": tpf},
                                           "framesize": {"size": {"x": w, "y": h}}}}}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("definition.json", json.dumps(d))

with tempfile.TemporaryDirectory() as root:
    text = {"type": 6, "value": {"strDB": [{"localeString": "en_US", "str": "YOUR TITLE"}]}}
    mogrt(f"{root}/Title A.mogrt", "Title A", 60, 12, 3840, 2160, 10160640000, [text, {"type": 2}])        # 5 s, 25 fps
    mogrt(f"{root}/Looks/Grain.mogrt", "Grain", 1001, 50, 1080, 1920, 10594584000, [{"type": 2}, {"type": 14}])  # 20.02 s, 23.976, vertical
    with open(f"{root}/Broken.mogrt", "wb") as f:
        f.write(b"not a zip")
    with open(f"{root}/notes.txt", "w") as f:
        f.write("ignore me")

    idx = a.build_template_index([root], out_path=None)
    names = [t["name"] for t in idx]
    check(names == ["Title A", "Grain"], f"two readable templates, broken one and non-template skipped, sorted by pack ({names})")
    t = next(x for x in idx if x["name"] == "Title A")
    check(t["seconds"] == 5.0 and t["fps"] == 25.0 and (t["width"], t["height"]) == (3840, 2160), "title length, frame rate and size read")
    check(t["text_fields"] == 1 and t["needs_text"] and t["default_text"] == ["YOUR TITLE"], "title's text field and default words found")
    check(t["pack"] is None and t["made_in"] == "After Effects", "top-folder template has no pack")
    g = next(x for x in idx if x["name"] == "Grain")
    check(g["pack"] == "Looks" and not g["needs_text"] and g["vertical"] and g["other_controls"] == 2, "template in a pack folder, no text, vertical")
    check(g["seconds"] == 20.02 and g["fps"] == 23.976, "fractional length and 23.976 fps")
    check(a.read_mogrt(f"{root}/Broken.mogrt") is None, "unreadable file gives None, not an error")

tr = a.build_transition_index(["AE.ADBE Whip", "ADBE Cross Zoom", "AE.AE_Impact_Directional_Blur", "AE.ADBE Cross Dissolve New",
                                "AE.ADBE Dip To Black", "ADBE Push", "AE.AE_Impact_Light_Leaks", "ADBE Page Turn", "AE.ADBE Whip"], out_path=None)
groups = {t["match_name"]: t["group"] for t in tr}
check(len(tr) == 8, "duplicates removed")
check(groups["AE.ADBE Whip"] == "blur_move" and groups["ADBE Cross Zoom"] == "blur_move" and groups["AE.AE_Impact_Directional_Blur"] == "blur_move", "whips, zooms and directional blur are blur moves")
check(groups["AE.ADBE Cross Dissolve New"] == "dissolve" and groups["AE.ADBE Dip To Black"] == "dip" and groups["ADBE Push"] == "push_slide", "dissolve, dip and push grouped")
check(groups["AE.AE_Impact_Light_Leaks"] == "light" and groups["ADBE Page Turn"] == "other", "light leak grouped, page turn other")
check([t["built_in"] for t in tr if t["match_name"] in ("AE.ADBE Whip", "AE.AE_Impact_Directional_Blur")] == [False, True][::-1] or
      (next(t for t in tr if t["match_name"] == "AE.ADBE Whip")["built_in"] and not next(t for t in tr if t["match_name"] == "AE.AE_Impact_Directional_Blur")["built_in"]),
      "Premiere's own vs third-party pack")
s = a.summary(idx, tr)
check(s["templates"] == 2 and s["templates_without_text"] == 1 and s["templates_vertical"] == 1, "summary counts templates")
check(set(s["blur_moves_built_in"]) == {"AE.ADBE Whip", "ADBE Cross Zoom"}, "summary lists built-in blur moves")
check(a.summary(None, None) == {}, "summary with nothing catalogued")

print(f"\nFAILS: {FAILS}")
sys.exit(1 if FAILS else 0)
