// Records the 40-second backup demo video for the "Live demo" slide.
//
//   FUSIONMAP_DATA=var/showcase fusionmap serve --port 8011 &
//   node presentation/record_demo.mjs http://127.0.0.1:8011/ presentation/build/video
//   (then presentation/make_video.sh turns the WebM into assets/demo.mp4)
//
// Headless Chromium draws no mouse pointer, so the page gets a synthetic one.
import { chromium } from "playwright";
import fs from "node:fs";

const [, , url = "http://127.0.0.1:8011/", out = "presentation/build/video"] = process.argv;
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

const W = 1600, H = 950;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium", args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: out, size: { width: W, height: H } } });
const t0 = Date.now();
await ctx.addInitScript(() => {
  addEventListener("DOMContentLoaded", () => {
    const c = document.createElement("div");
    c.id = "__cursor";
    Object.assign(c.style, {
      position: "fixed", left: "0", top: "0", width: "22px", height: "22px", margin: "-11px 0 0 -11px",
      borderRadius: "50%", background: "rgba(255,255,255,.85)", border: "2px solid rgba(255,122,61,.95)",
      boxShadow: "0 0 0 6px rgba(255,122,61,.18)", pointerEvents: "none", zIndex: "2147483647",
      transition: "transform .12s ease", transform: "translate(-100px,-100px)",
    });
    document.body.appendChild(c);
    let x = -100, y = -100;
    addEventListener("mousemove", (e) => { x = e.clientX; y = e.clientY; c.style.transform = `translate(${x}px,${y}px)`; }, true);
    addEventListener("mousedown", () => { c.style.transform = `translate(${x}px,${y}px) scale(.7)`; }, true);
    addEventListener("mouseup", () => { c.style.transform = `translate(${x}px,${y}px)`; }, true);
  });
});
const page = await ctx.newPage();
await page.goto(url, { waitUntil: "networkidle" });
await page.locator(".viewgrid .main .pane canvas").first().waitFor();
await page.waitForTimeout(3500); // volumes stream in
const ready = (Date.now() - t0) / 1000;

let mx = W / 2, my = H / 2;
const ease = (t) => 0.5 - 0.5 * Math.cos(Math.PI * t);
async function glide(x, y, ms = 700) {
  const n = Math.max(2, Math.round(ms / 16));
  const [x0, y0] = [mx, my];
  for (let i = 1; i <= n; i++) {
    const t = ease(i / n);
    await page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t);
    await page.waitForTimeout(16);
  }
  [mx, my] = [x, y];
}
async function clickOn(locator, pause = 900) {
  const b = await locator.boundingBox();
  await glide(b.x + b.width / 2, b.y + b.height / 2, 650);
  await page.mouse.down(); await page.waitForTimeout(90); await page.mouse.up();
  await page.waitForTimeout(pause);
}
const pane = page.locator(".viewgrid .main .pane").first();
const box = await pane.boundingBox();
const swipe = async (times, ms) => {
  for (let i = 0; i < times; i++) {
    await glide(box.x + box.width * 0.8, box.y + box.height * 0.62, ms);
    await glide(box.x + box.width * 0.2, box.y + box.height * 0.62, ms);
  }
  await glide(box.x + box.width * 0.5, box.y + box.height * 0.62, ms / 2);
};

// 1 · alignment: naive overlay vs FusionMap
await glide(box.x + box.width * 0.5, box.y + box.height * 0.62, 600);
await swipe(2, 1300);
await page.waitForTimeout(600);
// 2 · sharpening: registered PET vs AI-enhanced
await clickOn(page.getByRole("button", { name: "Sharpening", exact: true }), 700);
await glide(box.x + box.width * 0.5, box.y + box.height * 0.62, 500);
await swipe(1, 1300);
await page.waitForTimeout(500);
// 3 · tumours: click each, the viewer jumps to it
await clickOn(page.getByRole("tab", { name: "Tumours" }), 800);
const rows = page.locator("button.hs");
await clickOn(rows.nth(0), 1800);
await clickOn(rows.nth(1), 1800);
// 4 · ground-truth check on the overview
await clickOn(page.getByRole("tab", { name: "Overview" }), 600);
const gt = page.getByText("Ground truth check", { exact: false }).first();
await gt.scrollIntoViewIfNeeded().catch(() => {});
await glide(1400, 640, 600);
await page.mouse.wheel(0, 260);
await page.waitForTimeout(2600);
// 5 · export: DICOM, PACS push, report
await clickOn(page.getByRole("tab", { name: "Export" }), 3200);
// back to the fused view for the last frame
await clickOn(page.getByRole("button", { name: "Fused", exact: false }).first(), 1500);

const end = (Date.now() - t0) / 1000;
await ctx.close();
await browser.close();
const [file] = fs.readdirSync(out).filter((f) => f.endsWith(".webm"));
fs.writeFileSync(`${out}/timing.json`, JSON.stringify({ file: `${out}/${file}`, ready, end }, null, 2));
console.log(`recorded ${file}: usable from ${ready.toFixed(1)} s to ${end.toFixed(1)} s`);
