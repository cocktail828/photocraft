import assert from "node:assert/strict";
import { join } from "node:path";

// Exercise loaded images and parameter popovers, not just the welcome screen.
export async function checkMobile(browser, base, folder, errors) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, hasTouch: true, acceptDownloads: true,
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  let route;
  const settle = () => page.evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const select = async tool => {
    await page.locator(`[data-tool="${tool}"]`).tap();
    await settle();
  };
  const checkLayout = async label => {
    const issues = await page.evaluate(() => {
      const issues = [];
      if (document.documentElement.scrollWidth > innerWidth) issues.push("page overflows horizontally");
      if (innerHeight > 700 && document.documentElement.scrollHeight > innerHeight + 1)
        issues.push("tall phone layout scrolls out of the viewport");
      const canvas = document.getElementById("canvas-area").getBoundingClientRect();
      if (canvas.height < 159) issues.push(`canvas too short: ${canvas.height}`);
      const nav = document.getElementById("tools");
      const tools = Array.from(nav.children, el => el.getBoundingClientRect());
      if (tools.some(rect => Math.abs(rect.top - tools[0].top) > 1)) issues.push("tools must stay in one row");
      if (innerWidth <= 430 && nav.scrollWidth <= nav.clientWidth) issues.push("tool row must scroll horizontally");
      if (document.querySelector(".sidebar").getBoundingClientRect().top <
          document.querySelector(".workspace").getBoundingClientRect().bottom - 1)
        issues.push("tool row must sit below the workspace");
      for (const group of document.querySelectorAll(".stroke-fields, .filter-bottom-row")) {
        if (!group.checkVisibility()) continue;
        const rows = new Map();
        for (const el of group.children) {
          if (!el.checkVisibility()) continue;
          const rect = el.getBoundingClientRect();
          const key = Math.round(rect.top);
          rows.set(key, [...(rows.get(key) || []), rect]);
        }
        const parent = group.getBoundingClientRect();
        for (const row of rows.values()) {
          const middle = (Math.min(...row.map(r => r.left)) + Math.max(...row.map(r => r.right))) / 2;
          if (Math.abs(middle - (parent.left + parent.width / 2)) > 1) issues.push("parameter rows must be centered");
        }
      }
      const controls = Array.from(document.querySelectorAll(
        ".workspace-toolbar button, .sidebar button, .geometry-controls button, .stroke-controls button, .effect-controls button"))
        .filter(el => el.checkVisibility() && !el.closest("[popover]"));
      for (const [i, el] of controls.entries()) {
        const a = el.getBoundingClientRect();
        if (!el.closest(".sidebar") && (a.left < -1 || a.right > innerWidth + 1))
          issues.push(`${el.id || el.textContent} outside screen`);
        if (a.height < 39) issues.push(`${el.id || el.textContent} too small for touch`);
        for (const other of controls.slice(i + 1)) {
          const b = other.getBoundingClientRect();
          if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
              Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)
            issues.push(`${el.id || el.textContent} overlaps ${other.id || other.textContent}`);
        }
      }
      return issues;
    });
    assert.deepEqual(issues, [], label);
  };
  try {
    await page.goto(base);
    await page.waitForFunction(() => document.getElementById("service-label").textContent.includes("已连接"));
    assert.equal(await page.locator("#checker, .checker-toggle").count(), 0);
    assert.equal(await page.locator("#compare-button").textContent().then(value => value.trim()), "查看原图");
    await page.screenshot({ path: join(folder, "mobile-welcome.png") });
    const response = page.waitForResponse(r => r.url().endsWith("/api/demo") && r.request().method() === "POST");
    await page.locator("#demo-button").tap();
    route = `/api/sessions/${(await (await response).json()).id}`;
    await page.locator("#editor-canvas").waitFor({ state: "visible" });
    await page.waitForFunction(() => !document.body.classList.contains("busy"));
    for (const [width, height] of [[390, 844], [320, 568], [360, 740], [430, 932], [720, 900], [844, 390]]) {
      await page.setViewportSize({ width, height });
      for (const tool of ["crop", "brush", "mosaic", "blur", "enhance", "filters", "watermark", "compress"]) {
        await select(tool);
        await checkLayout(`${width}x${height} ${tool}`);
        const targets = await page.locator(".stroke-parameter-trigger:visible").evaluateAll(elements =>
          elements.map(el => el.getAttribute("popovertarget")));
        for (const target of targets) {
          await page.locator(`[popovertarget="${target}"]`).tap();
          const popover = page.locator(`#${target}:popover-open`);
          await popover.waitFor();
          await settle();
          const bounds = await popover.boundingBox();
          assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= width + 1 &&
            bounds.y + bounds.height <= height + 1, `${width}x${height} ${target} must fit on screen`);
          const done = popover.locator(".mobile-popover-header button");
          await done.tap();
          assert.equal(await page.locator(".stroke-parameter-popover:popover-open").count(), 0);
        }
        if (width === 390) {
          await page.screenshot({ path: join(folder, `mobile-${tool}.png`) });
        }
      }
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await select("brush");
    const before = await context.request.get(base + route).then(r => r.json());
    const canvas = await page.locator("#editor-canvas").boundingBox();
    await page.touchscreen.tap(canvas.x + canvas.width / 2, canvas.y + canvas.height / 2);
    await page.waitForFunction(async ({ route, revision }) =>
      (await (await fetch(route)).json()).revision > revision, { route, revision: before.revision });
    await select("compress");
    await page.locator('[data-field="format"]').selectOption("WEBP");
    await page.waitForFunction(() => document.getElementById("preview-info").textContent.includes("WEBP") &&
      !document.getElementById("apply-button").disabled);
    await page.locator("#apply-button").tap();
    await page.waitForFunction(async route =>
      (await (await fetch(route)).json()).current.format === "WEBP", route);
    await page.locator("#properties details summary").tap();
    await page.locator(".color-trigger").tap();
    await page.locator("#color-dialog").waitFor({ state: "visible" });
    const dialog = await page.locator("#color-dialog").boundingBox();
    assert.ok(dialog.y >= 0 && dialog.y + dialog.height <= 845, "mobile color dialog fits");
    await page.locator("#color-dialog .dialog-close").first().tap();
    const download = page.waitForEvent("download");
    await page.locator("#save-button").tap();
    await page.locator("#save-default").tap();
    assert.ok((await download).suggestedFilename().endsWith(".webp"));
    await page.locator("#theme-button").tap();
    await page.screenshot({ path: join(folder, "mobile-dark.png") });
    console.log("PHOTOCRAFT_MOBILE_SMOKE_OK: six viewports, eight tools, popovers, touch drawing, compression, download, color dialog");
  } catch (error) {
    await page.screenshot({ path: join(folder, "mobile-failure.png") });
    throw error;
  } finally {
    if (route) await context.request.post(base + route + "/close");
    await context.close();
  }
}
