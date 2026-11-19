// Run against an isolated frontend with a screenshot destination.
const assert = require("node:assert/strict");
const path = require("node:path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function run() {
  const [url, screenshot] = process.argv.slice(2);
  const browser = await chromium.launch({ channel: "msedge" });
  try {
    for (const colorScheme of ["light", "dark"]) {
      const page = await browser.newPage({ colorScheme, viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
      await page.goto(url);
      const actions = page.locator(".hdde-topbar-actions");
      const guide = actions.locator(".hdde-guide-trigger");
      const feedback = actions.locator('[data-testid="global-feedback-trigger"]');
      await guide.waitFor();
      await page.locator(".hdde-startup-splash").waitFor({ state: "hidden" });
      const outline = (button) => button.evaluate((el) => {
        const css = getComputedStyle(el);
        // Chromium can report a nonzero width even for outline-style: none.
        const width = css.outlineStyle === "none" ? 0 : parseFloat(css.outlineWidth);
        return { width, offset: parseFloat(css.outlineOffset) };
      });
      await guide.hover();
      if (colorScheme === "light") {
        const box = await actions.boundingBox();
        await page.screenshot({ path: path.resolve(screenshot), clip: {
          x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 12,
        } });
      }
      for (const button of [guide, feedback]) {
        await button.hover();
        assert.equal((await outline(button)).width, 0, "Hover should not draw an outer outline");
      }
      await guide.click();
      await page.locator(".hdde-guide-panel[open]").waitFor();
      await page.keyboard.press("Escape");
      await page.locator(".hdde-guide-panel[open]").waitFor({ state: "hidden" });
      await page.mouse.move(0, 0);
      for (const [key, button] of [["Tab", feedback], ["Shift+Tab", guide]]) {
        await page.keyboard.press(key);
        assert.ok(await button.evaluate((el) => el.matches(":focus-visible")));
        const { width, offset } = await outline(button);
        assert.ok(width >= 2 && width + offset <= 0, "Keyboard focus must remain visible within the button");
      }
      await page.close();
    }
  } finally {
    await browser.close();
  }
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
