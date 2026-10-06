// Builds the FusionMap pitch deck (presentation/FusionMap_Pitch.pptx).
//
//   cd presentation && npm install && node build_deck.js && python animate.py
//
// Every number on the slides comes from docs/benchmark.json or the showcase case report
// (seed 2026); market figures are the team's research and are labelled as such.
// Shapes that animate carry an objectName; build/animations.json tells animate.py which
// entrance effect, delay and transition each slide gets. Names starting with "!!" are
// matched across slides by PowerPoint's Morph transition.

"use strict";
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const HERE = __dirname;
const ROOT = path.resolve(HERE, "..");
const asset = (f) => path.join(HERE, "assets", f);
const icon = (f) => path.join(HERE, "assets", "icons", `${f}.png`);
const shot = (f) => path.join(ROOT, "docs", "screenshots", f);
const OUT = path.join(HERE, "FusionMap_Pitch.pptx");
const BUILD = path.join(HERE, "build");

const THEME = {
  name: "FusionMap",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0A0E16", // ink: slide background, text on bright fills
    lt1: "F3F6FA", // primary text
    dk2: "131B27", // card panels
    lt2: "93A0B4", // secondary text
    accent1: "FF7A3D", // PET / metabolism
    accent2: "7DD3FC", // MRI / anatomy
    accent3: "3DDC6A", // verified, inside margin
    accent4: "FFB547", // amber
    accent5: "FF6B6B", // error, cost
    accent6: "263244", // hairlines
    hlink: "7DD3FC",
    folHlink: "B79CFF",
  },
};
const HEX = THEME.colors;
const DIM_BAR = "4A5A70"; // de-emphasised chart bars (chart colours are hex-only)

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "FusionMap: AI PET/MRI fusion";
pres.subject = "Hackathon pitch deck";
pres.author = "Team MeatRiders";
pres.company = "Team MeatRiders";

const C = pres.SchemeColor;
const INK = C.text1;
const TXT = C.background1;
const MUTED = C.background2;
const PANEL = C.text2;
const LINE = C.accent6;
const PET = C.accent1;
const MRI = C.accent2;
const OK = C.accent3;
const AMBER = C.accent4;
const BAD = C.accent5;
const S = pres.shapes;

// ---------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: "FM_TITLE",
  background: { path: asset("bg_title.png") },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.45, w: 7.0, h: 1.3, fontSize: 66, bold: true, color: TXT, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.8, w: 6.6, h: 1.05, fontSize: 22, color: MUTED, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "FM_STATEMENT",
  background: { path: asset("bg_title.png") },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 0.55, w: 11.7, h: 0.4, fontSize: 13, bold: true, color: PET, charSpacing: 3, align: "left", valign: "middle", margin: 0 }, text: "" } },
  ],
});

pres.defineSlideMaster({
  title: "FM_CONTENT",
  background: { path: asset("bg_content.png") },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.42, w: 8.6, h: 0.34, fontSize: 13, bold: true, color: PET, charSpacing: 3, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.78, w: 12.13, h: 0.8, fontSize: 32, bold: true, color: TXT, align: "left", valign: "top", margin: 0 }, text: "" } },
    { image: { path: asset("logo.png"), x: 0.56, y: 6.9, w: 0.34, h: 0.34 } },
    { text: { text: "FusionMap  ·  Team MeatRiders  ·  research prototype, not for clinical use", options: { x: 0.95, y: 6.92, w: 8, h: 0.3, fontSize: 10, color: MUTED, margin: 0, valign: "middle" } } },
  ],
  slideNumber: { x: 12.13, y: 6.92, w: 0.6, h: 0.3, fontSize: 10, color: MUTED, align: "right" },
});

// ---------------------------------------------------------------- animation spec
const spec = { theme: THEME, slides: [] };
let cur = null;

function add(master, section, transition = "fade") {
  if (section) pres.addSection({ title: section });
  const slide = pres.addSlide({ masterName: master, sectionTitle: currentSection(section) });
  cur = { transition, anim: [], ph: [], names: new Set() };
  spec.slides.push(cur);
  return slide;
}
let lastSection = null;
function currentSection(s) {
  if (s) lastSection = s;
  return lastSection;
}

// queue an entrance effect for a named shape: fade | float | floatL | zoom | wipeL | wipeU
function anim(name, effect = "fade", delay = 0, dur = 600) {
  if (!cur.names.has(name)) throw new Error(`anim(): no shape named ${name}`);
  cur.anim.push({ name, effect, delay, dur });
}
function named(name) {
  if (cur.names.has(name)) throw new Error(`duplicate objectName ${name}`);
  cur.names.add(name);
  return name;
}

// ---------------------------------------------------------------- drawing helpers
// keep numbers and their units on one line ("6 mm", "26 s", "100 %")
const nb = (t) => (typeof t === "string" ? t.replace(/(\d) (mm|s|dB|M|k|%|lakh)(?![A-Za-z])/g, "$1\u00A0$2") : t);
const R = (text, options = {}) => ({ text: nb(text), options });

// fill a layout placeholder; pptxgenjs ignores objectName on placeholders, so animate.py
// renames them (in order) from spec.slides[i].ph
function P(slide, placeholder, name, content) {
  slide.addText(nb(content), { placeholder });
  cur.ph.push(named(name));
}

function text(slide, name, content, o) {
  slide.addText(nb(content), { isTextBox: true, margin: 0, valign: "top", objectName: named(name), ...o });
}

function card(slide, name, x, y, w, h, o = {}) {
  slide.addShape(S.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12,
    fill: { color: o.fill || PANEL, transparency: o.transparency || 0 },
    line: { color: o.line || LINE, width: o.lineW || 0.75 },
    objectName: named(name),
  });
}

function ring(slide, name, ico, x, y, d, color) {
  slide.addShape(S.OVAL, { x, y, w: d, h: d, fill: { color: PANEL }, line: { color, width: 1.25 }, objectName: named(`${name}_ring`) });
  slide.addImage({ path: icon(ico), x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52, altText: `${ico} icon`, objectName: named(`${name}_icon`) });
}
const ringAnim = (name, effect, delay, dur) => { anim(`${name}_ring`, effect, delay, dur); anim(`${name}_icon`, effect, delay, dur); };

function pill(slide, name, label, x, y, w, color, o = {}) {
  slide.addText(nb(label), {
    shape: S.ROUNDED_RECTANGLE, rectRadius: 0.16, x, y, w, h: o.h || 0.34,
    fill: { color, transparency: o.solid ? 0 : 80 }, line: { color, width: 0.75 },
    fontSize: o.fontSize || 12, bold: true, color: o.solid ? INK : color, align: "center", valign: "middle",
    margin: 0, charSpacing: 1, objectName: named(name),
  });
}

// framed picture (GIFs keep animating inside PowerPoint)
function framed(slide, name, file, x, y, w, h, alt, pad = 0.1) {
  card(slide, `${name}_frame`, x - pad, y - pad, w + 2 * pad, h + 2 * pad, { fill: INK, line: LINE });
  slide.addImage({ path: file, x, y, w, h, altText: alt, objectName: named(name) });
}
const framedAnim = (name, effect, delay, dur) => { anim(`${name}_frame`, effect, delay, dur); anim(name, effect, delay, dur); };

function arrow(slide, name, x, y, w = 0.26, h = 0.24, color = MUTED) {
  slide.addShape(S.RIGHT_ARROW, { x, y, w, h, fill: { color }, line: { color, width: 0 }, objectName: named(name) });
}

function line(slide, name, x1, y1, x2, y2, color = MUTED, o = {}) {
  slide.addShape(S.LINE, { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width: o.width || 1.25, dashType: o.dash || "solid" }, objectName: named(name) });
}

// icon + bold lead + muted sentence
function iconRow(slide, name, ico, color, lead, rest, x, y, w, size = 15) {
  ring(slide, name, ico, x, y, 0.55, color);
  text(slide, `${name}_txt`, [R(lead, { bold: true, color: TXT }), R(rest, { color: MUTED })], { x: x + 0.75, y: y - 0.02, w: w - 0.75, h: 0.62, fontSize: size, valign: "middle" });
}
const iconRowAnim = (name, delay) => { ringAnim(name, "zoom", delay, 500); anim(`${name}_txt`, "floatL", delay + 100, 600); };

const STEPS = [
  { n: "1", label: "Register", color: MRI },
  { n: "2", label: "Sharpen", color: PET },
  { n: "3", label: "Fuse & export", color: OK },
];

// pipeline tracker in the top-right corner; Morph flies it in from the slide-6 cards
function tracker(slide, active) {
  const xs = [10.2, 11.25, 12.3];
  const cy = 0.6;
  line(slide, "!!track", xs[0], cy, xs[2], cy, LINE, { width: 1.5 });
  STEPS.forEach((st, i) => {
    const on = i === active;
    const d = on ? 0.5 : 0.34;
    slide.addText(st.n, {
      shape: S.OVAL, x: xs[i] - d / 2, y: cy - d / 2, w: d, h: d,
      fill: { color: on ? st.color : PANEL }, line: { color: on ? st.color : MUTED, width: 1 },
      fontSize: on ? 16 : 11, bold: true, color: on ? INK : MUTED, align: "center", valign: "middle", margin: 0,
      objectName: named(`!!dot${st.n}`),
    });
    text(slide, `!!lab${st.n}`, st.label, { x: xs[i] - 0.55, y: 0.9, w: 1.1, h: 0.26, fontSize: 11, bold: on, color: on ? st.color : MUTED, align: "center" });
  });
}

// ================================================================= 1 · title
let s = add("FM_TITLE", "Opening");
s.addImage({ path: asset("logo.png"), x: 0.62, y: 0.75, w: 1.5, h: 1.5, altText: "FusionMap logo", objectName: named("logo") });
text(s, "kicker", "AI  PET / MRI  FUSION", { x: 0.8, y: 2.08, w: 6.5, h: 0.34, fontSize: 14, bold: true, color: MRI, charSpacing: 4, valign: "middle" });
P(s, "title", "title", "FusionMap");
P(s, "body", "subtitle", "PET-MRI precision from the scanners hospitals already own");
text(s, "team", [R("Team MeatRiders", { bold: true, fontSize: 18, color: TXT, breakLine: true }), R("Parth Deshmukh  ·  Atharva Jadhav  ·  Samuel Cardoza  ·  Ralston Crasta", { fontSize: 15, color: MUTED })], { x: 0.8, y: 5.35, w: 6.8, h: 0.8 });
framed(s, "sweep", asset("sweep.gif"), 8.2, 1.17, 3.6, 4.5, "Animated sweep through a fused PET/MRI brain study", 0.12);
text(s, "sweep_cap", "Real FusionMap output: fused PET/MRI, slice by slice", { x: 7.9, y: 5.98, w: 4.2, h: 0.3, fontSize: 11, color: MUTED, align: "center" });
framedAnim("sweep", "fade", 0, 900);
anim("logo", "zoom", 250, 700);
anim("kicker", "fade", 550, 500);
anim("title", "float", 700, 800);
anim("subtitle", "float", 950, 800);
anim("team", "fade", 1350, 700);
anim("sweep_cap", "fade", 1500, 600);
s.addNotes(`[0:00-0:15]  OPENING
Hi, we're Team MeatRiders: Parth, Atharva, Samuel and Ralston, and this is FusionMap.
In one line: FusionMap gives hospitals PET-MRI-level precision using the PET and MRI scanners they already own, with software alone.
(The brain on the right is real FusionMap output, scrolling through a fused study.)

HOW TO PRESENT: start the slide show (F5). Every slide animates by itself, so one click = next slide. The animated images play automatically in slide-show mode.`);

// ================================================================= 2 · hook
s = add("FM_STATEMENT", null, "fadeBlack");
P(s, "title", "kick", "THE PROBLEM IN ONE NUMBER");
text(s, "big", "13 mm", { x: 0.75, y: 1.05, w: 7.2, h: 2.4, fontSize: 150, bold: true, color: PET, valign: "bottom" });
text(s, "off", "off target", { x: 0.8, y: 3.5, w: 7.0, h: 0.8, fontSize: 44, bold: true, color: TXT });
text(s, "para", "That's how far the tumour glow on this patient's PET lands from the real tumour when it is simply overlaid on an MRI from a different scanner. Plan radiotherapy on that, and the beam treats healthy brain while the tumour escapes.", { x: 0.8, y: 4.5, w: 6.7, h: 1.4, fontSize: 18, color: MUTED });
text(s, "note", "Measured, not estimated: across 12 test patients the naive overlay is off by 11.8 mm on average, up to 15 mm (95th percentile).", { x: 0.8, y: 6.05, w: 6.7, h: 0.6, fontSize: 12, italic: true, color: MUTED });
framed(s, "naive", asset("naive_still.png"), 8.45, 0.9, 3.96, 5.63, "Naive PET over MRI overlay: tumour glow 13.2 mm away from the true tumour outline");
framedAnim("naive", "fade", 0, 700);
anim("kick", "fade", 200, 500);
anim("big", "zoom", 400, 700);
anim("off", "float", 1000, 700);
anim("para", "fade", 1400, 800);
anim("note", "fade", 1800, 600);
s.addNotes(`[0:15-0:40]  THE HOOK
Thirteen millimetres.
That is how far the tumour glow on a PET scan sits from the real tumour in this patient, when you simply lay it over an MRI from a different scanner. That's exactly what hospitals do today.
Across our 12 test patients the average is 11.8 mm and it reaches 15 mm.
In radiotherapy, a plan that is 13 mm off treats healthy brain and lets the tumour escape.

(Pause for a second and let the number land.)`);

// ================================================================= 3 · two scans
s = add("FM_CONTENT", "Problem");
P(s, "kicker", "kick", "WHY FUSION");
P(s, "title", "ttl", "MRI sees two lesions. PET knows which one is alive");
s.addImage({ path: asset("eq_mri.png"), x: 1.9, y: 1.85, w: 3.0, h: 3.75, altText: "MRI slice with two ring-shaped lesions", objectName: named("!!mri") });
s.addImage({ path: asset("eq_pet.png"), x: 8.43, y: 1.85, w: 3.0, h: 3.75, altText: "PET slice: only the lower lesion takes up tracer", objectName: named("!!pet") });
pill(s, "!!mripill", "MRI", 2.02, 1.97, 0.75, MRI, { solid: true });
pill(s, "!!petpill", "PET", 8.55, 1.97, 0.75, PET, { solid: true });
// the two lesions on the MRI (pixel centres 101,180 and 134,326 of a 354x442 slice)
s.addShape(S.OVAL, { x: 2.756 - 0.3, y: 3.375 - 0.3, w: 0.6, h: 0.6, line: { color: AMBER, width: 1.5, dashType: "dash" }, objectName: named("q1") });
s.addShape(S.OVAL, { x: 3.036 - 0.3, y: 4.613 - 0.3, w: 0.6, h: 0.6, line: { color: AMBER, width: 1.5, dashType: "dash" }, objectName: named("q2") });
text(s, "plus", "+", { x: 6.17, y: 3.05, w: 1.0, h: 1.2, fontSize: 80, bold: true, color: MUTED, align: "center", valign: "middle" });
text(s, "mri_txt", [R("Shows WHERE", { bold: true, fontSize: 20, color: MRI, breakLine: true }), R("1 mm anatomy and soft tissue. But a dead lesion and a living one can look the same.", { fontSize: 14, color: MUTED })], { x: 1.45, y: 5.75, w: 3.9, h: 1.0 });
text(s, "pet_txt", [R("Shows WHAT'S ALIVE", { bold: true, fontSize: 20, color: PET, breakLine: true }), R("Lights up tumour metabolism. But it is blurry (6 mm) and comes from another scanner.", { fontSize: 14, color: MUTED })], { x: 7.98, y: 5.75, w: 3.9, h: 1.0 });
anim("!!mri", "fade", 0, 700); anim("!!mripill", "fade", 0, 700);
anim("mri_txt", "float", 400, 700);
anim("q1", "zoom", 800, 500); anim("q2", "zoom", 950, 500);
anim("plus", "zoom", 1200, 500);
anim("!!pet", "fade", 1450, 700); anim("!!petpill", "fade", 1450, 700);
anim("pet_txt", "float", 1800, 700);
s.addNotes(`[0:40-1:00]  WHY BOTH SCANS
Why do doctors need both scans?
Look at the MRI on the left: two lesions, circled. On MRI they look alike.
The PET on the right shows which one is actually alive: only the lower one is glowing.
So MRI tells you WHERE, with millimetre anatomy. PET tells you WHAT is alive, but it's blurry and it comes from a different machine.`);

// ================================================================= 4 · fused (Morph)
s = add("FM_CONTENT", null, "morph");
P(s, "kicker", "kick", "WHY FUSION");
P(s, "title", "ttl", "Fused, they show exactly where the living tumour is");
const FX = 4.87, FY = 1.85, FW = 3.6, FH = 4.5;
s.addImage({ path: asset("eq_mri.png"), x: FX, y: FY, w: FW, h: FH, altText: "MRI slice", objectName: named("!!mri") });
s.addImage({ path: asset("eq_pet.png"), x: FX, y: FY, w: FW, h: FH, transparency: 45, altText: "PET slice", objectName: named("!!pet") });
s.addImage({ path: asset("eq_fused.png"), x: FX, y: FY, w: FW, h: FH, altText: "Fused PET/MRI slice", objectName: named("fused") });
pill(s, "!!mripill", "MRI", FX + 0.12, FY + 0.12, 0.75, MRI, { solid: true });
pill(s, "!!petpill", "PET", FX + 0.95, FY + 0.12, 0.75, PET, { solid: true });
// lesion centres on the 3.6 in wide image
const L1 = [FX + 101 * FW / 354, FY + 180 * FW / 354];
const L2 = [FX + 134 * FW / 354, FY + 326 * FW / 354];
s.addShape(S.OVAL, { x: L1[0] - 0.32, y: L1[1] - 0.32, w: 0.64, h: 0.64, line: { color: MUTED, width: 1.5, dashType: "dash" }, objectName: named("r1") });
s.addShape(S.OVAL, { x: L2[0] - 0.32, y: L2[1] - 0.32, w: 0.64, h: 0.64, line: { color: PET, width: 1.75 }, objectName: named("r2") });
line(s, "ln1", 4.25, L1[1], L1[0] - 0.32, L1[1], MUTED);
line(s, "ln2", 4.25, L2[1], L2[0] - 0.32, L2[1], PET);
text(s, "dead", [R("Dead tissue (radionecrosis)", { bold: true, fontSize: 17, color: TXT, breakLine: true }), R("MRI: looks like tumour. PET: cold, so it stays grey", { fontSize: 14, color: MUTED })], { x: 0.6, y: L1[1] - 0.45, w: 3.5, h: 0.9, valign: "middle" });
text(s, "alive", [R("Living tumour", { bold: true, fontSize: 17, color: PET, breakLine: true }), R("The PET glow sits exactly on its MRI lesion", { fontSize: 14, color: MUTED })], { x: 0.6, y: L2[1] - 0.45, w: 3.5, h: 0.9, valign: "middle" });
card(s, "catch", 8.95, 1.85, 3.78, 4.5);
text(s, "catch_k", "THE CATCH", { x: 9.25, y: 2.1, w: 3.2, h: 0.3, fontSize: 13, bold: true, color: BAD, charSpacing: 3 });
text(s, "catch_1", [R("$4–6 M", { bold: true, fontSize: 50, color: TXT, breakLine: true }), R("for one integrated PET-MRI scanner", { fontSize: 15, color: MUTED })], { x: 9.25, y: 2.5, w: 3.3, h: 1.5 });
text(s, "catch_2", [R("~10", { bold: true, fontSize: 50, color: TXT, breakLine: true }), R("of them in all of India", { fontSize: 15, color: MUTED })], { x: 9.25, y: 4.3, w: 3.3, h: 1.5 });
anim("fused", "fade", 0, 900);
anim("r1", "zoom", 700, 450); anim("ln1", "wipeL", 850, 450); anim("dead", "floatL", 1000, 600);
anim("r2", "zoom", 1250, 450); anim("ln2", "wipeL", 1400, 450); anim("alive", "floatL", 1550, 600);
anim("catch", "float", 2000, 700); anim("catch_k", "float", 2000, 700);
anim("catch_1", "float", 2150, 700); anim("catch_2", "float", 2400, 700);
s.addNotes(`[1:00-1:20]  FUSION
Fuse the two and you get the best of both.
The living tumour lights up exactly on its MRI lesion. And the upper lesion, dead tissue called radionecrosis, correctly stays grey.
That is what an integrated PET-MRI scanner gives you.
The catch: one of those costs 4 to 6 million dollars, and India has about ten of them.

(Transition: the two scans slide together with Morph. It needs PowerPoint 2019 / Microsoft 365; older versions simply fade.)`);

// ================================================================= 5 · the gap
s = add("FM_CONTENT");
P(s, "kicker", "kick", "THE GAP");
P(s, "title", "ttl", "The scanners are already there. The fusion isn't");
const GAP = [
  { ico: "hospital", ring: MRI, big: "700+", col: MRI, label: "cancer centres already own both a PET and an MRI scanner" },
  { ico: "users", ring: AMBER, big: "6–8 lakh", col: AMBER, label: "patients a year who could benefit from fused imaging" },
  { ico: "scanner", ring: BAD, big: "~10", col: BAD, label: "integrated PET-MRI scanners in the whole country" },
];
GAP.forEach((g, i) => {
  const x = 0.6 + i * 4.15;
  card(s, `g${i}`, x, 1.85, 3.83, 3.1);
  ring(s, `g${i}i`, g.ico, x + 0.35, 2.15, 0.8, g.ring);
  text(s, `g${i}n`, g.big, { x: x + 0.35, y: 3.1, w: 3.3, h: 0.9, fontSize: 54, bold: true, color: g.col, valign: "middle" });
  text(s, `g${i}l`, g.label, { x: x + 0.35, y: 4.05, w: 3.2, h: 0.7, fontSize: 15, color: MUTED });
  const d = i * 250;
  anim(`g${i}`, "float", d, 700); ringAnim(`g${i}i`, "float", d, 700);
  anim(`g${i}n`, "zoom", d + 300, 600); anim(`g${i}l`, "float", d + 150, 700);
});
card(s, "today", 0.6, 5.2, 12.13, 1.05);
ring(s, "todayi", "eye", 0.85, 5.43, 0.6, BAD);
text(s, "today_t", [R("Today: ", { bold: true, color: TXT }), R("the two scans sit on two screens and are compared by eye. Overlaid as-is, they miss by ", { color: MUTED }), R("11.8 mm", { bold: true, color: BAD }), R(" on average.", { color: MUTED })], { x: 1.65, y: 5.25, w: 10.85, h: 0.95, fontSize: 17, valign: "middle" });
text(s, "src", "Centre, scanner and patient counts: team market research. Overlay error: FusionMap benchmark, 12 test patients.", { x: 0.6, y: 6.4, w: 11, h: 0.3, fontSize: 10, italic: true, color: MUTED });
anim("today", "fade", 1100, 600); ringAnim("todayi", "fade", 1100, 600); anim("today_t", "fade", 1250, 700);
anim("src", "fade", 1600, 500);
s.addNotes(`[1:20-1:40]  THE OPPORTUNITY
Here's the opportunity.
More than 700 cancer centres in India already have a PET scanner and an MRI scanner. That's our team's market research.
The data already exists. What's missing is the fusion.
Today doctors put the two scans on two screens and compare them by eye. Overlaid as-is, they are off by almost 12 mm on average. We measured that.`);

// ================================================================= 6 · solution
s = add("FM_CONTENT", "Solution");
P(s, "kicker", "kick", "THE SOLUTION");
P(s, "title", "ttl", "FusionMap fuses them in three steps, in software");
const SOL = [
  { desc: "Line the scans up. Mutual-information alignment, with a VoxelMorph network built in for organs that deform.", chip: "error 11.8 → 0.86 mm" },
  { desc: "Restore what scanner blur hides. An MRI-guided Vision-Transformer U-Net sharpens the PET.", chip: "PSNR 26.4 → 36.6 dB" },
  { desc: "One colour-coded DICOM plus tumour contours, pushed straight into PACS and radiotherapy planning.", chip: "≈ 26 s per study · CPU" },
];
SOL.forEach((c, i) => {
  const x = 0.6 + i * 4.15;
  const st = STEPS[i];
  card(s, `c${i}`, x, 1.85, 3.83, 3.95);
  s.addText(st.n, { shape: S.OVAL, x: x + 0.35, y: 2.2, w: 0.8, h: 0.8, fill: { color: st.color }, line: { color: st.color, width: 1 }, fontSize: 26, bold: true, color: INK, align: "center", valign: "middle", margin: 0, objectName: named(`!!dot${st.n}`) });
  text(s, `!!lab${st.n}`, st.label, { x: x + 1.35, y: 2.2, w: 2.35, h: 0.8, fontSize: 26, bold: true, color: TXT, valign: "middle" });
  text(s, `c${i}d`, c.desc, { x: x + 0.35, y: 3.3, w: 3.15, h: 1.45, fontSize: 15, color: MUTED });
  pill(s, `c${i}p`, c.chip, x + 0.35, 4.95, 3.13, st.color, { h: 0.5, fontSize: 15 });
  const d = i * 600;
  anim(`c${i}`, "float", d, 700); anim(`!!dot${st.n}`, "zoom", d + 150, 550); anim(`!!lab${st.n}`, "floatL", d + 250, 600);
  anim(`c${i}d`, "fade", d + 350, 600); anim(`c${i}p`, "zoom", d + 450, 500);
  if (i < 2) {
    s.addShape(S.CHEVRON, { x: x + 3.88, y: 3.62, w: 0.22, h: 0.4, fill: { color: MUTED }, line: { color: MUTED, width: 0 }, objectName: named(`ch${i}`) });
    anim(`ch${i}`, "wipeL", d + 500, 400);
  }
});
text(s, "io", [R("DICOM in", { bold: true, color: TXT }), R(" from any PET and any MRI   →   ", { color: MUTED }), R("standard DICOM out", { bold: true, color: TXT }), R(" into the hospital. No new hardware.", { color: MUTED })], { x: 0.6, y: 6.05, w: 12.13, h: 0.45, fontSize: 16, valign: "middle" });
anim("io", "fade", 1900, 700);
s.addNotes(`[1:40-2:00]  THE SOLUTION
FusionMap closes that gap in three steps, all in software on the hospital's existing computer.
One: Register. Line the scans up.
Two: Sharpen. Recover the PET detail lost to blur.
Three: Fuse and export. One colour-coded DICOM, straight into the hospital systems.
Let me show you each one.

(The next three slides Morph: the numbered circles fly up into a progress tracker.)`);

// ================================================================= 7 · step 1 register
s = add("FM_CONTENT", null, "morph");
P(s, "kicker", "kick", [R("STEP 1  ·  REGISTER", { color: MRI })]);
P(s, "title", "ttl", "Fix the mismatch between scanners");
tracker(s, 0);
framed(s, "reg", asset("registration.gif"), 0.7, 1.95, 3.34, 4.75, "Animation: PET slides into alignment with the MRI while the tumour position error drops from 13.2 mm to 0.3 mm");
text(s, "hero", [R("11.8 mm", { bold: true, fontSize: 36, color: BAD }), R("   →   ", { fontSize: 32, color: MUTED }), R("0.86 mm", { bold: true, fontSize: 66, color: OK })], { x: 4.85, y: 1.8, w: 7.88, h: 1.2, valign: "bottom" });
text(s, "hero_cap", "average PET-to-MRI alignment error, 12 held-out test patients", { x: 4.85, y: 3.02, w: 7.88, h: 0.4, fontSize: 15, color: MUTED });
const REG = [
  { big: "13×", col: MRI, label: "smaller error than overlaying the scans as-is" },
  { big: "< 1 s", col: MRI, label: "to align a full study on an ordinary CPU" },
  { big: "12 / 12", col: OK, label: "patients with 95 % of the brain within 2 mm" },
];
REG.forEach((m, i) => {
  const x = 4.85 + i * 2.69;
  card(s, `m${i}`, x, 3.6, 2.5, 1.4);
  text(s, `m${i}t`, [R(m.big, { bold: true, fontSize: 30, color: m.col, breakLine: true }), R(m.label, { fontSize: 13, color: MUTED })], { x: x + 0.22, y: 3.7, w: 2.1, h: 1.2, valign: "middle" });
  anim(`m${i}`, "float", 900 + i * 200, 600); anim(`m${i}t`, "float", 900 + i * 200, 600);
});
iconRow(s, "row1", "target", MRI, "Mutual information ", "aligns scans whose contrasts look nothing alike: PET versus MRI.", 4.85, 5.25, 7.88);
iconRow(s, "row2", "microchip", MRI, "VoxelMorph AI is built in ", "for organs that deform, and switches on only when its own validation beats the classical method.", 4.85, 6.0, 7.88);
framedAnim("reg", "fade", 0, 700);
anim("hero", "zoom", 300, 700); anim("hero_cap", "fade", 650, 600);
iconRowAnim("row1", 1550); iconRowAnim("row2", 1800);
s.addNotes(`[2:00-2:25]  STEP 1: REGISTER
Watch the animation on the left. The PET starts where the scanner left it, then FusionMap aligns it, and the error counter drops from 13 mm to 0.3 mm for this tumour.
Across 12 held-out patients the average error goes from 11.8 mm to 0.86 mm. That's 13 times smaller, in under a second, on a normal CPU.
We use mutual information because PET and MRI look nothing alike, so you can't just match pixel brightness.
A VoxelMorph neural network is built in for organs that deform, like lung or prostate.`);

// ================================================================= 8 · step 2 sharpen
s = add("FM_CONTENT", null, "morph");
P(s, "kicker", "kick", [R("STEP 2  ·  SHARPEN", { color: PET })]);
P(s, "title", "ttl", "Recover the detail scanner blur hides");
tracker(s, 1);
framed(s, "sharp", asset("sharpening.gif"), 0.7, 1.95, 3.51, 4.75, "Animation: a swipe compares the blurry acquired PET with the AI-sharpened PET");
const SHP = [
  { big: "36.6 dB", label: "image fidelity (PSNR), up from 26.4 dB" },
  { big: "0.98", label: "structural similarity (SSIM), up from 0.65" },
  { big: "99 %", label: "of true tumour brightness recovered, up from 91 %" },
];
SHP.forEach((m, i) => {
  const x = 4.85 + i * 2.69;
  text(s, `k${i}`, [R(m.big, { bold: true, fontSize: 40, color: PET, breakLine: true }), R(m.label, { fontSize: 14, color: MUTED })], { x, y: 1.85, w: 2.5, h: 1.55 });
  anim(`k${i}`, "zoom", 300 + i * 200, 600);
});
text(s, "how", "HOW THE AI WORKS", { x: 4.85, y: 3.62, w: 4, h: 0.3, fontSize: 12, bold: true, color: MUTED, charSpacing: 2 });
const NET = [
  ["PET + MRI", "3 neighbouring slices"],
  ["CNN encoder", "local edges"],
  ["ViT attention", "global context"],
  ["CNN decoder", "full detail"],
  ["Sharp PET", "SUV preserved"],
];
NET.forEach(([a, b], i) => {
  const x = 4.85 + i * 1.645;
  const hot = i === 2 || i === 4;
  s.addText([R(a, { bold: true, fontSize: 14, color: TXT, breakLine: true }), R(b, { fontSize: 11, color: MUTED })], {
    shape: S.ROUNDED_RECTANGLE, rectRadius: 0.1, x, y: 4.0, w: 1.3, h: 0.95,
    fill: { color: i === 4 ? PET : PANEL, transparency: i === 4 ? 80 : 0 }, line: { color: hot ? PET : LINE, width: hot ? 1.5 : 0.75 },
    align: "center", valign: "middle", margin: 0, objectName: named(`n${i}`),
  });
  anim(`n${i}`, "wipeL", 1100 + i * 220, 450);
  if (i < 4) { arrow(s, `na${i}`, x + 1.345, 4.36); anim(`na${i}`, "wipeL", 1250 + i * 220, 300); }
});
text(s, "net_cap", "2.45 M parameters  ·  trained on 29 simulated volumes  ·  ~6 s per study on CPU (ONNX Runtime)", { x: 4.85, y: 5.03, w: 7.88, h: 0.3, fontSize: 11, color: MUTED });
iconRow(s, "row1", "brain", PET, "MRI-guided: ", "the anatomy tells the network where the true edges are.", 4.85, 5.45, 7.88);
iconRow(s, "row2", "shield", OK, "Never invents tumours: ", "dead tissue that MRI shows but PET doesn't stays cold.", 4.85, 6.12, 7.88);
framedAnim("sharp", "fade", 0, 700);
anim("how", "fade", 950, 500);
anim("net_cap", "fade", 2200, 500);
iconRowAnim("row1", 2350); iconRowAnim("row2", 2600);
s.addNotes(`[2:25-2:50]  STEP 2: SHARPEN
PET is blurry, so small tumours look dimmer than they really are, and that changes treatment decisions.
Our MRI-guided Vision-Transformer U-Net uses the MRI's sharp anatomy as a guide. The swipe on the left shows before and after.
Image fidelity goes from 26.4 to 36.6 dB, structural similarity from 0.65 to 0.98, and tumour brightness comes back to 99 % of the true value.
How it works: convolutions catch local edges, and the attention layer in the middle sees the whole slice at once.
It never invents tumours: dead tissue that shows on MRI but not on PET stays cold.`);

// ================================================================= 9 · step 3 fuse & export
s = add("FM_CONTENT", null, "morph");
P(s, "kicker", "kick", [R("STEP 3  ·  FUSE & EXPORT", { color: OK })]);
P(s, "title", "ttl", "One colour-coded study, straight into PACS");
tracker(s, 2);
framed(s, "sweep", asset("sweep.gif"), 0.7, 1.95, 3.52, 4.4, "Animated sweep through the fused PET/MRI study");
text(s, "colA", "WRITES STANDARD DICOM", { x: 4.85, y: 1.85, w: 3.7, h: 0.3, fontSize: 12, bold: true, color: MUTED, charSpacing: 2 });
const SERIES = [
  ["MR reference series", MRI],
  ["PET in SUV, quantitative", PET],
  ["AI-enhanced PET", AMBER],
  ["Colour fusion image", OK],
  ["RT-STRUCT tumour contours", BAD],
];
SERIES.forEach(([label, col], i) => {
  const y = 2.25 + i * 0.66;
  card(s, `se${i}`, 4.85, y, 3.7, 0.54, { lineW: 0.75 });
  text(s, `se${i}t`, [R("●   ", { color: col, fontSize: 14 }), R(label, { color: TXT, fontSize: 15 })], { x: 5.05, y, w: 3.4, h: 0.54, valign: "middle" });
  anim(`se${i}`, "wipeL", 400 + i * 150, 450); anim(`se${i}t`, "wipeL", 400 + i * 150, 450);
});
arrow(s, "big_arrow", 8.78, 3.5, 0.45, 0.5, OK);
text(s, "colB", "STRAIGHT INTO", { x: 9.45, y: 1.85, w: 3.28, h: 0.3, fontSize: 12, bold: true, color: MUTED, charSpacing: 2 });
const TARGETS = [
  ["server", "Hospital PACS", "DICOM C-STORE push"],
  ["target", "Radiotherapy planning", "imports the RT-STRUCT"],
  ["book", "Printable report", "for the tumour board"],
];
TARGETS.forEach(([ico, a, b], i) => {
  const y = 2.25 + i * 1.1;
  card(s, `tg${i}`, 9.45, y, 3.28, 0.94);
  ring(s, `tg${i}i`, ico, 9.65, y + 0.19, 0.56, OK);
  text(s, `tg${i}t`, [R(a, { bold: true, fontSize: 15, color: TXT, breakLine: true }), R(b, { fontSize: 12, color: MUTED })], { x: 10.37, y: y + 0.1, w: 2.3, h: 0.74, valign: "middle" });
  const d = 1450 + i * 200;
  anim(`tg${i}`, "float", d, 600); ringAnim(`tg${i}i`, "float", d, 600); anim(`tg${i}t`, "float", d, 600);
});
card(s, "ana", 4.85, 5.72, 7.88, 0.95);
text(s, "ana_t", [R("Automatic tumour analytics:  ", { bold: true, color: TXT }), R("SUVmax · SUVpeak · metabolic volume · TLG · tumour-to-background ratio. Every series shares one frame of reference, so any viewer lines them up.", { color: MUTED })], { x: 5.1, y: 5.77, w: 7.45, h: 0.85, fontSize: 14, valign: "middle" });
framedAnim("sweep", "fade", 0, 700);
anim("colA", "fade", 250, 500);
anim("big_arrow", "wipeL", 1200, 400);
anim("colB", "fade", 1300, 500);
anim("ana", "fade", 2150, 600); anim("ana_t", "fade", 2150, 600);
s.addNotes(`[2:50-3:10]  STEP 3: FUSE & EXPORT
FusionMap writes standard DICOM: the MRI reference, the quantitative PET in SUV units, the AI PET, the colour fusion, and the tumour contours as an RT-STRUCT.
It pushes them straight into the hospital PACS, and radiotherapy planning systems import the contours directly. There's also a printable report for the tumour board.
And it measures every tumour automatically: SUVmax, metabolic volume, total lesion glycolysis.`);

// ================================================================= 10 · live demo
s = add("FM_CONTENT", "Demo");
P(s, "kicker", "kick", [R("LIVE DEMO", { color: OK })]);
P(s, "title", "ttl", "See it run on a full study in 26 seconds");
// a 50-second recording of the real app (record_demo.mjs); the first frame doubles as the poster
card(s, "app_frame", 0.6, 1.85, 8.1, 4.89, { fill: INK, line: LINE });
s.addMedia({
  type: "video", path: asset("demo.mp4"), x: 0.7, y: 1.95, w: 7.9, h: 4.69, objectName: named("app"),
  cover: `data:image/png;base64,${fs.readFileSync(asset("demo_poster.png")).toString("base64")}`,
});
text(s, "watch", "WHAT TO WATCH", { x: 9.15, y: 1.85, w: 3.5, h: 0.3, fontSize: 12, bold: true, color: MUTED, charSpacing: 2 });
const DEMO = [
  ["Alignment", "drag the swipe: naive vs FusionMap"],
  ["Sharpening", "PET as acquired vs AI-enhanced"],
  ["Ground-truth check", "every lesion verified against the truth"],
  ["Tumour metrics", "click a tumour: SUVmax, MTV, TBR"],
  ["Send to PACS", "plus the printable report"],
];
DEMO.forEach(([a, b], i) => {
  const y = 2.3 + i * 0.88;
  s.addText(String(i + 1), { shape: S.OVAL, x: 9.15, y: y + 0.08, w: 0.46, h: 0.46, fill: { color: PANEL }, line: { color: OK, width: 1.25 }, fontSize: 14, bold: true, color: OK, align: "center", valign: "middle", margin: 0, objectName: named(`dn${i}`) });
  text(s, `dt${i}`, [R(a, { bold: true, fontSize: 16, color: TXT, breakLine: true }), R(b, { fontSize: 12, color: MUTED })], { x: 9.8, y, w: 2.93, h: 0.66, valign: "middle" });
  anim(`dn${i}`, "zoom", 600 + i * 180, 450); anim(`dt${i}`, "floatL", 650 + i * 180, 550);
});
anim("app_frame", "zoom", 0, 800); anim("app", "zoom", 0, 800);
anim("watch", "fade", 450, 500);
s.addNotes(`[3:10-4:10]  LIVE DEMO (about 60 seconds)
BEFORE THE TALK: run "fusionmap serve" (or "docker compose up") and open http://localhost:8000. The showcase patient is processed automatically on first start.

1. Workspace > Compare > Alignment. Move the mouse across the axial view: "Left, the scans overlaid as the scanners left them; the glow is off the lesion. Right, after FusionMap, it sits on it." Point at 10.4 > 0.93 mm and the green "inside a 2 mm radiotherapy margin" line.
2. Compare > Sharpening: "PET as acquired on the left, AI-enhanced on the right."
3. Overview > Ground-truth check: "Viable tumour: found. MRI-occult tumour: found, because PET sees it. Radionecrosis: correctly NOT flagged."
4. Tumours tab: click a tumour and the viewer jumps to it. Read out SUVmax, MTV and TBR.
5. Export tab > Send to PACS (with docker compose the study appears in Orthanc on :8042). Then open the printable report.

BACKUP: if the live demo fails (no laptop, no Wi-Fi, crash), stay on this slide, hover the picture and click its play button. It is a 50-second recording of the real app doing exactly steps 1-5, so narrate over it.`);

// ================================================================= 11 · validation
s = add("FM_CONTENT", "Proof");
P(s, "kicker", "kick", "VALIDATION");
P(s, "title", "ttl", "Measured on patients where we know the truth");
const chartBase = {
  x: 0, y: 0, w: 0, h: 0, barDir: "col", barGapWidthPct: 55,
  showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.lt1, dataLabelFontSize: 14, dataLabelFontBold: true, dataLabelFontFace: "+mn-lt",
  catAxisLabelColor: HEX.lt2, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", catAxisLineShow: false,
  valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
};
[
  {
    key: "ce", x: 0.6, head: "Alignment error, mm", sub: "lower is better · auto mode picks rigid MI", badge: "−93 %", badgeCol: OK,
    labels: ["Overlay as-is", "Rigid MI", "+ B-spline", "+ VoxelMorph"], values: [11.8, 0.86, 0.92, 0.86], colors: [HEX.accent5, HEX.accent2, DIM_BAR, DIM_BAR], max: 14, fmt: "0.0#",
  },
  {
    key: "cq", x: 6.78, head: "PET image fidelity, PSNR in dB", sub: "higher is better", badge: "+10 dB", badgeCol: PET,
    labels: ["As acquired", "Deconvolution", "FusionMap ViT"], values: [26.4, 27.2, 36.6], colors: [DIM_BAR, DIM_BAR, HEX.accent1], max: 42, fmt: "0.0",
  },
].forEach((c, i) => {
  card(s, c.key, c.x, 1.85, 5.95, 4.0);
  text(s, `${c.key}_h`, [R(c.head, { bold: true, fontSize: 17, color: TXT, breakLine: true }), R(c.sub, { fontSize: 12, color: MUTED })], { x: c.x + 0.25, y: 2.0, w: 4.3, h: 0.7 });
  text(s, `${c.key}_b`, c.badge, { x: c.x + 4.3, y: 2.0, w: 1.4, h: 0.6, fontSize: 26, bold: true, color: c.badgeCol, align: "right", valign: "middle" });
  s.addChart(pres.charts.BAR, [{ name: c.head, labels: c.labels, values: c.values }], {
    ...chartBase, x: c.x + 0.15, y: 2.75, w: 5.65, h: 3.0, chartColors: c.colors, valAxisMinVal: 0, valAxisMaxVal: c.max, dataLabelFormatCode: c.fmt,
    objectName: named(`${c.key}_chart`),
  });
  const d = i * 600;
  anim(c.key, "fade", d, 500); anim(`${c.key}_h`, "fade", d, 500);
  anim(`${c.key}_chart`, "wipeU", d + 250, 900); anim(`${c.key}_b`, "zoom", d + 1100, 500);
});
card(s, "strip", 0.6, 6.0, 12.13, 0.72);
[
  ["12", " held-out test patients"],
  ["100 %", " of tumours detected"],
  ["0", " false positives"],
  ["1 mm", " exact ground-truth grid"],
].forEach(([a, b], i) => {
  text(s, `st${i}`, [R(a, { bold: true, fontSize: 22, color: i === 0 ? TXT : OK }), R(b, { fontSize: 14, color: MUTED })], { x: 0.6 + i * 3.0325, y: 6.0, w: 3.0325, h: 0.72, align: "center", valign: "middle" });
});
anim("strip", "float", 1900, 600);
[0, 1, 2, 3].forEach((i) => anim(`st${i}`, "float", 1900 + i * 120, 600));
s.addNotes(`[4:10-4:30]  WHY BELIEVE US
Real patients never come with the right answer, so we built digital patients from the MNI152 brain where we know the exact truth, and we measure error in millimetres.
Left: alignment error. Rigid mutual information, which our auto mode picks, cuts it by 93 %. VoxelMorph ties it on brain; more on that next.
Right: image fidelity. FusionMap's AI adds 10 dB over the raw PET and is far ahead of classical deconvolution.
100 % of tumours detected, with zero false positives.
All numbers: docs/benchmark.json, reproducible with "fusionmap benchmark".`);

// ================================================================= 12 · trust
s = add("FM_CONTENT");
P(s, "kicker", "kick", "TRUST");
P(s, "title", "ttl", "Built to be trusted, not just to impress");
const HX = 0.7, HY = 1.95, HW = 3.42, HH = 4.27, k = HW / 354;
framed(s, "heroimg", asset("hero_still.png"), HX, HY, HW, HH, "Fused PET/MRI slice: the living tumour glows, the radionecrosis stays grey");
const T1 = [HX + 101 * k, HY + 180 * k];
const T2 = [HX + 134 * k, HY + 326 * k];
s.addShape(S.OVAL, { x: T1[0] - 0.3, y: T1[1] - 0.3, w: 0.6, h: 0.6, line: { color: OK, width: 1.5, dashType: "dash" }, objectName: named("tr1") });
s.addShape(S.OVAL, { x: T2[0] - 0.3, y: T2[1] - 0.3, w: 0.6, h: 0.6, line: { color: PET, width: 1.75 }, objectName: named("tr2") });
line(s, "tl1", T1[0] + 0.3, T1[1], 4.35, T1[1], OK, { dash: "dash" });
line(s, "tl2", T2[0] + 0.3, T2[1], 4.35, T2[1], PET);
text(s, "tag1", [R("Radionecrosis", { bold: true, fontSize: 15, color: TXT, breakLine: true }), R("MRI says tumour, PET says dead: correctly not flagged", { fontSize: 12, color: MUTED })], { x: 4.45, y: T1[1] - 0.45, w: 2.05, h: 0.9, valign: "middle" });
text(s, "tag2", [R("Living tumour", { bold: true, fontSize: 15, color: PET, breakLine: true }), R("found, 0.3 mm from the truth", { fontSize: 12, color: MUTED })], { x: 4.45, y: T2[1] - 0.45, w: 2.05, h: 0.9, valign: "middle" });
const TRUST = [
  { key: "ta", ico: "shield", col: OK, head: "The radionecrosis trap", body: "Our test patients include lesions that MRI shows but PET says are dead. An AI that copies the MRI would light them up. FusionMap keeps them cold: uptake ratio 1.05, where 1.0 is perfect." },
  { key: "tb", ico: "check", col: MRI, head: "An AI gate, not AI everywhere", body: "Our VoxelMorph network matched classical alignment (1.172 vs 1.173 mm) but did not beat it, so auto mode keeps the classical method. AI switches on only when its own validation wins, and the raw PET is always exported too." },
];
TRUST.forEach((t, i) => {
  const y = 1.85 + i * 2.5;
  card(s, t.key, 6.85, y, 5.88, 2.3);
  ring(s, `${t.key}i`, t.ico, 7.1, y + 0.25, 0.6, t.col);
  text(s, `${t.key}h`, t.head, { x: 7.9, y: y + 0.25, w: 4.6, h: 0.6, fontSize: 20, bold: true, color: TXT, valign: "middle" });
  text(s, `${t.key}b`, t.body, { x: 7.1, y: y + 1.0, w: 5.4, h: 1.2, fontSize: 14, color: MUTED });
  const d = 1700 + i * 350;
  anim(t.key, "float", d, 650); ringAnim(`${t.key}i`, "float", d, 650); anim(`${t.key}h`, "float", d, 650); anim(`${t.key}b`, "fade", d + 200, 600);
});
framedAnim("heroimg", "fade", 0, 700);
anim("tr1", "zoom", 450, 450); anim("tl1", "wipeL", 650, 400); anim("tag1", "floatL", 800, 550);
anim("tr2", "zoom", 1050, 450); anim("tl2", "wipeL", 1250, 400); anim("tag2", "floatL", 1400, 550);
s.addNotes(`[4:30-4:50]  TRUST
In medicine, an AI has to be trustworthy, not just impressive. Two examples.
First, the radionecrosis trap. An AI that simply copies the MRI would light up dead tissue. Ours keeps it cold: an uptake ratio of 1.05, where 1.0 is perfect.
Second, honesty. Our VoxelMorph network matched classical alignment on the brain, but it didn't beat it. So FusionMap's auto mode doesn't use it. AI switches on only when it wins its own validation, and the unmodified PET is always exported alongside the AI PET.`);

// ================================================================= 13 · engineering
s = add("FM_CONTENT", "Platform & impact");
P(s, "kicker", "kick", "ENGINEERING");
P(s, "title", "ttl", "Runs on the hospital's own computer");
const NODES = [
  ["scanner", MRI, "Any PET + MRI", "DICOM or NIfTI, from two separate scanners"],
  ["cogs", PET, "FusionMap engine", "Python · SimpleITK · ONNX Runtime"],
  ["laptop", AMBER, "Web viewer", "React · runs in any browser"],
  ["server", OK, "PACS + planning", "standard DICOM out · C-STORE"],
];
NODES.forEach(([ico, col, a, b], i) => {
  const x = 0.6 + i * 3.127;
  card(s, `nd${i}`, x, 1.85, 2.75, 1.8);
  ring(s, `nd${i}i`, ico, x + 0.25, 2.1, 0.62, col);
  text(s, `nd${i}h`, a, { x: x + 1.02, y: 2.1, w: 1.63, h: 0.62, fontSize: 16, bold: true, color: TXT, valign: "middle" });
  text(s, `nd${i}s`, b, { x: x + 0.25, y: 2.88, w: 2.3, h: 0.65, fontSize: 13, color: MUTED });
  const d = i * 280;
  anim(`nd${i}`, "float", d, 600); ringAnim(`nd${i}i`, "float", d, 600); anim(`nd${i}h`, "float", d, 600); anim(`nd${i}s`, "float", d, 600);
  if (i < 3) { arrow(s, `ar${i}`, x + 2.8, 2.63); anim(`ar${i}`, "wipeL", d + 250, 300); }
});
const FACTS = [
  ["CPU only", OK, "26 s per study. No GPU, no cloud."],
  ["Private", OK, "patient data never leaves the hospital"],
  ["45 tests", MRI, "automated, run by CI on every push"],
  ["1 command", AMBER, "docker compose up, PACS included"],
];
FACTS.forEach(([a, col, b], i) => {
  const x = 0.6 + i * 3.09;
  card(s, `fc${i}`, x, 3.9, 2.86, 1.3);
  text(s, `fc${i}t`, [R(a, { bold: true, fontSize: 26, color: col, breakLine: true }), R(b, { fontSize: 14, color: MUTED })], { x: x + 0.25, y: 3.95, w: 2.45, h: 1.2, valign: "middle" });
  anim(`fc${i}`, "zoom", 1250 + i * 150, 500); anim(`fc${i}t`, "zoom", 1250 + i * 150, 500);
});
card(s, "lit", 0.6, 5.45, 12.13, 1.22);
ring(s, "liti", "book", 0.85, 5.76, 0.6, MRI);
text(s, "lit_t", [R("Every design choice traces back to published research", { bold: true, fontSize: 16, color: TXT, breakLine: true }), R("Nensa 2014  ·  Catana 2011  ·  Yoon 2012  ·  Wei 2022  ·  Alongi 2024  ·  Chen 2024 (Plasma CycleGAN)  ·  Chen 2025 (MRI-to-PET synthesis)", { fontSize: 13, color: MUTED })], { x: 1.65, y: 5.5, w: 10.9, h: 1.12, valign: "middle" });
anim("lit", "fade", 2000, 600); ringAnim("liti", "fade", 2000, 600); anim("lit_t", "fade", 2100, 600);
s.addNotes(`[4:50-5:05]  ENGINEERING
It runs on the hospital's own computer: CPU only, 26 seconds for a full study. No GPU, no cloud, so patient data never leaves the building.
It reads DICOM from any PET and any MRI, and writes standard DICOM back.
45 automated tests run on every push, and one docker command brings up the app together with a PACS.
And every design decision traces back to the seven papers we studied. The mapping is in docs/LITERATURE.md.`);

// ================================================================= 14 · impact
s = add("FM_CONTENT");
P(s, "kicker", "kick", "IMPACT");
P(s, "title", "ttl", "PET-MRI-grade precision for the price of software");
const COMPARE = [
  { key: "old", x: 0.6, head: "Integrated PET-MRI scanner", headCol: MUTED, line: LINE, lineW: 0.75, rows: [["$4–6 M", "per scanner"], ["New suite", "shielding, siting, specialist staff"], ["~10", "in all of India"]] },
  { key: "new", x: 6.78, head: "FusionMap", headCol: PET, line: PET, lineW: 1.75, rows: [["₹40–60 k", "to build"], ["₹0", "new hardware: uses the PET and MRI already there"], ["700+", "centres that could run it"]] },
];
COMPARE.forEach((c, i) => {
  card(s, c.key, c.x, 1.85, 5.95, 3.55, { line: c.line, lineW: c.lineW });
  if (i === 0) ring(s, `${c.key}i`, "hospital", c.x + 0.3, 2.08, 0.6, MUTED);
  else s.addImage({ path: asset("logo.png"), x: c.x + 0.22, y: 1.98, w: 0.78, h: 0.78, altText: "FusionMap logo", objectName: named(`${c.key}i`) });
  text(s, `${c.key}h`, c.head, { x: c.x + 1.1, y: 2.08, w: 4.6, h: 0.6, fontSize: 20, bold: true, color: c.headCol, valign: "middle" });
  c.rows.forEach(([a, b], j) => {
    text(s, `${c.key}r${j}`, [R(a, { bold: true, fontSize: 26, color: i === 0 ? TXT : PET })], { x: c.x + 0.3, y: 2.9 + j * 0.8, w: 2.35, h: 0.7, valign: "middle" });
    text(s, `${c.key}d${j}`, b, { x: c.x + 2.7, y: 2.9 + j * 0.8, w: 3.05, h: 0.7, fontSize: 14, color: MUTED, valign: "middle" });
  });
  const d = i * 700;
  anim(c.key, i ? "float" : "fade", d, 650);
  if (i === 0) ringAnim(`${c.key}i`, "fade", d, 650); else anim(`${c.key}i`, "zoom", d + 100, 600);
  anim(`${c.key}h`, i ? "float" : "fade", d, 650);
  c.rows.forEach((_, j) => { anim(`${c.key}r${j}`, i ? "zoom" : "fade", d + 200 + j * 150, 500); anim(`${c.key}d${j}`, "fade", d + 250 + j * 150, 500); });
});
const WINS = [
  ["users", AMBER, "Patients", "radiotherapy aimed at the living tumour"],
  ["eye", MRI, "Doctors", "one fused image instead of two screens"],
  ["hospital", OK, "Hospitals", "a new capability with no capital cost"],
];
WINS.forEach(([ico, col, a, b], i) => {
  const x = 0.6 + i * 4.15;
  ring(s, `w${i}`, ico, x, 5.72, 0.6, col);
  text(s, `w${i}t`, [R(a, { bold: true, fontSize: 16, color: TXT, breakLine: true }), R(b, { fontSize: 14, color: MUTED })], { x: x + 0.78, y: 5.62, w: 3.2, h: 0.8, valign: "middle" });
  ringAnim(`w${i}`, "zoom", 1800 + i * 180, 450); anim(`w${i}t`, "floatL", 1850 + i * 180, 550);
});
s.addNotes(`[5:05-5:20]  IMPACT
An integrated PET-MRI scanner costs 4 to 6 million dollars, needs a new suite and specialist staff, and India has about ten.
FusionMap costs 40 to 60 thousand rupees to build and needs zero new hardware, so it can run in the 700-plus centres that already own both scanners.
Patients get radiotherapy aimed at the living tumour, doctors get one fused image instead of two screens, and hospitals get a new capability with no capital cost.`);

// ================================================================= 15 · roadmap
s = add("FM_CONTENT");
P(s, "kicker", "kick", "WHAT'S NEXT");
P(s, "title", "ttl", "From prototype to the clinic");
const ROAD = [
  { tag: "NOW", col: OK, head: "Working prototype", body: "Validated on 12 digital patients, DICOM in and out, PACS push, 45 tests" },
  { tag: "NEXT", col: MRI, head: "Real scans", body: "Fine-tune on paired PET/MRI from The Cancer Imaging Archive (TCIA)" },
  { tag: "THEN", col: AMBER, head: "Reader study", body: "Nuclear-medicine physicians compare FusionMap with hybrid PET-MRI" },
  { tag: "SCALE", col: PET, head: "Clinic and body", body: "CDSCO medical-device software pathway; lung and prostate with VoxelMorph" },
];
const cxs = ROAD.map((_, i) => 0.6 + i * 3.093 + 1.425);
line(s, "tline", cxs[0], 2.55, cxs[3], 2.55, LINE, { width: 2 });
anim("tline", "wipeL", 0, 1300);
ROAD.forEach((r, i) => {
  const x = 0.6 + i * 3.093;
  text(s, `rt${i}`, r.tag, { x: cxs[i] - 1.0, y: 1.85, w: 2.0, h: 0.32, fontSize: 13, bold: true, color: r.col, align: "center", charSpacing: 3 });
  s.addText(i === 0 ? "✓" : String(i + 1), { shape: S.OVAL, x: cxs[i] - 0.25, y: 2.3, w: 0.5, h: 0.5, fill: { color: i === 0 ? r.col : PANEL }, line: { color: r.col, width: 1.5 }, fontSize: 15, bold: true, color: i === 0 ? INK : r.col, align: "center", valign: "middle", margin: 0, objectName: named(`rn${i}`) });
  card(s, `rc${i}`, x, 3.05, 2.85, 2.05);
  text(s, `rc${i}h`, r.head, { x: x + 0.25, y: 3.25, w: 2.4, h: 0.5, fontSize: 18, bold: true, color: TXT, valign: "middle" });
  text(s, `rc${i}b`, r.body, { x: x + 0.25, y: 3.85, w: 2.4, h: 1.4, fontSize: 14, color: MUTED });
  const d = 150 + i * 320;
  anim(`rn${i}`, "zoom", d, 450); anim(`rt${i}`, "fade", d, 450);
  anim(`rc${i}`, "float", d + 100, 600); anim(`rc${i}h`, "float", d + 100, 600); anim(`rc${i}b`, "float", d + 200, 600);
});
card(s, "ask", 0.6, 5.4, 12.13, 1.0, { line: PET, lineW: 1.25 });
ring(s, "aski", "rocket", 0.85, 5.6, 0.6, PET);
text(s, "ask_t", [R("What would speed us up: ", { bold: true, color: TXT }), R("a clinical partner with a PET and an MRI, for real-patient validation and the reader study.", { color: MUTED })], { x: 1.65, y: 5.45, w: 10.9, h: 0.9, fontSize: 17, valign: "middle" });
anim("ask", "float", 1700, 650); ringAnim("aski", "float", 1700, 650); anim("ask_t", "float", 1750, 650);
s.addNotes(`[5:20-5:35]  WHAT'S NEXT
The prototype works today.
Next, we fine-tune on real paired PET/MRI scans from The Cancer Imaging Archive.
Then a reader study with nuclear-medicine physicians, comparing FusionMap with a real hybrid PET-MRI.
Then the CDSCO software-as-a-medical-device pathway, and body sites like lung and prostate, where VoxelMorph's deformable alignment matters most.
What would speed us up most is a clinical partner.`);

// ================================================================= 16 · close
s = add("FM_STATEMENT", "Close", "fadeBlack");
P(s, "title", "kick", "THANK YOU  ·  QUESTIONS?");
s.addShape(S.OVAL, { x: 7.225, y: 1.6, w: 4.3, h: 4.3, line: { color: MRI, width: 2.25 }, objectName: named("ringB") });
s.addShape(S.OVAL, { x: 8.475, y: 1.6, w: 4.3, h: 4.3, line: { color: PET, width: 2.25 }, objectName: named("ringO") });
s.addImage({ path: asset("mip.gif"), x: 8.55, y: 2.3, w: 2.9, h: 2.9, rounding: true, altText: "Rotating PET projection of the brain with two glowing tumours", objectName: named("mip") });
text(s, "st1", "700+ hospitals already own a PET and an MRI.", { x: 0.8, y: 1.3, w: 6.2, h: 1.5, fontSize: 40, bold: true, color: TXT, valign: "bottom" });
text(s, "st2", "FusionMap turns them into a PET-MRI.", { x: 0.8, y: 2.95, w: 6.2, h: 1.5, fontSize: 40, bold: true, color: PET });
s.addImage({ path: asset("logo.png"), x: 0.65, y: 4.62, w: 0.85, h: 0.85, altText: "FusionMap logo", objectName: named("logo") });
text(s, "brand", "FusionMap", { x: 1.55, y: 4.7, w: 4, h: 0.7, fontSize: 28, bold: true, color: TXT, valign: "middle" });
text(s, "team", [
  R("Team MeatRiders", { fontSize: 15, bold: true, color: TXT, breakLine: true }),
  R("Parth Deshmukh  ·  Atharva Jadhav  ·  Samuel Cardoza  ·  Ralston Crasta", { fontSize: 15, color: MUTED, breakLine: true }),
  R("github.com/dev-parthdeshmukh/fusiontech", { fontSize: 15, color: MRI, hyperlink: { url: "https://github.com/dev-parthdeshmukh/fusiontech" } }),
], { x: 0.8, y: 5.6, w: 7.5, h: 1.05 });
anim("ringB", "zoom", 0, 800); anim("ringO", "zoom", 250, 800);
anim("mip", "fade", 600, 900);
anim("kick", "fade", 300, 500);
anim("st1", "float", 800, 800); anim("st2", "float", 1400, 800);
anim("logo", "zoom", 2000, 600); anim("brand", "fade", 2100, 600); anim("team", "fade", 2300, 600);
s.addNotes(`[5:35-5:45]  CLOSE
To close: more than 700 hospitals already own a PET and an MRI.
FusionMap turns them into a PET-MRI.
Thank you. We'd love your questions.

(Leave this slide up during Q&A. If a judge asks one of the expected questions, the next slide has the short answers.)`);

// ================================================================= 17 · backup Q&A
s = add("FM_CONTENT", "Backup");
P(s, "kicker", "kick", [R("BACKUP  ·  JUDGE Q&A", { color: MRI })]);
P(s, "title", "ttl", "Questions we expect, answered");
const QA = [
  ["Validated on real patients?", "Not yet, and we say so on every screen. Real scan pairs have no ground truth, so we use digital patients with exact answers. Next: TCIA data and a reader study."],
  ["Why not just use PET-CT?", "CT shows brain soft tissue poorly and adds radiation. PET/MRI can cut the dose to about 20 % of PET/CT (Nensa 2014)."],
  ["Does the AI copy the MRI?", "That's exactly what we test for: radionecrosis stays cold (ratio 1.05), and the raw PET is always exported beside the AI PET."],
  ["Why a ViT, not CycleGAN?", "With paired data, a supervised ViT hybrid is more faithful. We ship a CycleGAN trainer for hospitals that only have unpaired data."],
  ["Does it need a GPU or the cloud?", "No. ONNX Runtime on a CPU, about 26 s per study, and patient data never leaves the hospital."],
  ["How does it fit the workflow?", "DICOM in, standard DICOM out: MR, SUV PET, AI PET, colour fusion and RT-STRUCT, pushed to PACS by C-STORE."],
];
QA.forEach(([q, a], i) => {
  const x = 0.6 + (i % 3) * 4.15;
  const y = 1.85 + Math.floor(i / 3) * 2.45;
  card(s, `qa${i}`, x, y, 3.83, 2.25);
  text(s, `qa${i}t`, [R(q, { bold: true, fontSize: 17, color: MRI, breakLine: true }), R(a, { fontSize: 15, color: MUTED })], { x: x + 0.25, y: y + 0.22, w: 3.33, h: 1.85 });
  anim(`qa${i}`, "fade", i * 120, 500); anim(`qa${i}t`, "fade", i * 120, 500);
});
s.addNotes(`BACKUP: show only if a judge asks. Full answers: docs/PITCH.md.

Regulatory path? In India: software as a medical device under CDSCO, which needs clinical evaluation. Step one is a retrospective reader study against hybrid PET-MRI.
Why VoxelMorph if the brain is rigid? We measured it: it tied rigid MI on brain (1.172 vs 1.173 mm), so auto mode keeps rigid. It's built for lung and prostate, where organs deform.
Where do the market numbers come from? Team research: scanner cost, centre counts, patient numbers. Every alignment, quality and detection number was measured by us (docs/benchmark.json).`);

// ---------------------------------------------------------------- write
(async () => {
  fs.mkdirSync(BUILD, { recursive: true });
  await pres.writeFile({ fileName: OUT });
  fs.writeFileSync(path.join(BUILD, "animations.json"), JSON.stringify(spec, (k, v) => (v instanceof Set ? undefined : v), 2));
  // optional: the pptx skill's theme writer (animate.py writes the same theme if it is absent)
  const skill = process.env.PPTX_SKILL_DIR;
  if (skill && fs.existsSync(path.join(skill, "scripts", "apply_theme.js"))) {
    const { applyTheme } = require(path.join(skill, "scripts", "apply_theme.js"));
    await applyTheme(OUT, THEME);
  }
  console.log(`wrote ${path.relative(ROOT, OUT)} (${spec.slides.length} slides)`);
})();
