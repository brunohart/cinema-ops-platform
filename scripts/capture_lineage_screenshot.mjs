/**
 * VDE-23 — capture Dagster global asset lineage for the case study.
 * Dark UI, retina DPR, no browser chrome (page screenshot).
 */
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.DAGSTER_URL || "http://127.0.0.1:3000";
const OUT =
  process.env.OUT ||
  new URL("../docs/assets/2026-07-31-vde-23-lineage-graph.png", import.meta.url).pathname;

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || "/usr/local/bin/google-chrome",
  headless: "new",
  args: [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
    "--force-device-scale-factor=2",
    "--high-dpi-support=1",
  ],
  defaultViewport: {
    width: 1680,
    height: 960,
    deviceScaleFactor: 2,
  },
});

const page = await browser.newPage();
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "dark" }]);

// Seed dark theme preferences before first paint.
await page.evaluateOnNewDocument(() => {
  const keys = [
    ["dagster.theme", JSON.stringify("dark")],
    ["theme", "dark"],
    ["dagster-theme", "dark"],
    ["ColorScheme", "DARK"],
    ["dagster.colorScheme", "DARK"],
  ];
  for (const [k, v] of keys) {
    try {
      localStorage.setItem(k, v);
    } catch (_) {}
  }
});

await page.goto(`${BASE}/asset-groups`, {
  waitUntil: "networkidle0",
  timeout: 120_000,
});

// Dismiss any modal / toast that blocks the graph.
async function dismissOverlays() {
  await page.evaluate(() => {
    for (const b of document.querySelectorAll("button")) {
      const t = (b.textContent || "").trim();
      if (/^(OK|Done|Close|Dismiss|Got it|Not now|Skip)$/i.test(t)) b.click();
    }
    // Escape-key style: click backdrop if present
    const dialogs = document.querySelectorAll('[role="dialog"], [class*="Dialog"]');
    for (const d of dialogs) {
      const ok = [...d.querySelectorAll("button")].find((b) =>
        /^(OK|Done|Close)$/i.test((b.textContent || "").trim()),
      );
      if (ok) ok.click();
    }
  });
  await page.keyboard.press("Escape").catch(() => {});
  await new Promise((r) => setTimeout(r, 400));
}

await dismissOverlays();

// Open settings once, pick Dark, close — then never leave settings open.
async function setDarkThemeViaUi() {
  const opened = await page.evaluate(() => {
    const buttons = [...document.querySelectorAll("button, a")];
    const settings = buttons.find((b) =>
      /settings|preferences/i.test(
        `${b.getAttribute("aria-label") || ""} ${b.textContent || ""}`,
      ),
    );
    if (!settings) return false;
    settings.click();
    return true;
  });
  if (!opened) return;
  await new Promise((r) => setTimeout(r, 700));

  await page.evaluate(() => {
    // Theme section: click Dark specifically.
    const nodes = [...document.querySelectorAll("button, [role='radio'], label, div, span")];
    const dark = nodes.find((el) => {
      const t = (el.textContent || "").trim();
      return t === "Dark" || t === "Dark theme";
    });
    if (dark) dark.click();
  });
  await new Promise((r) => setTimeout(r, 500));

  // Close settings with Done / Escape — do NOT reset caches.
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll("button")];
    const done = buttons.find((b) => /^(Done|Close)$/i.test((b.textContent || "").trim()));
    if (done) done.click();
  });
  await page.keyboard.press("Escape").catch(() => {});
  await new Promise((r) => setTimeout(r, 600));
  await dismissOverlays();
}

await setDarkThemeViaUi();
await dismissOverlays();

// Ensure we are on lineage, not settings.
await page.goto(`${BASE}/asset-groups`, {
  waitUntil: "networkidle0",
  timeout: 120_000,
});
await dismissOverlays();

await page.waitForFunction(
  () => {
    const text = document.body?.innerText || "";
    return text.includes("raw_tmdb") && text.includes("fct_ticket_sale");
  },
  { timeout: 120_000 },
);

// Let materialization live-data paint green/materialized state.
await new Promise((r) => setTimeout(r, 3000));
await dismissOverlays();

// Hide left navigation to give the graph the frame (collapse non-load-bearing chrome).
await page.evaluate(() => {
  const buttons = [...document.querySelectorAll("button")];
  const hideNav = buttons.find((b) =>
    /hide navigation|collapse navigation|close navigation/i.test(
      `${b.getAttribute("aria-label") || ""} ${b.textContent || ""}`,
    ),
  );
  if (hideNav) hideNav.click();
});
await new Promise((r) => setTimeout(r, 500));

// Collapse the right-hand asset detail pane if open (load-bearing is the graph).
await page.evaluate(() => {
  // Click empty canvas background to deselect assets / close detail.
  const graph = document.querySelector('[class*="AssetGraph"], .react-flow, main');
  if (graph) {
    const r = graph.getBoundingClientRect();
    const ev = new MouseEvent("click", {
      bubbles: true,
      clientX: r.left + 20,
      clientY: r.top + 20,
    });
    graph.dispatchEvent(ev);
  }
});
await page.keyboard.press("Escape").catch(() => {});
await new Promise((r) => setTimeout(r, 400));

// Zoom to fit so four sources + gold share one frame.
await page.evaluate(() => {
  const controls = [...document.querySelectorAll("button, [role='button']")];
  const fit = controls.find((b) => {
    const label = `${b.getAttribute("aria-label") || ""} ${b.getAttribute("title") || ""} ${b.textContent || ""}`;
    return /zoom to fit|fit to screen|fit content|reset zoom|fit/i.test(label);
  });
  if (fit) fit.click();
});
// Dagster / react-flow common shortcut
for (const key of ["Digit0", "Equal", "KeyF"]) {
  await page.keyboard.down("Control");
  await page.keyboard.press(key).catch(() => {});
  await page.keyboard.up("Control");
}
await new Promise((r) => setTimeout(r, 1200));
await dismissOverlays();

// Final check: no dialog should be visible.
const blocked = await page.evaluate(() => {
  const dialog = document.querySelector('[role="dialog"]');
  if (!dialog) return null;
  const style = getComputedStyle(dialog);
  if (style.display === "none" || style.visibility === "hidden") return null;
  return (dialog.textContent || "").slice(0, 200);
});
if (blocked) {
  console.log("blocking dialog still present, dismissing again:", blocked.slice(0, 80));
  await dismissOverlays();
  await page.goto(`${BASE}/asset-groups`, { waitUntil: "networkidle0", timeout: 120_000 });
  await new Promise((r) => setTimeout(r, 2500));
  await dismissOverlays();
}

const graphBox = await page.evaluate(() => {
  // Prefer the graph canvas itself, excluding sidebars when possible.
  const candidates = [
    ...document.querySelectorAll('[class*="AssetGraph"]'),
    ...document.querySelectorAll(".react-flow"),
    ...document.querySelectorAll('[data-testid="asset-graph"]'),
  ];
  let best = null;
  for (const el of candidates) {
    const r = el.getBoundingClientRect();
    const area = r.width * r.height;
    if (r.width > 500 && r.height > 350 && (!best || area > best.area)) {
      best = { area, r, sel: el.className?.toString?.().slice(0, 80) || el.tagName };
    }
  }
  if (!best) return null;
  return {
    x: Math.max(0, best.r.x),
    y: Math.max(0, best.r.y),
    width: best.r.width,
    height: best.r.height,
    sel: best.sel,
  };
});

fs.mkdirSync(path.dirname(OUT), { recursive: true });

if (graphBox) {
  const clip = {
    x: Math.floor(graphBox.x),
    y: Math.floor(graphBox.y),
    width: Math.floor(Math.min(graphBox.width, 1680 - graphBox.x)),
    height: Math.floor(Math.min(graphBox.height, 960 - graphBox.y)),
  };
  console.log("clip", graphBox.sel, clip);
  await page.screenshot({ path: OUT, type: "png", clip });
} else {
  console.log("no graph clip — viewport");
  await page.screenshot({ path: OUT, type: "png", fullPage: false });
}

const dump = await page.evaluate(() => ({
  title: document.title,
  url: location.href,
  theme: {
    colorScheme: getComputedStyle(document.documentElement).colorScheme,
    bg: getComputedStyle(document.body).backgroundColor,
  },
  hasDialog: !!document.querySelector('[role="dialog"]'),
  sampleText: (document.body.innerText || "").slice(0, 1500),
}));
fs.writeFileSync("/tmp/lineage-shot/debug.json", JSON.stringify(dump, null, 2));
console.log("wrote", OUT, "bytes", fs.statSync(OUT).size);
console.log(JSON.stringify({ url: dump.url, theme: dump.theme, hasDialog: dump.hasDialog }));

await browser.close();
