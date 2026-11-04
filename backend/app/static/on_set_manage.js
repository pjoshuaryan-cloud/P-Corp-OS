// Make, change and send shot lists from the owner's phone, with no Mac. The login comes from a one-time QR code on the Mac and reaches shot lists only.
// It lives in a cookie this page's scripts can't read, so this address opens nothing on anyone else's phone, however it's forwarded. Everything anyone typed goes on screen through textContent.
"use strict";
const L = window.OnSetLogic;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

let setUp = true, setupMessage = null, overview = null, current = null, screen = "home", pollTimer = null, editing = null, timing = null, lastRender = "", seenDraft = null;

function toast(text, bad) { const t = $("toast"); t.textContent = text; t.hidden = false; t.classList.toggle("bad", !!bad); clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, bad ? 7000 : 3500); }
function ask(title, body, yes) { return new Promise((resolve) => { $("askTitle").textContent = title; $("askBody").textContent = body; $("askYes").textContent = yes; $("askDialog").showModal(); $("askYes").onclick = () => { $("askDialog").close(); resolve(true); }; $("askNo").onclick = () => { $("askDialog").close(); resolve(false); }; }); }
const anyDialogOpen = () => [...document.querySelectorAll("dialog")].some((d) => d.open);

function needSetup(message) {
  clearTimeout(pollTimer); setUp = false;
  $("top").hidden = true; $("bottom").hidden = true;
  const main = $("main"); main.textContent = "";
  const box = el("div"); box.id = "needSetup";
  box.append(el("h2", "", "This phone isn't set up"), el("p", "", message || "On the Mac, open Coverage Plans, click My phone, and scan the QR code."));
  main.appendChild(box);
}

async function call(path, options, waitSeconds) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), (waitSeconds || 15) * 1000);
  let res;
  try {
    res = await fetch(path, { ...options, cache: "no-store", signal: controller.signal, headers: options && options.body ? { "Content-Type": "application/json" } : {} });
  } catch (e) {
    throw new Error("No signal. Try again when there's some.");
  } finally { clearTimeout(timer); }
  const body = await res.json().catch(() => ({}));
  if (res.status === 404 && /^This phone isn't set up/.test(body.detail || "")) { needSetup(setupMessage); throw new Error(body.detail); }
  if (!res.ok) throw new Error(body.detail || "That didn't work. Try again.");
  return body;
}
const post = (path, payload) => call(path, { method: "POST", body: JSON.stringify(payload || {}) });

const shortDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const stateOf = (l) => (l.stopped ? ["Stopped", "off"] : l.expired ? ["Ran out", "late"] : ["Live", "live"]);
const crewUrl = (token) => `${location.origin}/static/on_set.html#t=${token}`;
const clock = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }); };

// ---- all lists ------------------------------------------------------------------------------------------------------------------------------------------------
function renderHome() {
  const fingerprint = JSON.stringify(["home", overview.lists]);
  if (fingerprint === lastRender) return;
  lastRender = fingerprint;
  $("top").hidden = false; $("back").hidden = true; $("details").hidden = true; $("title").textContent = "Shot lists"; $("sub").textContent = "";
  document.title = "Shot lists";
  const main = $("main"); main.textContent = "";
  if (!overview.lists.length) main.appendChild(el("div", "empty", "No lists yet. Make one, and it can go to your crew in a tap."));
  for (const l of overview.lists) {
    const card = el("button", "list-card"); card.type = "button";
    card.appendChild(el("b", "", l.name));
    const [word, cls] = stateOf(l);
    const line = el("div", "sub"); line.append(el("span", `state ${cls}`, word), ` · ${shortDate(l.shoot_date)}${l.client ? ` · ${l.client}` : ""}`);
    const count = el("div", "sub", `${l.done} of ${l.total} shots ticked`);
    if (l.must_left) { count.append(" · "); count.appendChild(el("span", "must-left", `${l.must_left} must-have${l.must_left === 1 ? "" : "s"} left`)); }
    card.append(line, count);
    card.onclick = () => openList(l.id);
    main.appendChild(card);
  }
  $("bottom").hidden = false; $("bottomBtn").textContent = "New shot list"; $("bottomBtn").onclick = openNew;
}
async function loadHome() {
  overview = await call("/set/manage/lists");
  if (screen === "home" && !anyDialogOpen()) renderHome();
}

function openNew() {
  $("newName").value = ""; $("newClient").value = ""; $("newDate").value = L.localDate(new Date());
  const pick = $("newTemplate"); pick.textContent = "";
  for (const t of overview.templates) { const o = el("option", "", `${t.name} (${t.shots} shots)`); o.value = t.id; pick.appendChild(o); }
  const brief = el("option", "", "Draft from a brief"); brief.value = "__brief"; pick.appendChild(brief);
  const blank = el("option", "", "An empty list"); blank.value = ""; pick.appendChild(blank);
  $("newDialog").showModal();
}
$("newCancel").onclick = () => $("newDialog").close();
$("newSave").onclick = async () => {
  const name = $("newName").value.trim();
  if (!name) { $("newName").focus(); return; }
  $("newSave").disabled = true;
  try {
    const start = $("newTemplate").value;
    current = await post("/set/manage/lists", { name, client: $("newClient").value, shoot_date: $("newDate").value, template: start === "__brief" ? null : start || null });
    $("newDialog").close(); screen = "list"; lastRender = ""; renderList(); schedule();
    if (start === "__brief") openDraft();
  } catch (e) { toast(e.message, true); } finally { $("newSave").disabled = false; }
};

// ---- one list -------------------------------------------------------------------------------------------------------------------------------------------------
function shotRow(item, tick) {
  const row = el("button", `shot${item.priority === "must" ? " must" : ""}${tick && tick.done ? " done" : ""}`); row.type = "button";
  row.appendChild(el("span", "what", item.description));
  const meta = [item.priority_label, item.size_label, item.owner].filter(Boolean).join(" · ");
  if (meta) row.appendChild(el("span", "meta", meta));
  if (tick && tick.done) row.appendChild(el("span", "by", `${tick.by}, ${clock(tick.at)}${tick.note ? ` · ${tick.note}` : ""}`));
  row.onclick = () => openShot(item);
  return row;
}
function renderList() {
  if (!current) return;
  const fingerprint = JSON.stringify(["list", current]);
  if (fingerprint === lastRender) return;
  lastRender = fingerprint;
  $("top").hidden = false; $("back").hidden = false; $("details").hidden = false;
  $("title").textContent = current.name; document.title = current.name;
  const [word] = stateOf(current);
  $("sub").textContent = [word, shortDate(current.shoot_date), current.client].filter(Boolean).join(" · ");
  const main = $("main"), keep = window.scrollY; main.textContent = "";

  if (current.live && current.token) {
    const row = el("div", "primary-row");
    const send = el("button", "big primary", "Send to crew"); send.type = "button"; send.onclick = shareToCrew;
    const qr = el("button", "big", "QR code"); qr.type = "button"; qr.onclick = showQr;
    row.append(send, qr); main.appendChild(row);
    const mine = el("button", "big wide", "Open the checklist to tick"); mine.type = "button"; mine.style.marginBottom = "12px";
    mine.onclick = () => { location.href = crewUrl(current.token); };
    main.appendChild(mine);
  } else {
    const on = el("button", "big primary wide", current.stopped ? "Make a new link" : "Turn the link back on"); on.type = "button"; on.style.marginBottom = "12px";
    on.onclick = async () => { try { current = await post(`/set/manage/lists/${current.id}/link`); lastRender = ""; renderList(); toast(current.stopped ? "" : "The link is on."); } catch (e) { toast(e.message, true); } };
    main.appendChild(on);
  }

  if (current.draft && current.draft.state === "running") main.appendChild(el("div", "drafting", "Reading the brief. This usually takes a few seconds, and you can keep using your phone."));
  const progress = el("div", "progress"), track = el("div", "track"), fill = el("div"); fill.id = "fill"; fill.style.width = `${current.total ? (100 * current.done) / current.total : 0}%`;
  track.appendChild(fill); progress.append(track, `${current.done} of ${current.total} shots ticked`);
  if (current.must_left) { progress.append(" · "); progress.appendChild(el("span", "must-left", `${current.must_left} must-have${current.must_left === 1 ? "" : "s"} left`)); }
  main.appendChild(progress);

  if (!current.items.length && !(current.draft && current.draft.state === "running")) main.appendChild(el("div", "empty", "No shots yet. Add the first one below, or draft them from a brief."));
  const draft = el("button", "big wide", current.items.length ? "Replace with a draft from a brief" : "Draft from a brief"); draft.type = "button"; draft.onclick = openDraft;
  const drafting = current.draft && current.draft.state === "running";
  if (!drafting && !current.items.length) main.appendChild(draft);   // the first thing to do on an empty list; on a full one it goes below the shots, out of the way
  for (const moment of L.momentsOf(current.items)) {
    const head = el("button", "moment"); head.type = "button"; head.setAttribute("aria-label", `Set a time for ${moment.name}`);
    head.append(el("span", "", moment.name), el("span", `when${moment.time ? "" : " none"}`, moment.time || "Add time"));
    head.onclick = () => openTime(moment);
    main.appendChild(head);
    for (const item of moment.items) main.appendChild(shotRow(item, current.ticks[item.id]));
  }
  if (!drafting && current.items.length) { draft.style.marginTop = "18px"; main.appendChild(draft); }
  window.scrollTo(0, keep);
  $("bottom").hidden = false; $("bottomBtn").textContent = "Add a shot"; $("bottomBtn").onclick = () => openShot(null);
}
async function openList(id) {
  try { current = await call(`/set/manage/lists/${id}`); seenDraft = current.draft ? current.draft.finished_at : null; screen = "list"; lastRender = ""; window.scrollTo(0, 0); renderList(); schedule(); } catch (e) { toast(e.message, true); }
}
$("back").onclick = async () => { screen = "home"; current = null; lastRender = ""; window.scrollTo(0, 0); try { await loadHome(); } catch (e) { if (overview) renderHome(); toast(e.message, true); } schedule(); };

// Drafting from a brief. Photos get made smaller here: quicker on poor signal, and Claude doesn't need 12 megapixels to read a run sheet.
const asBase64 = (blob) => new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result).split(",")[1] || ""); r.onerror = reject; r.readAsDataURL(blob); });
async function readBriefFile(file) {
  if (file.type.startsWith("image/") && window.createImageBitmap) {
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas"); canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
      if (blob) return { name: `${file.name.replace(/\.[^.]+$/, "")}.jpg`, media_type: "image/jpeg", data: await asBase64(blob) };
    } catch (e) { /* send it as it is */ }
  }
  return { name: file.name, media_type: file.type, data: await asBase64(file) };
}
function openDraft() {
  $("draftText").value = ""; $("draftFiles").value = "";
  const ticked = Object.values(current.ticks).filter((t) => t.done).length;
  $("draftNote").textContent = `${current.items.length ? `This replaces the ${current.items.length} shots here${ticked ? ", and their ticks" : ""}. ` : ""}The brief goes to Anthropic. About 1¢ for a one-page brief.`;
  $("draftDialog").showModal();
}
$("draftCancel").onclick = () => $("draftDialog").close();
$("draftSave").onclick = async () => {
  const text = $("draftText").value, picked = [...$("draftFiles").files];
  if (!text.trim() && !picked.length) { $("draftText").focus(); return; }
  if (picked.length > 6) { toast("At most 6 files at a time.", true); return; }
  $("draftSave").disabled = true; $("draftSave").textContent = "Sending…";
  try {
    const files = [];
    for (const f of picked) files.push(await readBriefFile(f));
    current = await call(`/set/manage/lists/${current.id}/draft`, { method: "POST", body: JSON.stringify({ text, files }) }, 120);
    seenDraft = null; $("draftDialog").close(); lastRender = ""; renderList(); schedule();
  } catch (e) { toast(e.message, true); } finally { $("draftSave").disabled = false; $("draftSave").textContent = "Draft shot list"; }
};

// Sending it should be one tap: the phone's own share sheet where there is one, and a copied link where there isn't.
async function shareToCrew() {
  const url = crewUrl(current.token), text = `${current.name}: open this, pick your name, and tick what you get.`;
  if (navigator.share) {
    try { await navigator.share({ title: current.name, text, url }); return; } catch (e) { if (e.name === "AbortError") return; }
  }
  try { await navigator.clipboard.writeText(`${text} ${url}`); toast("Link copied. Paste it to your crew."); } catch (e) { toast("Couldn't copy it. Use the QR code instead.", true); }
}
function showQr() { const box = $("qrBox"); box.textContent = ""; box.appendChild(window.OnSetQr.qrSvg(crewUrl(current.token), document)); $("qrDialog").showModal(); }
$("qrClose").onclick = () => $("qrDialog").close();

function fillChoices() {
  const size = $("shotSize"); size.textContent = "";
  for (const s of overview.sizes) { const o = el("option", "", s.label); o.value = s.id; size.appendChild(o); }
  const pri = $("shotPriority"); pri.textContent = "";
  for (const [k, v] of Object.entries(overview.priorities)) { const o = el("option", "", v); o.value = k; pri.appendChild(o); }
  const moments = $("momentList"); moments.textContent = "";
  for (const m of new Set(current.items.map((i) => i.moment))) { const o = el("option"); o.value = m; moments.appendChild(o); }
  const owners = $("ownerList"); owners.textContent = "";
  for (const m of new Set(current.items.map((i) => i.owner).filter(Boolean))) { const o = el("option"); o.value = m; owners.appendChild(o); }
}
async function openShot(item) {
  if (!overview) { try { overview = await call("/set/manage/lists"); } catch (e) { toast(e.message, true); return; } }
  editing = item; fillChoices();
  const last = current.items[current.items.length - 1];
  $("shotTitle").textContent = item ? "Change this shot" : "Add a shot";
  $("shotWhat").value = item ? item.description : ""; $("shotMoment").value = item ? item.moment : (last ? last.moment : "");
  $("shotSize").value = item ? item.size : "any"; $("shotPriority").value = item ? item.priority : "must"; $("shotOwner").value = item ? item.owner : "";
  $("shotDelete").hidden = !item;
  $("shotDialog").showModal();
}
$("shotCancel").onclick = () => $("shotDialog").close();
$("shotSave").onclick = async () => {
  const description = $("shotWhat").value.trim();
  if (!description) { $("shotWhat").focus(); return; }
  const moment = $("shotMoment").value.trim() || "General";
  const known = current.items.find((i) => i.moment === moment && i.time);
  const fields = { description, moment, size: $("shotSize").value, priority: $("shotPriority").value, owner: $("shotOwner").value.trim() };
  if (!editing && known) fields.time = known.time;
  $("shotSave").disabled = true;
  try {
    current = await post(`/set/manage/lists/${current.id}/items${editing ? `/${editing.id}` : ""}`, fields);
    $("shotDialog").close(); lastRender = ""; renderList();
  } catch (e) { toast(e.message, true); } finally { $("shotSave").disabled = false; }
};
$("shotDelete").onclick = async () => {
  try { current = await call(`/set/manage/lists/${current.id}/items/${editing.id}`, { method: "DELETE" }); $("shotDialog").close(); lastRender = ""; renderList(); toast("Removed."); } catch (e) { toast(e.message, true); }
};

function openTime(moment) {
  timing = moment; $("timeTitle").textContent = `Time for ${moment.name}`;
  $("timeValue").value = /^\d{2}:\d{2}$/.test(moment.time) ? moment.time : "10:00";   // an empty time box on an iPhone looks like nothing to tap
  $("timeDialog").showModal();
}
async function saveTime(value) {
  try { current = await post(`/set/manage/lists/${current.id}/moment`, { moment: timing.name, time: value }); $("timeDialog").close(); lastRender = ""; renderList(); } catch (e) { toast(e.message, true); }
}
$("timeCancel").onclick = () => $("timeDialog").close();
$("timeSave").onclick = () => saveTime($("timeValue").value);
$("timeClear").onclick = () => saveTime("");

$("details").onclick = () => {
  $("detName").value = current.name; $("detClient").value = current.client; $("detDate").value = current.shoot_date;
  $("detStop").hidden = !current.live;
  $("detailsDialog").showModal();
};
$("detCancel").onclick = () => $("detailsDialog").close();
$("detSave").onclick = async () => {
  try { current = await post(`/set/manage/lists/${current.id}`, { name: $("detName").value, client: $("detClient").value, shoot_date: $("detDate").value }); $("detailsDialog").close(); lastRender = ""; renderList(); } catch (e) { toast(e.message, true); }
};
$("detStop").onclick = async () => {
  $("detailsDialog").close();
  if (!(await ask("Stop this link?", "The crew's phones lose the list straight away. Ticks are kept for the report. A new link will have a new address.", "Stop link"))) return;
  try { current = await call(`/set/manage/lists/${current.id}/link`, { method: "DELETE" }); lastRender = ""; renderList(); toast("Stopped."); } catch (e) { toast(e.message, true); }
};

// ---- keeping up with the crew's ticks -------------------------------------------------------------------------------------------------------------------------
function schedule() {
  clearTimeout(pollTimer);
  if (!setUp || document.hidden) return;
  pollTimer = setTimeout(async () => {
    try {
      if (screen === "list" && current) {
        const fresh = await call(`/set/manage/lists/${current.id}`);
        if (fresh.draft && fresh.draft.finished_at && fresh.draft.finished_at !== seenDraft) { toast(fresh.draft.message, fresh.draft.state === "failed"); seenDraft = fresh.draft.finished_at; }
        if (screen === "list" && current && fresh.id === current.id && !anyDialogOpen()) { current = fresh; renderList(); }
      } else if (screen === "home") { await loadHome(); }
    } catch (e) { /* poor signal: the next try may work, and what's on screen stays */ }
    schedule();
  }, current && current.draft && current.draft.state === "running" ? 1500 : 6000);
}
document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(pollTimer); else schedule(); });

// ---- start ----------------------------------------------------------------------------------------------------------------------------------------------------
(async function start() {
  const setup = location.hash.match(/(?:^#|&)s=([^&]+)/);
  if (setup) {
    let res;
    try {
      res = await fetch("/set/manage/claim", { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: decodeURIComponent(setup[1]) }) });
    } catch (e) { needSetup("No signal. Open the QR code's link again when there's some."); return; }
    if (!res.ok) setupMessage = (await res.json().catch(() => ({}))).detail;   // only shown if this phone isn't already set up
    history.replaceState(null, "", location.pathname);   // a used code doesn't stay in the address
  }
  try {
    await loadHome();
  } catch (e) {
    if (setUp) $("main").textContent = e.message;
  }
  schedule();
})();
