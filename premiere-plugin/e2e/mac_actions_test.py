"""Tests for Frank's hands on the Mac (backend/app/mac_actions.py + mac_tools.py, 2026-11-20). Everything happens in temp folders that stand in for the home
folder, a plugged-in drive and iCloud Drive, and a temp SQLite file stands in for the cloud database. Nothing is opened on screen, nothing goes to the real
Bin, nothing is uploaded: those calls are fakes."""
import asyncio, json, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, "/Users/joshuapeters/Desktop/P-Corp/backend")
from app import mac_actions as ma, mac_tools as mt
from app.mac_actions import MacActionError

FAILS = 0
def check(msg, cond, extra=""):
    global FAILS
    line = ("PASS " if cond else "FAIL ") + msg
    if not cond and extra != "":
        line += f"   {extra}"
    print(line)
    FAILS += 0 if cond else 1

def refused(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except MacActionError as exc:
        return str(exc)

tmp = Path(tempfile.mkdtemp(prefix="mac_actions_test_")).resolve()
HOME, DRIVE = tmp / "home", tmp / "Volumes" / "Joshx"
for d in (HOME / "Desktop" / "Invoices", HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs", HOME / "Library" / "Keychains", HOME / ".ssh",
          HOME / "P-Corp" / "backend" / "data", DRIVE / "Shoots" / "JD Sports"):
    d.mkdir(parents=True)
(HOME / "Desktop" / "Invoices" / "JD invoice Nov.pdf").write_bytes(b"%PDF-1.4 test")
(HOME / "Desktop" / "notes.txt").write_text("hi")
(HOME / ".ssh" / "id_rsa").write_text("secret")
(HOME / "Library" / "Keychains" / "login.keychain-db").write_text("secret")
(HOME / "Desktop" / ".env").write_text("KEY=1")
(HOME / "P-Corp" / "backend" / "data" / "audit.db").write_text("x")
(DRIVE / "Shoots" / "JD Sports" / "JD hero shot.mp4").write_bytes(b"0" * 2000)
(DRIVE / "Shoots" / "JD Sports" / "other.mov").write_bytes(b"0")

ma.HOME = HOME
ma.ICLOUD = HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
ma.ICLOUD_INBOX = ma.ICLOUD / "P Corp Inbox"
ma.REPO_DATA = HOME / "P-Corp" / "backend" / "data"
ma.REPO_ENV = HOME / "P-Corp" / "backend" / ".env"
ma._roots = lambda: [HOME, DRIVE]
ma.DB_PATH = tmp / "mac_actions.db"

# ---------------------------------------------------------------- the folder rules
check("a file in the home folder is allowed", ma.safe_path(str(HOME / "Desktop" / "notes.txt")) == HOME / "Desktop" / "notes.txt")
check("a file on a plugged-in drive is allowed", ma.safe_path(str(DRIVE / "Shoots")) == DRIVE / "Shoots")
check("iCloud Drive is allowed even though it sits in Library", ma.safe_path(str(ma.ICLOUD)) == ma.ICLOUD)
for label, p in [("a system folder", "/etc/hosts"), ("the rest of Library", HOME / "Library" / "Keychains" / "login.keychain-db"),
                 ("a hidden folder (.ssh)", HOME / ".ssh" / "id_rsa"), ("a .env file", HOME / "Desktop" / ".env"),
                 ("P Corp's own data", ma.REPO_DATA / "audit.db"), ("climbing out with ..", str(HOME / "Desktop" / ".." / ".." / ".." ))]:
    check(f"{label} is refused", refused(ma.safe_path, str(p)) is not None, p)
check("a missing file is refused with its path", "Nothing at" in (refused(ma.safe_path, str(HOME / "nope.txt")) or ""))
link = HOME / "Desktop" / "sneaky"
link.symlink_to(HOME / ".ssh")
check("a link that points into a hidden folder is refused (the real path is checked)", refused(ma.safe_path, str(link / "id_rsa")) is not None)

# ---------------------------------------------------------------- find
out = ma.find_files("jd hero", folder=str(DRIVE))
check("find on a drive matches every word in the name, any case", [r["name"] for r in out["results"]] == ["JD hero shot.mp4"], out)
check("find gives size and modified time", out["results"][0]["size"] == 2000 and out["results"][0]["modified"])
check("find with no words is refused", refused(ma.find_files, "  ") is not None)

# ---------------------------------------------------------------- copy / move / rename
src = HOME / "Desktop" / "notes.txt"
out = ma.copy_move(str(src), str(DRIVE / "Shoots"), "copy")
check("copy into a folder keeps the name and leaves the original", (DRIVE / "Shoots" / "notes.txt").read_text() == "hi" and src.exists(), out)
check("copying again refuses rather than overwrite", "nothing was overwritten" in (refused(ma.copy_move, str(src), str(DRIVE / "Shoots"), "copy") or ""))
out = ma.copy_move(str(DRIVE / "Shoots" / "notes.txt"), "notes old.txt", "rename")
check("rename keeps it in the same folder", (DRIVE / "Shoots" / "notes old.txt").exists() and not (DRIVE / "Shoots" / "notes.txt").exists(), out)
check("rename with a folder in the new name is refused", refused(ma.copy_move, str(DRIVE / "Shoots" / "notes old.txt"), "../x.txt", "rename") is not None)
out = ma.copy_move(str(DRIVE / "Shoots" / "notes old.txt"), str(HOME / "Desktop" / "Invoices"), "move")
check("move takes it out of the old folder", (HOME / "Desktop" / "Invoices" / "notes old.txt").exists() and not (DRIVE / "Shoots" / "notes old.txt").exists())
check("copying into a hidden folder is refused", refused(ma.copy_move, str(src), str(HOME / ".ssh"), "copy") is not None)
check("copying a key out is refused", refused(ma.copy_move, str(HOME / ".ssh" / "id_rsa"), str(HOME / "Desktop"), "copy") is not None)
check("an unknown mode is refused", refused(ma.copy_move, str(src), str(DRIVE), "delete") is not None)

# ---------------------------------------------------------------- bin, apps, websites (refusals only; nothing is opened or binned)
check("binning the whole home folder is refused", refused(ma.move_to_bin, str(HOME)) is not None)
check("binning a whole drive is refused", refused(ma.move_to_bin, str(DRIVE)) is not None)
check("binning a key is refused", refused(ma.move_to_bin, str(HOME / ".ssh" / "id_rsa")) is not None)
check("an app path instead of a name is refused", refused(ma.open_app, "/bin/sh") is not None)
check("a made-up app is refused", "No app called" in (refused(ma.open_app, "Definitely Not An App 9000") or ""))
for bad in ("file:///etc/passwd", "javascript:alert(1)", ""):
    check(f"a non-web address is refused ({bad or 'empty'})", refused(ma.open_url, bad) is not None)

# ---------------------------------------------------------------- send to phone: small -> cloud, big -> iCloud Drive
staged = ma.stage_for_phone(str(HOME / "Desktop" / "Invoices" / "JD invoice Nov.pdf"))
check("a small file goes by the cloud inbox with its bytes read", staged["via"] == "cloud" and staged["content"] == b"%PDF-1.4 test")
ma.INBOX_MAX_BYTES = 1000
staged = ma.stage_for_phone(str(DRIVE / "Shoots" / "JD Sports" / "JD hero shot.mp4"))
check("a big file is copied into iCloud Drive > P Corp Inbox instead", staged["via"] == "icloud" and (ma.ICLOUD_INBOX / "JD hero shot.mp4").exists(), staged)
staged = ma.stage_for_phone(str(DRIVE / "Shoots" / "JD Sports" / "JD hero shot.mp4"))
check("sending the same big file again doesn't overwrite the first copy", staged["name"] != "JD hero shot.mp4" and len(list(ma.ICLOUD_INBOX.iterdir())) == 2, staged)
check("a folder can't be sent", refused(ma.stage_for_phone, str(DRIVE / "Shoots")) is not None)
ma.INBOX_MAX_BYTES = 45 * 1024 * 1024


# ---------------------------------------------------------------- the tools, the tap, and the phone relay
class FakeSocket:
    def __init__(self, answer):
        self.answer, self.sent = answer, []
    async def send_text(self, text):
        self.sent.append(text)
    async def receive_text(self):
        card = json.loads(self.sent[-1].removeprefix("\n[mac_approval_request]"))
        if self.answer == "wrong-id":
            return json.dumps({"approval_response": {"id": "someone-else", "approved": True}})
        return json.dumps({"approval_response": {"id": card["id"], "approved": self.answer == "yes"}})


async def scenario():
    uploads = []
    async def fake_upload(name, content):
        uploads.append((name, len(content)))
        return f"macinbox-abc123-{name}"
    ma.upload_to_inbox = fake_upload
    deleted = []
    async def fake_delete(key):
        deleted.append(key)
    ma.delete_from_inbox = fake_delete

    # on the Mac: tap needed for changes, not for finding
    mt.on_the_mac = lambda: True
    ws = FakeSocket("no")
    text, doc = await mt.execute_mac_tool_call("copy_or_move_on_mac", {"source": str(src), "destination": str(DRIVE), "mode": "copy"}, ws)
    check("a copy shows the Mac card first", ws.sent and ws.sent[0].startswith("\n[mac_approval_request]") and "Copy on your Mac" in ws.sent[0])
    check("saying no does nothing", "said no" in text and not (DRIVE / "notes.txt").exists(), text)
    ws = FakeSocket("wrong-id")
    text, _ = await mt.execute_mac_tool_call("move_to_bin_on_mac", {"path": str(src)}, ws)
    check("a yes for a different card counts as no", "said no" in text and src.exists())
    ws = FakeSocket("yes")
    text, doc = await mt.execute_mac_tool_call("copy_or_move_on_mac", {"source": str(src), "destination": str(DRIVE), "mode": "copy"}, ws)
    check("saying yes does it", (DRIVE / "notes.txt").exists() and doc is None, text)
    ws = FakeSocket("yes")
    text, _ = await mt.execute_mac_tool_call("find_files_on_mac", {"query": "hero", "folder": str(DRIVE)}, ws)
    check("finding needs no card and lists the path", not ws.sent and "JD hero shot.mp4" in text, text)
    text, _ = await mt.execute_mac_tool_call("open_on_mac", {"path": str(HOME / ".ssh")}, FakeSocket("yes"))
    check("a refusal comes back as words, not a crash", text.startswith("Couldn't do it:") and "Hidden" in text, text)
    ws = FakeSocket("yes")
    text, doc = await mt.execute_mac_tool_call("send_file_to_phone", {"path": str(HOME / "Desktop" / "Invoices" / "JD invoice Nov.pdf")}, ws)
    check("sending asks first, then uploads and returns the chat attachment", "Send to your iPhone" in ws.sent[0] and uploads == [("JD invoice Nov.pdf", 13)]
          and doc == {"filename": "macinbox-abc123-JD invoice Nov.pdf", "title": "JD invoice Nov.pdf"}, (text, doc))
    rows = await ma._run(None, "SELECT storage_key FROM mac_inbox")
    check("the sent file is recorded so it can be removed after 24 hours", rows == [("macinbox-abc123-JD invoice Nov.pdf",)], rows)

    # from the phone: the cloud server queues for the Mac
    mt.on_the_mac = lambda: False
    text, _ = await mt.execute_mac_tool_call("find_files_on_mac", {"query": "hero"}, FakeSocket("yes"), postgres_conn=None)
    check("without the shared database the cloud says so plainly", "shared database" in text, text)
    real_run = mt._run
    async def via_sqlite(action, a, conn):   # the same relay code, with the temp SQLite file as the shared database
        if not await ma.mac_online(None):
            raise MacActionError("Your Mac isn't answering")
        action_id = await ma.queue(action, a, None)
        return await relay_wait(action_id)
    async def relay_wait(action_id):
        out = await ma.wait_for(action_id, 8, None)
        if out is None:
            raise MacActionError("Your Mac took too long to answer.")
        if out["status"] == "failed":
            raise MacActionError(out["result"]["error"])
        return out["result"]
    mt._run = via_sqlite
    await ma._run(None, "DELETE FROM mac_worker")
    text, _ = await mt.execute_mac_tool_call("find_files_on_mac", {"query": "hero", "folder": str(DRIVE)}, FakeSocket("yes"))
    check("with the Mac off the phone is told plainly", "isn't answering" in text, text)

    async def mac_side():   # the Mac's loop, a few passes
        for _ in range(30):
            await mt.relay_pass(None)
            await asyncio.sleep(0.2)
    await ma.heartbeat(None)
    mac = asyncio.create_task(mac_side())
    text, _ = await mt.execute_mac_tool_call("find_files_on_mac", {"query": "hero", "folder": str(DRIVE)}, FakeSocket("yes"))
    check("a phone request is run by the Mac and the answer comes back", "JD hero shot.mp4" in text, text)
    text, _ = await mt.execute_mac_tool_call("open_on_mac", {"path": "/etc/hosts"}, FakeSocket("yes"))
    check("a refusal on the Mac comes back to the phone as words", "outside your home folder" in text, text)
    ws = FakeSocket("no")
    text, _ = await mt.execute_mac_tool_call("move_to_bin_on_mac", {"path": str(src)}, ws)
    rows = await ma._run(None, "SELECT COUNT(*) FROM mac_actions WHERE action = 'move_to_bin'")
    check("a no on the phone never reaches the Mac", "said no" in text and rows[0][0] == 0 and src.exists())
    mac.cancel()
    mt._run = real_run

    # queue housekeeping
    old = ma._ago(ma.QUEUE_EXPIRES_SECONDS + 5)
    await ma._run(None, "INSERT INTO mac_actions (created_at, action, args_json, status, updated_at) VALUES (?, 'open_url', '{}', 'new', ?)", (old, old))
    check("an old request the Mac never saw expires instead of running late", await ma.claim(None) is None)
    rows = await ma._run(None, "SELECT status FROM mac_actions WHERE created_at = ?", (old,))
    check("…and is marked expired", rows == [("expired",)], rows)
    await ma._run(None, "UPDATE mac_inbox SET created_at = ?", (ma._ago(25 * 3600),))
    await mt.relay_pass(None)
    rows = await ma._run(None, "SELECT COUNT(*) FROM mac_inbox")
    check("a phone file older than 24 hours is removed from storage and forgotten", deleted == ["macinbox-abc123-JD invoice Nov.pdf"] and rows[0][0] == 0, (deleted, rows))
    await ma._run(None, "UPDATE mac_worker SET seen_at = ?", (ma._ago(60),))
    check("a Mac that hasn't beaten for a minute counts as offline", not await ma.mac_online(None))

asyncio.run(scenario())

audit = Path("/Users/joshuapeters/Desktop/P-Corp/backend/data/audit.db")
if audit.exists():
    import sqlite3
    n = sqlite3.connect(f"file:{audit}?mode=ro", uri=True).execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
    check("the real audit log is untouched (722 tool calls)", n == 722, n)
print(f"\n{'ALL PASS' if FAILS == 0 else f'{FAILS} FAILED'}")
sys.exit(1 if FAILS else 0)
