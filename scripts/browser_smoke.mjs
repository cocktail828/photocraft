// End-to-end checks of the real browser workspace; screenshots come from the running app.
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { chromium, firefox, webkit } from "playwright";
import { checkMobile } from "./mobile_smoke.mjs";
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
  assert.equal(await page.locator('[data-tool="background"]').count(), 0);
  await page.evaluate(async () => {
    const { EditorCanvas } = await import("/static/canvas.js");
    const source = document.createElement("canvas");
    source.width = source.height = 100;
    source.getContext("2d").fillStyle = "#ffffff";
    source.getContext("2d").fillRect(0, 0, 100, 100);
    const image = new Image();
    image.src = source.toDataURL();
    await image.decode();
    for (const erase of [false, true]) {
      const editor = Object.create(EditorCanvas.prototype);
      Object.assign(editor, { image, width: 100, height: 100, tool: "brush", drag: {
        type: "stroke", points: [[20, 20]], brush: { size: 10, opacity: 0.5, color: "#0000ff", erase },
      }});
      editor.paintLocal();
      const surface = editor.localImage;
      const pixel = () => Array.from(surface.getContext("2d").getImageData(20, 20, 1, 1).data);
      const first = pixel();
      editor.drag.points.push([50, 20], [20, 20]);
      editor.paintLocal();
      if (surface !== editor.localImage || first.join() !== pixel().join())
        throw new Error("Incremental strokes must reuse their surface and preserve opacity at overlaps");
      const untouched = surface.getContext("2d").getImageData(90, 90, 1, 1).data;
      if (untouched[0] !== 255 || untouched[3] !== 255)
        throw new Error("Stroke redraw must preserve untouched pixels");
    }
  });

  await shot("welcome");
  const demoResponse = page.waitForResponse(
    (r) => r.url().endsWith("/api/demo") && r.status() === 201,
  );
  await page.locator("#demo-button").click();
  sid = (await (await demoResponse).json()).id;
  const route = base + "/api/sessions/" + sid;
  const state = async () => context.request.get(route).then((r) => r.json());
  const waitCurrent = (key, value) => page.waitForFunction(
    async ({ route, key, value }) => (await (await fetch(route)).json()).current[key] === value,
    { route, key, value },
  );
  const waitApply = (disabled) => page.waitForFunction(
    (disabled) => document.getElementById("apply-button").disabled === disabled &&
      !document.body.classList.contains("busy"),
    disabled,
  );
  const payload = async () =>
    context.request.get(route + "/download").then((r) => r.body());
  const original = await payload();
  await waitText("preview-info", "295 × 413");
  await shot("crop");
  await page.locator("#apply-button").click();
  await waitCurrent("width", 295);
  await page.locator('[popovertarget="crop-preset-popover"]').click();
  await page.locator("#crop-mode").selectOption("t:1");
  await waitText("preview-info", "允许缩放");
  await page.locator("#apply-button").click();
  await page.locator("#error-dialog").waitFor({ state: "visible" });
  assert.match(await page.locator("#error-message").textContent(), /允许缩放/);
  assert.equal((await state()).current.width, 295);
  await page.locator("#error-dialog .primary").click();
  await page.locator("#undo-button").click();
  await waitCurrent("width", 720);
  assert.deepEqual(await payload(), original);
  await select("crop");
  await page.locator('[popovertarget="crop-preset-popover"]').click();
  await page.locator("#crop-mode").selectOption("custom");
  assert.equal(await page.locator('[data-field="ratio_w"]').inputValue(), "16");
  assert.equal(await page.locator('[data-field="ratio_h"]').inputValue(), "9");
  await waitApply(false);
  await shot("crop-ratio");
  await select("watermark");
  await page.locator('[popovertarget="watermark-text-popover"]').click();
  await page.locator("#mark-text").fill("仅用于资料审核");
  await page.keyboard.press("Escape");
  await page.locator('[popovertarget="watermark-style-popover"]').click();
  assert.equal(await page.locator(".watermark-colors .swatch").count(), 16);
  await page.locator('[data-watermark-swatch="#ef4444"]').click();
  assert.equal(await page.locator("#watermark-color").inputValue(), "#ef4444");
  assert.equal(await page.locator('.watermark-colors .brush-color-hex').inputValue(), "#ef4444");
  assert.equal(await page.locator('[data-watermark-swatch][aria-pressed="true"]').getAttribute("data-watermark-swatch"), "#ef4444");
  await shot("colors");
  await page.locator('.watermark-colors .brush-color-hex').fill("#64748b");
  assert.equal(await page.locator("#watermark-color").inputValue(), "#64748b");
  await page.keyboard.press("Escape");
  await waitApply(false);
  await page.waitForFunction(() => !document.body.classList.contains("busy"));
  await page.waitForTimeout(350);
  await shot("watermark");
  assert.deepEqual(
    await payload(),
    original,
    "watermark draft must never enter saved pixels",
  );
  await page.locator("#apply-button").click();
  await waitApply(true);
  assert.notDeepEqual(await payload(), original);
  await select("enhance");
  assert.equal(await page.locator("#properties").isVisible(), false);
  assert.equal(await page.locator("#effect-controls").isVisible(), true);
  await page.locator('[popovertarget="adjust-light-popover"]').click();
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
  assert.equal(await page.locator("#properties").isVisible(), false);
  assert.equal(await page.locator("#stroke-controls").isVisible(), true);
  const strokeArea = await page.locator("#stroke-controls").boundingBox();
  const photoArea = await page.locator("#editor-canvas").boundingBox();
  assert.ok(strokeArea.y >= photoArea.y + photoArea.height - 1, "Brush controls must sit below the photo");
  assert.equal(await page.locator('#stroke-controls input[type="range"]:visible').count(), 0);
  await page.locator('[popovertarget="stroke-paint-popover"]').click();
  await page.locator('#stroke-paint-popover:popover-open').waitFor();
  await page.locator('#stroke-paint-popover [data-field="size"]').evaluate(el => {
    el.value = '42'; el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  assert.equal(await page.locator('#stroke-paint-popover .range-value').first().textContent(), '42 px');
  await page.locator('[popovertarget="stroke-erase-popover"]').click();
  assert.equal(await page.locator('.stroke-parameter-popover:popover-open').count(), 1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.stroke-parameter-popover:popover-open').count(), 0);
  await page.locator('[popovertarget="stroke-paint-popover"]').click();
  await page.keyboard.press('Escape');
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
  await waitCurrent("format", "WEBP");
  assert.equal((await state()).current.quality, 45);
  const compressed = await payload();
  assert.notDeepEqual(compressed, beforeCompress);
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#save-button").click();
  await page.locator("#save-default").click();
  const downloaded = await downloadEvent;
  assert.ok(downloaded.suggestedFilename().endsWith(".webp"));
  assert.deepEqual(await readFile(await downloaded.path()), compressed);
  await page.locator("#view-size-button").click();
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
  await waitCurrent("format", "WEBP");
  await page.locator("#theme-button").click();
  await shot("dark");
  await page.locator("#theme-button").click();
  await select("crop");
  assert.equal(await page.locator("#new-template").count(), 0);
  for (const path of ["/api/config", "/api/templates", "/api/preferences"]) {
    assert.equal((await context.request.get(base + path)).status(), 404);
  }
  await checkMobile(browser, base, folder, errors);
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
