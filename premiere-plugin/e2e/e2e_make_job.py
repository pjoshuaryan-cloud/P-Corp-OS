"""usage: e2e_make_job.py <shoot name> <source dir> <out file for the job id>  -- creates, ingests and analyses a TEST job via the real backend; adds a logo and a song."""
import sys, os, time, shutil; sys.path.insert(0, "."); import e2e_api as a
shoot, src, outfile = sys.argv[1:4]; SP = os.getcwd()
jid = a.ok("POST", "/post/jobs", json={"profile": "alpha_mode", "client_name": "ZZTest", "shoot_name": shoot, "source_path": f"{SP}/{src}", "destination_volume_path": f"{SP}/e2e/dest",
                                      "deliverable_format": os.environ.get("E2E_FORMAT", "16:9"), "resolution": "4k_uhd", "frame_rate": "24"})["id"]
open(outfile, "w").write(str(jid)); print("created test job #", jid)
a.ok("POST", f"/post/jobs/{jid}/start"); j = a.wait_status(jid, {"ingested"}, timeout=600)
print("ingested:", j["total_files"], "files,", j["files_copied"], "copied,", j["files_failed"], "failed")
a.ok("POST", f"/post/jobs/{jid}/analyze-media"); t0 = time.time()
while time.time() - t0 < 600:
    j = a.job(jid)
    if j.get("media_analyzed_at") and j["status"] == "ingested": break
    time.sleep(2)
root = j["destination_root"]; os.makedirs(f"{root}/06_GRAPHICS", exist_ok=True); os.makedirs(f"{root}/07_MUSIC", exist_ok=True)
shutil.copyfile("gfx/test_logo.png", f"{root}/06_GRAPHICS/logo.png")
shutil.copyfile("/Users/joshuapeters/Downloads/Channel 13 - Do You Remember - Instrumental Version.mp3", f"{root}/07_MUSIC/bed.mp3")
print("analysed:", bool(j.get("media_analyzed_at")), "| root:", root)
