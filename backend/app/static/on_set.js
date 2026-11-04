// The on-set phone page (Shoot Logger Phase 3). Anyone with the link can see and tick one job's list. The token sits after the "#", so it never reaches a server log, and travels in a header.
// Everything other people typed goes on screen through textContent, never as HTML.
"use strict";
const L = window.OnSetLogic;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

const match = location.hash.match(/(?:^#|&)t=([^&]+)/);
const token = match ? decodeURIComponent(match[1]) : null;
const KEY = token ? `onset:${token.slice(0, 16)}` : null;

// What survives a closed tab or a dead battery: the list, every tick seen, and ticks still waiting for signal.
const state = { list: null, version: 0, lastId: 0, seen: {}, queue: [], me: "", offset: 0 };
let filter = "all", online = true, stopped = false, failures = 0, pollTimer = null, polling = false, flushing = false, noteItem = null, lastRender = "";

function loadSaved() {
  try { Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) { /* a private window: it still works until the tab closes */ }
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* see above */ }
}
function toast(text) { const t = $("toast"); t.textContent = text; t.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 3500); }

// ---- talking to the server ------------------------------------------------------------------------------------------------------------------------------------
async function call(path, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    return await fetch(path, { ...options, cache: "no-store", signal: controller.signal, headers: { "X-Set-Token": token, ...(options && options.headers) } });
  } finally { clearTimeout(timer); }
}
function setOnline(value) { online = value; render(); }
// Only the server's own words count. Any other 404 could just be a deploy in progress, and mustn't wipe a phone with ticks waiting.
async function saysStopped(res) {
  if (res.status !== 404) return false;
  const body = await res.clone().json().catch(() => ({}));
  return /^This link isn't active/.test(body.detail || "");
}
function linkStopped() {
  stopped = true; clearTimeout(pollTimer);
  try { localStorage.removeItem(KEY); } catch (e) { /* nothing was saved */ }   // a stopped link takes its list off this phone too
  for (const id of ["top", "filters", "say"]) $(id).hidden = true;
  const main = $("main"); main.textContent = "";
  const box = el("div"); box.id = "stopped";
  box.append(el("h2", "", "This link isn't active"), el("p", "", state.queue.length ? `${state.queue.length} tick${state.queue.length === 1 ? "" : "s"} on this phone didn't get sent. Ask whoever sent the link for a new one.` : "It's been stopped or has run out. Ask whoever sent it for a new one."));
  main.appendChild(box);
}

async function poll() {
  if (polling || stopped) return;
  polling = true;
  try {
    await flush();
    const res = await call(`/set/state?since=${state.lastId}&v=${state.version}`);
    if (await saysStopped(res)) { linkStopped(); return; }
    if (!res.ok) throw new Error(String(res.status));
    const body = await res.json();
    state.offset = Date.parse(body.server_time) - Date.now();
    if (body.list) { state.list = body.list; state.version = body.list_version; }
    for (const t of body.ticks) state.seen[t.id] = t;
    state.lastId = body.last_id;
    failures = 0;
    save();
    if (!online) online = true;
    render();
  } catch (e) {
    failures += 1;
    online = false;
    render();
    if (!state.list) $("main").textContent = "No signal. This page needs signal the first time it opens: it'll load by itself as soon as there is some.";
  } finally {
    polling = false;
    schedule();
  }
}
function schedule() {
  clearTimeout(pollTimer);
  if (stopped || document.hidden) return;
  const base = ((state.list && state.list.settings && state.list.settings.poll_seconds) || 5) * 1000;
  // A tick made while a request was already out goes as soon as that one's back, not at the next poll.
  pollTimer = setTimeout(poll, state.queue.length && !failures ? 200 : Math.min(30000, base * 2 ** Math.min(failures, 3)));
}

// Sends waiting ticks. They only leave the queue once the server has them, and sending one twice counts once.
async function flush() {
  if (flushing || !state.queue.length) return;
  flushing = true;
  try {
    const batch = state.queue.slice(0, 50);
    const res = await call("/set/ticks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ events: batch.map(({ event_id, item, done, by, note, at }) => ({ event_id, item, done, by, note, at })) }) });
    if (await saysStopped(res)) { linkStopped(); return; }
    if (res.ok || res.status === 400 || res.status === 422) {
      const sent = new Set(batch.map((e) => e.event_id));
      state.queue = state.queue.filter((e) => !sent.has(e.event_id));
      save();
      if (!res.ok) toast("A tick couldn't be saved.");
      else { const body = await res.json(); if (body.rejected) toast("That shot is no longer on the list."); if (body.full) toast("This list has too many ticks. Ask the DOP for help."); }
    } else { throw new Error(String(res.status)); }
  } finally { flushing = false; }
}

function nowIso() { return new Date(Date.now() + state.offset).toISOString(); }
function newId() { return (crypto.randomUUID && crypto.randomUUID()) || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`; }

function record(itemIds, done, note) {
  if (!state.me) { askWho(() => record(itemIds, done, note)); return; }
  for (const item of itemIds) state.queue.push({ event_id: newId(), item, done, by: state.me, note: (note || "").slice(0, 200), at: nowIso() });
  save();
  render();
  clearTimeout(pollTimer);
  poll();
}

// ---- the screen -----------------------------------------------------------------------------------------------------------------------------------------------
function ticksNow() { return L.foldTicks([...Object.values(state.seen), ...state.queue.map((e) => ({ item: e.item, done: e.done, by: e.by, note: e.note, at: e.at }))]); }
function whenText(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }); }
const isMine = (item) => item.owner && state.me && item.owner.toLowerCase() === state.me.toLowerCase();

function shotRow(item, ticks, waiting) {
  const tick = ticks[item.id], done = !!(tick && tick.done);
  const row = el("div", `shot${done ? " done" : ""}${item.priority === "must" ? " must" : ""}`);
  const b = el("button", "tick"); b.type = "button"; b.setAttribute("aria-pressed", String(done));
  const box = el("span", "box"); box.setAttribute("aria-hidden", "true");
  box.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'; // fixed markup, nothing anyone typed
  const words = el("span", "words");
  words.appendChild(el("span", "what", item.description));
  const meta = [item.priority_label, item.size_label, item.owner].filter(Boolean).join(" · ");
  if (meta) { const m = el("span", "meta", meta); m.style.display = "block"; words.appendChild(m); }
  if (done) {
    const line = el("span", "by", `${tick.by}, ${whenText(tick.at)}${waiting.has(item.id) ? " (not sent yet)" : ""}${tick.note ? ` · ${tick.note}` : ""}`);
    line.style.display = "block"; words.appendChild(line);
  }
  b.append(box, words);
  b.onclick = () => record([item.id], !done);
  row.appendChild(b);
  if (done) {
    const n = el("button", "notebtn", "Note"); n.type = "button"; n.setAttribute("aria-label", `Add a note to ${item.description}`);
    n.onclick = () => openNote(item);
    row.appendChild(n);
  }
  return row;
}

function render() {
  if (stopped || !state.list) return;
  const { items, name, client, shoot_date: shootDate, settings } = state.list;
  const ticks = ticksNow(), waiting = new Set(state.queue.map((e) => e.item)), now = new Date();
  const p = L.progress(items, ticks), alerts = L.alertsFor(items, ticks, now, shootDate, settings);
  const hasMine = items.some(isMine);
  // Only touch the list when something changed, so a poll doesn't jump the page or eat a tap.
  const fingerprint = JSON.stringify([items, ticks, [...waiting], filter, state.me, online, state.queue.length, alerts.map((a) => a.text)]);
  if (fingerprint === lastRender) return;
  lastRender = fingerprint;
  for (const id of ["top", "filters", "say"]) $(id).hidden = false;
  document.title = `On set: ${name}`;
  $("title").textContent = name;
  const sameDay = L.localDate(now) === shootDate;
  $("sub").textContent = [client, sameDay ? "" : `Shoot day ${new Date(`${shootDate}T12:00:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}`, state.me ? `You're ${state.me}` : ""].filter(Boolean).join(" · ");
  const net = $("net");
  net.className = online ? "" : "off";
  net.textContent = online ? (state.queue.length ? "Sending…" : "Live") : (state.queue.length ? `No signal, ${state.queue.length} waiting` : "No signal");
  $("fill").style.width = `${p.total ? (100 * p.done) / p.total : 0}%`;
  const count = $("count"); count.textContent = ""; count.className = p.mustLeft ? "" : "clear";
  count.append(`${p.done} of ${p.total} shots · `, el("b", "", p.mustLeft ? `${p.mustLeft} must-have${p.mustLeft === 1 ? "" : "s"} left` : "all must-haves ticked"));
  // Only the most urgent warning stays pinned at the top: the rest scroll away, so the list keeps the screen.
  const box = $("alerts"), more = $("moreAlerts"); box.textContent = ""; more.textContent = "";
  alerts.forEach((a, i) => (i ? more : box).appendChild(el("div", `alert ${a.level}`, a.text)));
  $("mineBtn").hidden = !hasMine;
  if (filter === "mine" && !hasMine) filter = "all";
  for (const b of document.querySelectorAll("#filters button")) b.setAttribute("aria-pressed", String(b.dataset.filter === filter));

  const main = $("main"), keep = window.scrollY; main.textContent = "";
  const show = (i) => (filter === "left" ? !(ticks[i.id] && ticks[i.id].done) : filter === "mine" ? isMine(i) : true);
  let shown = 0;
  for (const moment of L.momentsOf(items)) {
    const rows = moment.items.filter(show);
    if (!rows.length) continue;
    const h = el("div", "moment"); h.append(el("span", "", moment.name)); if (moment.time) h.append(el("span", "time", moment.time));
    main.appendChild(h);
    for (const item of rows) { main.appendChild(shotRow(item, ticks, waiting)); shown += 1; }
  }
  if (!shown) main.appendChild(el("div", "empty", filter === "left" ? "Everything's ticked." : "No shots here."));
  window.scrollTo(0, keep);
}

// ---- who, notes, voice ----------------------------------------------------------------------------------------------------------------------------------------
function askWho(then) {
  const chips = $("whoChips"); chips.textContent = "";
  const owners = [...new Set(((state.list && state.list.items) || []).map((i) => i.owner).filter(Boolean))];
  const pick = (name) => { state.me = name.trim().slice(0, 40); save(); $("whoDialog").close(); lastRender = ""; render(); if (then) then(); };
  for (const o of owners) { const b = el("button", "", o); b.type = "button"; b.onclick = () => pick(o); chips.appendChild(b); }
  $("whoInput").value = "";
  $("whoSave").onclick = () => { if ($("whoInput").value.trim()) pick($("whoInput").value); else $("whoInput").focus(); };
  $("whoDialog").showModal();
}
function openNote(item) {
  noteItem = item; $("noteFor").textContent = item.description; $("noteInput").value = ""; $("noteDialog").showModal(); $("noteInput").focus();
}
$("noteCancel").onclick = () => $("noteDialog").close();
$("noteSave").onclick = () => { const note = $("noteInput").value.trim(); $("noteDialog").close(); if (note && noteItem) record([noteItem.id], true, note); };

function showMatches(phrase) {
  const items = state.list.items, ticks = ticksNow(), found = L.matchPhrase(phrase, items);
  if (!found.length) { toast(`No shot on the list matches "${phrase}".`); return; }
  $("matchSaid").textContent = `"${phrase}"`;
  const box = $("matchList"); box.textContent = "";
  for (const m of found) {
    const already = ticks[m.item.id] && ticks[m.item.id].done;
    const row = el("label", "match"), input = el("input"); input.type = "checkbox"; input.value = m.item.id; input.checked = m.strong && !already;
    const text = el("span", "", m.item.description); text.appendChild(el("small", "", already ? `Already ticked by ${ticks[m.item.id].by}` : [m.item.size_label, m.item.moment].filter(Boolean).join(" · ")));
    row.append(input, text); box.appendChild(row);
  }
  const save2 = $("matchSave");
  const sync = () => { const n = box.querySelectorAll("input:checked").length; save2.disabled = !n; save2.textContent = n ? `Tick ${n}` : "Tick"; };
  box.onchange = sync; sync();
  save2.onclick = () => { const ids = [...box.querySelectorAll("input:checked")].map((i) => i.value); $("matchDialog").close(); if (ids.length) { record(ids, true); toast(`Ticked ${ids.length}.`); } };
  $("matchDialog").showModal();
}
$("matchCancel").onclick = () => $("matchDialog").close();
$("say").onsubmit = (e) => { e.preventDefault(); const text = $("sayText").value.trim(); if (!text) return; $("sayText").value = ""; $("sayText").blur(); showMatches(text); };

// One tap to talk where the browser can do it. Where it can't, the box is still there, and the keyboard's own mic works in it.
const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
if (Speech) {
  const mic = $("mic"); mic.hidden = false;
  let listening = null;
  mic.onclick = () => {
    if (listening) { listening.stop(); return; }
    const rec = new Speech(); rec.interimResults = true; rec.continuous = false; rec.lang = navigator.language || "en-ZA";
    let heard = "";
    rec.onresult = (ev) => { heard = Array.from(ev.results).map((r) => r[0].transcript).join(" ").trim(); $("sayText").value = heard; };
    rec.onerror = (ev) => { if (ev.error === "not-allowed" || ev.error === "service-not-allowed") toast("The mic is blocked. Type it, or use the keyboard's mic."); else if (ev.error !== "no-speech" && ev.error !== "aborted") toast("Didn't catch that. Try again, or type it."); };
    rec.onend = () => { listening = null; mic.classList.remove("listening"); $("sayText").placeholder = "Say or type what you got"; if (heard) { $("sayText").value = ""; showMatches(heard); } };
    try { rec.start(); listening = rec; mic.classList.add("listening"); $("sayText").placeholder = "Listening…"; } catch (e) { toast("Didn't catch that. Try again, or type it."); }
  };
}

// The say-it box stays above the keyboard. iPhones cover fixed things at the bottom of the page otherwise.
if (window.visualViewport) {
  const fit = () => { $("say").style.bottom = `${Math.max(0, window.innerHeight - visualViewport.height - visualViewport.offsetTop)}px`; };
  visualViewport.addEventListener("resize", fit);
  visualViewport.addEventListener("scroll", fit);
}
for (const b of document.querySelectorAll("#filters button")) b.onclick = () => { filter = b.dataset.filter; render(); };
document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(pollTimer); else poll(); });
window.addEventListener("online", () => { clearTimeout(pollTimer); poll(); });
window.addEventListener("hashchange", () => location.reload());   // a new link opened in the same tab only changes what's after the "#", so a browser won't reload by itself
setInterval(render, 30000);   // the run-sheet warnings change with the clock even when nobody ticks

// ---- start ----------------------------------------------------------------------------------------------------------------------------------------------------
(async function start() {
  if (!token) { linkStopped(); return; }
  loadSaved();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("on_set_sw.js", { scope: "/static/on_set" }).catch(() => {});
  render();
  await poll();
  if (!stopped && state.list && !state.me) askWho();
})();
