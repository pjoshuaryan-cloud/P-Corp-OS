// The on-set page's thinking, with no screen in it, so it can be tested on its own: where each shot stands, what's coming up on the run sheet, and what a spoken phrase means.
// It all runs on the phone. A voice note never leaves it, and matching one costs nothing.
(function (exports) {
  "use strict";

  // ---- where each shot stands ---------------------------------------------------------------------------------------------------------------------------------
  // The latest thing anyone did to a shot, by when they did it. Ticks still waiting for signal have no id yet and sort after the rest at the same moment.
  function foldTicks(events) {
    const out = {};
    const ordered = events.slice().sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : (a.id === undefined ? Infinity : a.id) - (b.id === undefined ? Infinity : b.id)));
    for (const e of ordered) {
      const previous = out[e.item];
      const note = e.note || (previous && e.done && previous.done ? previous.note : "");
      out[e.item] = { done: !!e.done, by: e.by, at: e.at, note: note || "" };
    }
    return out;
  }

  function progress(items, ticks) {
    let done = 0, mustLeft = 0;
    for (const item of items) {
      const isDone = ticks[item.id] && ticks[item.id].done;
      if (isDone) done += 1;
      else if (item.priority === "must") mustLeft += 1;
    }
    return { done, total: items.length, mustLeft };
  }

  // ---- the run sheet ------------------------------------------------------------------------------------------------------------------------------------------
  // Minutes after midnight, from what people really type on a run sheet, or null if it isn't a clock time ("TBC", "after lunch").
  function parseClock(text) {
    const m = String(text || "").trim().toLowerCase().match(/^(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm)?$/);
    if (!m) return null;
    let hour = Number(m[1]);
    const minute = m[2] ? Number(m[2]) : 0;
    if (minute > 59) return null;
    if (m[3]) {
      if (hour < 1 || hour > 12) return null;
      hour = (hour % 12) + (m[3] === "pm" ? 12 : 0);
    } else if (!m[2]) {
      return null;   // a bare "11" is more likely a number than a time
    }
    return hour > 23 ? null : hour * 60 + minute;
  }

  // Moments in run-sheet order, each with its time (the first one given) and shots.
  function momentsOf(items) {
    const out = [];
    const seen = new Map();
    for (const item of items) {
      let moment = seen.get(item.moment);
      if (!moment) {
        moment = { name: item.moment, time: "", minutes: null, items: [] };
        seen.set(item.moment, moment);
        out.push(moment);
      }
      if (!moment.time && item.time) {
        moment.time = item.time;
        moment.minutes = parseClock(item.time);
      }
      moment.items.push(item);
    }
    return out;
  }

  const localDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  // What to warn about right now. Only must-haves, only on the shoot day, and the phone's own clock is the venue's clock. Most urgent first, and at most three, so it stays readable.
  function alertsFor(items, ticks, now, shootDate, settings) {
    if (localDate(now) !== shootDate) return [];
    const soon = (settings && settings.soon_minutes) || 30, live = (settings && settings.now_minutes) || 15;
    const clock = now.getHours() * 60 + now.getMinutes();
    const urgent = [], passed = [];
    for (const moment of momentsOf(items)) {
      if (moment.minutes === null) continue;
      const left = moment.items.filter((i) => i.priority === "must" && !(ticks[i.id] && ticks[i.id].done));
      if (!left.length) continue;
      const until = moment.minutes - clock;
      const shots = left.length === 1 ? left[0].description : `${left.length} must-haves`;
      if (until > 0 && until <= soon) urgent.push({ level: "soon", moment: moment.name, until, left: left.length, text: `${moment.name} in ${until} min. Still to get: ${shots}.` });
      else if (until <= 0 && until > -live) urgent.push({ level: "now", moment: moment.name, until, left: left.length, text: `${moment.name} is on now. Still to get: ${shots}.` });
      else if (until <= -live) passed.push({ moment: moment.name, left: left.length });
    }
    urgent.sort((a, b) => a.until - b.until);
    const out = urgent.slice(0, 2);
    if (passed.length) {
      const count = passed.reduce((n, p) => n + p.left, 0);
      const names = passed.length === 1 ? `${passed[0].moment} has` : `${passed.length} moments have`;
      out.push({ level: "passed", left: count, text: `${names} passed with ${count} must-have${count === 1 ? "" : "s"} not ticked.` });
    }
    return out;
  }

  // ---- a spoken phrase ----------------------------------------------------------------------------------------------------------------------------------------
  const STOP = new Set("a an and the of at on in to for from with we i ive im just got get getting done shot shots shooting take took it its is was are that this these those some all our my me them there here have has had bit now also then both clip clips footage by very really please yes ok okay".split(" "));
  const SIZES = { wide: "wide", establishing: "wide", establish: "wide", master: "wide", close: "close", closeup: "close", tight: "close", cu: "close", detail: "detail", macro: "detail", insert: "detail", medium: "medium", mid: "medium" };
  const SIZE_KEYS = { extreme_wide: "wide", wide: "wide", medium: "medium", close: "close", detail: "detail" };

  function stem(word) {
    if (word.length > 5 && word.endsWith("ing")) word = word.slice(0, -3);
    else if (word.length > 4 && word.endsWith("ed")) word = word.slice(0, -2);
    else if (word.length > 3 && word.endsWith("s") && !word.endsWith("ss")) word = word.slice(0, -1);
    if (word.length > 3 && word.endsWith("e")) word = word.slice(0, -1);   // so "waving" and "waves" land on the same word
    return word;
  }

  // Words that count, as stems, plus any size mentioned as "#wide", "#close" and so on.
  function tokens(text) {
    const clean = String(text || "").toLowerCase().replace(/[’']/g, "").replace(/\bpop[\s-]+up\b/g, "popup").replace(/\bclose[\s-]+up\b/g, "closeup").replace(/\bb[\s-]+roll\b/g, "broll").replace(/\bd[\s.]*j\b/g, "dj").replace(/[^a-z0-9]+/g, " ");
    const words = new Set(), sizes = new Set();
    for (const raw of clean.split(" ")) {
      if (!raw || STOP.has(raw)) continue;
      if (SIZES[raw]) sizes.add(SIZES[raw]);
      else words.add(stem(raw));
    }
    return { words, sizes };
  }

  // Speech-to-text often gets a word slightly wrong ("burkenstock"), so a long word is allowed one slip.
  function near(a, b) {
    if (a === b) return true;
    if (Math.min(a.length, b.length) < 5 || Math.abs(a.length - b.length) > 1) return false;
    let i = 0, j = 0, slips = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { i += 1; j += 1; continue; }
      slips += 1;
      if (slips > 1) return false;
      if (a.length > b.length) i += 1;
      else if (b.length > a.length) j += 1;
      else { i += 1; j += 1; }
    }
    return slips + (a.length - i) + (b.length - j) <= 1;
  }

  // Which shots a phrase is about, best first. It only suggests: a person always confirms before anything is ticked. "strong" ones start selected.
  function matchPhrase(text, items) {
    const said = tokens(text);
    if (!said.words.size) return [];
    const parsed = items.map((item) => {
      const t = tokens(item.description);
      if (SIZE_KEYS[item.size]) t.sizes.add(SIZE_KEYS[item.size]);
      return { item, ...t };
    });
    const count = new Map();
    for (const p of parsed) for (const w of p.words) count.set(w, (count.get(w) || 0) + 1);
    const weight = (w) => Math.log(1 + parsed.length / (count.get(w) || 1));
    const spoken = [...said.words].reduce((n, w) => n + (count.has(w) ? weight(w) : Math.log(1 + parsed.length)), 0);
    const scored = [];
    for (const p of parsed) {
      let matched = 0, hits = 0;
      for (const w of p.words) {
        if ([...said.words].some((s) => near(s, w))) { matched += weight(w); hits += 1; }
      }
      if (!hits) continue;
      const whole = [...p.words].reduce((n, w) => n + weight(w), 0);
      const coverage = matched / whole, precision = Math.min(1, matched / (spoken || 1));
      let score = 0.6 * coverage + 0.4 * precision;
      if (said.sizes.size && p.sizes.size) score *= [...p.sizes].some((s) => said.sizes.has(s)) ? 1.1 : 0.55;
      scored.push({ item: p.item, score: Math.min(1, score), hits });
    }
    scored.sort((a, b) => b.score - a.score);
    if (!scored.length) return [];
    const top = scored[0].score;
    return scored.filter((s) => s.score >= 0.25 && s.score >= top * 0.5).slice(0, 5).map((s) => ({ item: s.item, score: s.score, strong: s.score >= 0.42 && s.score >= top * 0.8 }));
  }

  Object.assign(exports, { foldTicks, progress, parseClock, momentsOf, alertsFor, matchPhrase, localDate });
})(typeof module !== "undefined" && module.exports ? module.exports : (window.OnSetLogic = {}));
