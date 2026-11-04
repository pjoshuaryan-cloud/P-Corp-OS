// The on-set page's logic (backend/app/static/on_set_logic.js): where a shot stands, the run-sheet warnings, and matching a spoken phrase. No screen, no network. Run:
//   cd premiere-plugin/e2e && node plugin_on_set_test.js
const L = require("../../backend/app/static/on_set_logic.js");
let fails = 0;
function check(name, cond, detail) {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${name}${!cond && detail !== undefined ? `   [${JSON.stringify(detail)}]` : ""}`);
  if (!cond) fails += 1;
}

// ---- where a shot stands: the same answer on every phone, whatever order ticks arrive in
const t = (id, item, done, by, at, note) => ({ id, item, done, by, at, note: note || "" });
let f = L.foldTicks([t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z")]);
check("a tick counts", f.i1.done && f.i1.by === "A");
f = L.foldTicks([t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z"), t(2, "i1", false, "B", "2026-11-06T09:05:00.000Z")]);
check("the later of two actions wins", f.i1.done === false && f.i1.by === "B");
f = L.foldTicks([t(5, "i1", false, "B", "2026-11-06T09:05:00.000Z"), t(6, "i1", true, "A", "2026-11-06T09:00:00.000Z")]);
check("a tick that waited for signal doesn't override something done after it", f.i1.done === false, f);
const a = L.foldTicks([t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z"), t(2, "i1", false, "B", "2026-11-06T09:00:00.000Z")]);
const b = L.foldTicks([t(2, "i1", false, "B", "2026-11-06T09:00:00.000Z"), t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z")]);
check("the same moment lands the same way on every phone", JSON.stringify(a) === JSON.stringify(b) && a.i1.done === false);
f = L.foldTicks([t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z", "wide only"), { item: "i1", done: true, by: "A", at: "2026-11-06T09:01:00.000Z", note: "" }]);
check("a tick still waiting for signal shows, and keeps the note", f.i1.done && f.i1.note === "wide only", f);
f = L.foldTicks([t(1, "i1", true, "A", "2026-11-06T09:00:00.000Z", "wide only"), t(2, "i1", false, "A", "2026-11-06T09:01:00.000Z")]);
check("unticking clears the note", f.i1.note === "", f);

const list = [
  { id: "i1", moment: "ARRIVALS", time: "10:00", description: "Whole pop-up with Birkenstock sign visible", size: "wide", priority: "must", owner: "A-cam" },
  { id: "i2", moment: "ARRIVALS", time: "10:00", description: "Queue of guests at the kiosk", size: "any", priority: "must", owner: "" },
  { id: "i3", moment: "ARRIVALS", time: "10:00", description: "Rosebank mall building seen from outside", size: "wide", priority: "should", owner: "" },
  { id: "i4", moment: "CUSTOMISATION", time: "11:00", description: "Laser engraving a leather keyring", size: "close", priority: "must", owner: "B-cam" },
  { id: "i5", moment: "CUSTOMISATION", time: "11:00", description: "Laser engraving a clog", size: "close", priority: "must", owner: "B-cam" },
  { id: "i6", moment: "OPENING", time: "11:30", description: "Mayor giving a speech at a microphone on stage", size: "any", priority: "must", owner: "" },
  { id: "i7", moment: "TALENT", time: "12:00", description: "Talent showing the clog to camera", size: "any", priority: "must", owner: "" },
  { id: "i8", moment: "TALENT", time: "12:00", description: "Talent writing on the graffiti wall", size: "any", priority: "should", owner: "" },
  { id: "i9", moment: "GAMES AND FOOD", time: "", description: "Guests throwing bean bags at the cornhole game", size: "any", priority: "should", owner: "" },
  { id: "i10", moment: "GAMES AND FOOD", time: "", description: "Matis Paris cake trays with branding visible", size: "any", priority: "should", owner: "" },
  { id: "i11", moment: "GAMES AND FOOD", time: "", description: "Barista pouring coffee at branded coffee cart", size: "any", priority: "must", owner: "" },
  { id: "i12", moment: "MUSIC", time: "15:00", description: "DJ at the branded booth", size: "any", priority: "must", owner: "" },
  { id: "i13", moment: "MUSIC", time: "15:00", description: "Whole staff team posed together for group photo", size: "any", priority: "must", owner: "" },
  { id: "i14", moment: "MUSIC", time: "15:00", description: "Drone shot looking down on the pop-up from above", size: "extreme_wide", priority: "should", owner: "" },
];
const p = L.progress(list, { i1: { done: true }, i3: { done: true }, i2: { done: false } });
check("progress counts done shots and must-haves left", p.done === 2 && p.total === 14 && p.mustLeft === 8, p);

// ---- run-sheet times, as people really type them
for (const [text, want] of [["11:30", 690], ["09:05", 545], ["9.30", 570], ["14h30", 870], ["10am", 600], ["10 am", 600], ["2:30 pm", 870], ["12pm", 720], ["12am", 0], ["TBC", null], ["after lunch", null], ["", null], ["25:00", null], ["11", null], ["13pm", null], ["11:75", null]]) {
  check(`"${text}" reads as ${want}`, L.parseClock(text) === want, L.parseClock(text));
}
const m = L.momentsOf(list);
check("moments stay in run-sheet order, with their times", m.map((x) => x.name).join() === "ARRIVALS,CUSTOMISATION,OPENING,TALENT,GAMES AND FOOD,MUSIC" && m[2].minutes === 690 && m[4].minutes === null, m.map((x) => x.minutes));

// ---- the warnings
const day = "2026-11-06";
const at = (hh, mm, d = 6) => new Date(2026, 10, d, hh, mm);
const settings = { soon_minutes: 30, now_minutes: 15 };
const allBefore = (ids) => Object.fromEntries(ids.map((i) => [i, { done: true }]));
let w = L.alertsFor(list, {}, at(11, 18), day, settings);
check("twelve minutes out, it names the one must-have left", w[0].level === "soon" && w[0].moment === "OPENING" && w[0].until === 12 && w[0].text.includes("Mayor giving a speech"), w);
w = L.alertsFor(list, {}, at(10, 40), day, settings);
check("with several left it gives the count", w.some((a) => a.moment === "CUSTOMISATION" && a.text.includes("2 must-haves")), w);
w = L.alertsFor(list, {}, at(11, 35), day, settings);
check("during a moment it says it's on now", w.some((a) => a.level === "now" && a.moment === "OPENING"), w);
w = L.alertsFor(list, allBefore(["i6"]), at(11, 18), day, settings);
check("a moment with its must-haves ticked says nothing", !w.some((a) => a.moment === "OPENING"), w);
w = L.alertsFor(list, {}, at(16, 0), day, settings);
check("afterwards it rolls up what was missed", w.length === 1 && w[0].level === "passed" && w[0].left === 8 && w[0].text.startsWith("5 moments have passed"), w);
w = L.alertsFor(list, L.foldTicks([]), at(10, 20), day, settings);
check("one moment past reads properly", w.some((a) => a.level === "passed" && a.text.startsWith("ARRIVALS has passed with 2 must-haves")), w);
check("a should-have alone never warns", !L.alertsFor([{ id: "x", moment: "M", time: "10:00", description: "d", priority: "should" }], {}, at(9, 50), day, settings).length);
check("a moment with no clock time never warns", !L.alertsFor([{ id: "x", moment: "M", time: "TBC", description: "d", priority: "must" }], {}, at(9, 50), day, settings).length);
check("it says nothing on any other day", !L.alertsFor(list, {}, at(11, 18, 5), day, settings).length);
check("never more than three at once", L.alertsFor(list, {}, at(11, 25), day, settings).length <= 3);

// ---- a spoken phrase: expected shots, fixed before tuning. Only ever a suggestion, and a person confirms.
const logo = [
  { id: "a", description: "Logo wall, wide", size: "wide" }, { id: "b", description: "Logo wall, tight", size: "close" }, { id: "c", description: "Logo on the product box", size: "close" },
  { id: "d", description: "Crowd wide at the stage", size: "wide" }, { id: "e", description: "Speaker at the podium", size: "medium" },
];
let got = L.matchPhrase("logo wall, wide and tight", logo);
check("the spec's own example ticks both logo-wall shots", got.filter((g) => g.strong).map((g) => g.item.id).sort().join() === "a,b", got.map((g) => [g.item.id, g.score.toFixed(2), g.strong]));
got = L.matchPhrase("logo wall wide", logo);
check("saying wide puts the wide one first", got[0].item.id === "a" && !got.filter((g) => g.strong).some((g) => g.item.id === "b"), got.map((g) => [g.item.id, g.score.toFixed(2), g.strong]));

const PHRASES = [
  ["got the whole pop up with the sign", "i1"], ["pop-up wide, sign in frame", "i1"], ["queue at the kiosk", "i2"], ["guests in the queue", "i2"],
  ["mall building from outside", "i3"], ["rosebank exterior", "i3"], ["leather keyring laser", "i4"], ["engraving the keyring close up", "i4"],
  ["laser on the clog", "i5"], ["got the clog engraving", "i5"], ["the mayor's speech", "i6"], ["mayor on stage", "i6"], ["talent showing the clog", "i7"],
  ["graffiti wall", "i8"], ["talent writing on the wall", "i8"], ["bean bags", "i9"], ["cornhole game, people throwing", "i9"], ["matis cake", "i10"], ["cake trays", "i10"],
  ["barista", "i11"], ["coffee cart", "i11"], ["DJ", "i12"], ["d j at the booth", "i12"], ["group photo of the staff", "i13"], ["drone from above", "i14"], ["burkenstock pop up", "i1"],
];
let topRight = 0, wrongStrong = 0;
for (const [phrase, want] of PHRASES) {
  const found = L.matchPhrase(phrase, list);
  const right = found[0] && found[0].item.id === want;
  if (right) topRight += 1;
  const bad = found.filter((x) => x.strong && x.item.id !== want).map((x) => x.item.id);
  if (bad.length) wrongStrong += 1;
  check(`"${phrase}" suggests ${want} first`, right, found.map((x) => [x.item.id, x.score.toFixed(2), x.strong]));
}
console.log(`  matched ${topRight} of ${PHRASES.length}, with a wrong shot pre-selected on ${wrongStrong}`);
check("at least 9 in 10 phrases put the right shot first", topRight >= PHRASES.length * 0.9, topRight);
check("hardly any phrase pre-selects a wrong shot", wrongStrong <= 2, wrongStrong);
check("words not about anything on the list suggest nothing", !L.matchPhrase("lunch break for the crew", list).length, L.matchPhrase("lunch break for the crew", list).map((x) => x.item.id));
check("empty words suggest nothing", !L.matchPhrase("got it, all done", list).length);
check("a size alone isn't enough to suggest a shot", !L.matchPhrase("wide", list).length);

// ---- the JD store opening list, with what someone might really say on the floor. Phrases fixed before looking at the scores.
const config = JSON.parse(require("fs").readFileSync(require("path").join(__dirname, "../../backend/app/shoot_log_config.json"), "utf8"));
const jd = config.coverage.starter_templates[0].items.map((it, n) => ({ id: `s${n}`, description: it.description, size: it.shot_size || "any", priority: it.priority }));
const shot = (words) => jd.find((j) => j.description.startsWith(words)).id;
const JD_PHRASES = [
  ["got the JD logo and the mall sign", "JD logo"], ["store front wide", "Full store front"], ["the welcome banner", "Welcome banner"], ["crowd at the barrier", "Crowd at the entrance"],
  ["confetti", "Confetti"], ["walking in, interior reveal", "First walk in"], ["certificate handover", "Certificate"], ["staff group photo with the logos", "Staff group pose"], ["staff cheering", "Staff cheering"],
  ["inside the store wide", "Store interior"], ["crep protect display", "Partner brand"], ["someone grabbing a shoe off the wall", "Customer grabbing"], ["guy holding the shoe to camera", "Customer holding"],
  ["customer trying shoes on", "Customer trying"], ["lifting the bag", "Customer lifting"], ["DJ hands up", "DJ at the booth"], ["DJ headphones", "DJ detail"], ["the dancers", "Dancers"], ["prize wheel", "Prize wheel"], ["people waving at camera", "Smiles"],
];
let jdRight = 0, jdWrong = 0;
for (const [phrase, want] of JD_PHRASES) {
  const found = L.matchPhrase(phrase, jd);
  const right = found[0] && found[0].item.id === shot(want);
  if (right) jdRight += 1;
  if (found.some((x) => x.strong && x.item.id !== shot(want))) jdWrong += 1;
  console.log(`  ${right ? "  ok" : "MISS"}  "${phrase}" -> ${found.slice(0, 2).map((x) => `${x.item.description.slice(0, 26)} ${x.score.toFixed(2)}${x.strong ? "*" : ""}`).join(" | ") || "nothing"}`);
}
console.log(`  JD list: right shot first on ${jdRight} of ${JD_PHRASES.length}, a wrong shot pre-selected on ${jdWrong}`);
check("on the JD list, at least 8 in 10 phrases put the right shot first", jdRight >= JD_PHRASES.length * 0.8, jdRight);

console.log(fails ? `\n${fails} FAILED` : "\nALL PASSED");
process.exit(fails ? 1 : 0);
