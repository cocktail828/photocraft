// End-to-end checks of the real browser workspace; screenshots come from the running app.
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium, firefox, webkit } from "playwright";
const browserName = process.env.PHOTOCRAFT_BROWSER || "chromium";
const engine = { chromium, firefox, webkit }[browserName];
assert.ok(engine, "Unknown browser engine");

const base = process.env.PHOTOCRAFT_BASE_URL || "http://127.0.0.1:8000";
const folder = process.env.PHOTOCRAFT_SCREENSHOT_DIR || "artifacts/web-ui";
await mkdir(folder, { recursive: true });
const browser = await engine.launch({
  headless: true,
  ...(browserName === "chromium" ? { args: ["--no-sandbox"] } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 1,
  acceptDownloads: true,
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const shot = async (name) => {
  await page.locator("#toast").waitFor({ state: "hidden" });
  return page.screenshot({ path: join(folder, name + ".png") });
};
const waitText = async (id, text) =>
  page.waitForFunction(
    ({ id, text }) => document.getElementById(id).textContent.includes(text),
    { id, text },
  );
const select = async (name) => page.locator(`[data-tool="${name}"]`).click();
let sid;
try {
  await page.goto(base);
  await waitText("service-label", "已连接");
  await page.evaluate(async () => {
    const { blurThumbnail } = await import("/static/blur.js");
    const sample = document.createElement("canvas");
    sample.width = 3;
    sample.height = 1;
    const context = sample.getContext("2d");
    context.fillStyle = "#ff0000";
    context.fillRect(1, 0, 1, 1);
    blurThumbnail(sample, 1);
    const data = context.getImageData(0, 0, 3, 1).data;
    if (data[0] !== 255 || data[3] !== 85 || data[4] !== 255 || data[7] !== 85)
      throw new Error("Portable blur must preserve color around transparent edges");
  });
  assert.equal(
    await page
      .locator(".menus, #new-template, #config-dialog")
      .count(),
    0,
  );
  await shot("welcome");
  const demoResponse = page.waitForResponse(
    (r) => r.url().endsWith("/api/demo") && r.status() === 201,
  );
  await page.locator("#demo-button").click();
  sid = (await (await demoResponse).json()).id;
  const route = base + "/api/sessions/" + sid;
  const state = async () => context.request.get(route).then((r) => r.json());
  const payload = async () =>
    context.request.get(route + "/download").then((r) => r.body());
  const original = await payload();
  await waitText("preview-info", "295 × 413");
  await shot("crop");
  await page.locator("#apply-button").click();
  await waitText("current-info", "295 × 413");
  await page.locator("#crop-mode").selectOption("t:1");
  await waitText("preview-info", "允许缩放");
  await page.locator("#apply-button").click();
  await page.locator("#error-dialog").waitFor({ state: "visible" });
  assert.match(await page.locator("#error-message").textContent(), /允许缩放/);
  assert.equal((await state()).current.width, 295);
  await page.locator("#error-dialog .primary").click();
  await page.locator("#undo-button").click();
  await waitText("current-info", "720 × 900");
  assert.deepEqual(await payload(), original);
  await select("crop");
  await page.locator("#crop-mode").selectOption("custom");
  assert.equal(await page.locator('[data-field="ratio_w"]').inputValue(), "16");
  assert.equal(await page.locator('[data-field="ratio_h"]').inputValue(), "9");
  await waitText("preview-badge", "未应用");
  await shot("crop-ratio");
  await select("watermark");
  await page.locator("#mark-text").fill("仅用于资料审核");
  await page.locator('[data-pick-color="color"]').click();
  await page.locator("#color-dialog").waitFor({ state: "visible" });
  assert.equal(await page.locator("#color-presets .swatch").count(), 16);
  await page.locator('#color-presets [data-value="#ef4444"]').click();
  assert.equal(await page.locator("#color-hex").inputValue(), "#ef4444");
  assert.equal(await page.locator('#color-presets [aria-pressed="true"]').getAttribute("data-value"), "#ef4444");
  await shot("colors");
  await page.locator("#color-hex").fill("#64748b");
  await page.locator("#color-g").evaluate((el) => {
    el.value = "116";
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.equal(await page.locator("#color-hex").inputValue(), "#64748b");
  await page.locator('#color-form button[type="submit"]').click();
  await page.locator("#color-dialog").waitFor({ state: "hidden" });
  assert.ok(
    (await page.locator('[data-pick-color="color"]').textContent()).includes(
      "#64748b",
    ),
  );
  await waitText("preview-badge", "未应用");
  await page.waitForFunction(() => !document.body.classList.contains("busy"));
  await page.waitForTimeout(350);
  await shot("watermark");
  assert.deepEqual(
    await payload(),
    original,
    "watermark draft must never enter saved pixels",
  );
  await page.locator("#apply-button").click();
  await waitText("preview-badge", "与当前一致");
  assert.notDeepEqual(await payload(), original);
  await select("enhance");
  await page.locator('[data-field="brightness"]').evaluate((el) => {
    el.dispatchEvent(new PointerEvent("pointerdown"));
    el.value = "1.25";
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForFunction(
    async (url) =>
      (await (await fetch(url)).json()).enhancement.brightness === 1.25,
    route,
  );
  assert.equal(
    await page.locator('[data-field="brightness"]').inputValue(),
    "1.25",
  );
  await shot("enhance");
  await select("brush");
  const beforeBrush = (await state()).revision;
  const box = await page.locator("#editor-canvas").boundingBox();
  await page.mouse.move(box.x + box.width / 2 - 30, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, {
    steps: 12,
  });
  await page.mouse.up();
  await page.waitForFunction(
    async ({ url, revision }) =>
      (await (await fetch(url)).json()).revision > revision,
    { url: route, revision: beforeBrush },
  );
  await shot("brush");
  await page.locator("#undo-button").click();
  await page.waitForFunction(
    async ({ url, revision }) =>
      (await (await fetch(url)).json()).revision > revision + 1,
    { url: route, revision: beforeBrush },
  );
  for (const name of ["mosaic", "blur"]) {
    await select(name);
    const before = await state();
    const originalBytes = await payload();
    const localBefore = await page.locator("#editor-canvas").evaluate((el) => el.toDataURL());
    await page.mouse.move(box.x + box.width / 2 - 30, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2, { steps: 12 });
    const localAfter = await page.locator("#editor-canvas").evaluate((el) => el.toDataURL());
    assert.notEqual(localAfter, localBefore, `${name} must preview while drawing`);
    await page.mouse.up();
    await page.waitForFunction(async ({ url, revision }) => (await (await fetch(url)).json()).revision > revision,
      { url: route, revision: before.revision });
    await page.locator("#undo-button").click();
    await page.waitForFunction(async ({ url, revision }) => (await (await fetch(url)).json()).revision > revision + 1,
      { url: route, revision: before.revision });
    assert.deepEqual(await payload(), originalBytes);
  }
  await select("compress");
  await page.locator('[data-field="format"]').selectOption("WEBP");
  await page.locator('[data-field="quality"]').evaluate((el) => {
    el.value = "45";
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await waitText("preview-info", "WEBP");
  await waitText("preview-info", "质量 45");
  const beforeCompress = await payload();
  await shot("workspace");
  await shot("compress");
  await page.locator("#apply-button").click();
  await waitText("current-info", "WEBP");
  assert.equal((await state()).current.quality, 45);
  const compressed = await payload();
  assert.notDeepEqual(compressed, beforeCompress);
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#save-button").click();
  const downloaded = await downloadEvent;
  assert.ok(downloaded.suggestedFilename().endsWith(".webp"));
  assert.deepEqual(await readFile(await downloaded.path()), compressed);
  await page.locator("#actual-button").click();
  assert.equal(await page.locator("#zoom").textContent(), "100%");
  await page.locator("#compare-button").hover();
  await page.mouse.down();
  await page.waitForFunction(
    () => document.getElementById("zoom").textContent !== "100%",
  );
  await page.mouse.up();
  assert.equal(await page.locator("#zoom").textContent(), "100%");
  await page.locator("#undo-button").click();
  await page.waitForFunction(
    async (url) => (await (await fetch(url)).json()).current.format !== "WEBP",
    route,
  );
  await page.locator("#redo-button").click();
  await waitText("current-info", "WEBP");
  await page.locator("#theme-button").click();
  await shot("dark");
  await page.locator("#theme-button").click();
  await select("crop");
  assert.equal(await page.locator("#new-template").count(), 0);
  for (const path of ["/api/config", "/api/templates", "/api/preferences"]) {
    assert.equal((await context.request.get(base + path)).status(), 404);
  }
  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  mobile.on("pageerror", (e) => errors.push(e.message));
  await mobile.goto(base);
  await mobile.waitForFunction(() =>
    document.getElementById("status").textContent.includes("服务已连接"),
  );
  assert.ok(
    await mobile.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "mobile layout must not overflow",
  );
  await mobile.screenshot({ path: join(folder, "mobile.png"), fullPage: true });
  await mobile.close();
  assert.deepEqual(errors, []);
  console.log(
    `PHOTOCRAFT_BROWSER_SMOKE_OK (${browserName}): crop, validation, drafts, colors, enhancement, brush, compression, download, compare, history, restricted configuration, mobile`,
  );
} catch (error) {
  await shot("failure");
  console.error(await page.locator("#status").textContent());
  throw error;
} finally {
  if (sid) await context.request.post(base + "/api/sessions/" + sid + "/close");
  await browser.close();
}
