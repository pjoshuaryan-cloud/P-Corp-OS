"""Tests for the 'drive isn't plugged in' guard (backend/app/ssd_guard.py: require_connected / DriveNotConnected), as used by planning, Describe, proxies and ingest.
Run:  cd premiere-plugin/e2e && ../../backend/.venv/bin/python drive_guard_test.py"""
import os
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import post_edit_plan, post_ingest, ssd_guard  # noqa: E402
from app.ssd_guard import DriveNotConnected, DriveNotResponding, require_connected  # noqa: E402

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (f"   [{detail}]" if detail else ""))
    fails += 0 if cond else 1


with tempfile.TemporaryDirectory() as tmp:
    vols = Path(tmp) / "Volumes"
    (vols / "Joshx SSD").mkdir(parents=True)
    root = str(vols)
    check("a path on a connected drive passes through unchanged", require_connected(vols / "Joshx SSD" / "Client" / "Shoot", root) == vols / "Joshx SSD" / "Client" / "Shoot")
    try:
        require_connected(vols / "Not Plugged In" / "Client" / "Shoot", root)
        raised = None
    except DriveNotConnected as exc:
        raised = exc
    check("a path on a drive that isn't there raises DriveNotConnected, naming the drive", raised is not None and 'Not Plugged In' in raised.message and "isn't connected" in raised.message, getattr(raised, "message", None))
    check("it is a DriveNotResponding too, so the app's existing 503 handler shows its message", isinstance(raised, DriveNotResponding) and raised.message == str(raised))
    check("checking never creates the missing drive's folder", sorted(os.listdir(root)) == ["Joshx SSD"], os.listdir(root))
    check("paths outside /Volumes are never checked", require_connected("/Users/someone/Desktop/x", root) == Path("/Users/someone/Desktop/x"))
    check("the volumes folder itself passes", require_connected(root, root) == Path(root))
    nfd = unicodedata.normalize("NFD", "Café Drive")
    (vols / nfd).mkdir()
    check("a drive whose name is stored in another Unicode form still counts as connected", require_connected(vols / unicodedata.normalize("NFC", "Café Drive") / "x", root) == vols / unicodedata.normalize("NFC", "Café Drive") / "x")
    check("if /Volumes itself can't be read it does not block on a guess", require_connected("/nonexistent-root/Anything/x", "/nonexistent-root") == Path("/nonexistent-root/Anything/x"))

# ---- the real planner helpers against the real /Volumes (nothing may be created there) ---------------------------------------------------
GHOST = "/Volumes/ZZ Test Drive That Is Not Plugged In"
job = {"destination_root": GHOST + "/Client/Shoot", "profile": "alpha_mode"}
for label, call in (("edit_dir", lambda: post_edit_plan.edit_dir(job)), ("music_dir", lambda: post_edit_plan.music_dir(job)), ("find_logo", lambda: post_edit_plan.find_logo(job))):
    try:
        call()
        ok = False
    except DriveNotConnected:
        ok = True
    check(f"{label} refuses a job whose drive isn't plugged in", ok)
check("and nothing was created under /Volumes", not os.path.exists(GHOST))
with tempfile.TemporaryDirectory() as tmp2:
    local = {"destination_root": tmp2, "profile": "alpha_mode"}
    check("a job on an ordinary folder still gets its paths", post_edit_plan.edit_dir(local) == Path(tmp2) / "10_PREMIERE" / "edit_plans" and post_edit_plan.music_dir(local) == Path(tmp2) / "07_MUSIC")

# ---- ingest --------------------------------------------------------------------------------------------------------------------------------
problem = post_ingest.destination_drive_problem(GHOST + "/Client/Shoot")
check("ingest explains a missing destination drive and says Retry will work", problem and "isn't connected" in problem and "press Retry" in problem, problem)
check("ingest says nothing about a destination that is fine", post_ingest.destination_drive_problem("/tmp/anything") is None)

print(f"\nFAILS: {fails}")
sys.exit(1 if fails else 0)
