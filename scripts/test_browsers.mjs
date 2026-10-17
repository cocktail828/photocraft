import { spawnSync } from "node:child_process";
import { join } from "node:path";

const browsers = (
  process.env.PHOTOCRAFT_BROWSERS || "chromium,firefox,webkit"
).split(",");
const folder = process.env.PHOTOCRAFT_SCREENSHOT_DIR || "artifacts/web-ui";
for (const name of browsers) {
  const result = spawnSync(process.execPath, ["scripts/browser_smoke.mjs"], {
    stdio: "inherit",
    env: {
      ...process.env,
      PHOTOCRAFT_BROWSER: name.trim(),
      PHOTOCRAFT_SCREENSHOT_DIR:
        name.trim() === "chromium" ? folder : join(folder, name.trim()),
    },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
