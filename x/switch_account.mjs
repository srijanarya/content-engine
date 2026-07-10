#!/usr/bin/env node
// Switch the ACTIVE X account in an automation Chrome profile (multi-login must already exist —
// this clicks the sidebar account switcher; it never enters credentials).
//   CHROME_AUTOMATION_PROFILE=~/.chrome-automation-treum CDP_PORT=9332 node switch_account.mjs TreumAlgotech
// Prints {"ok":true,"handle":...} on success; {"ok":false,...} if the target account has no session
// in this profile (fix: headed Chrome → account switcher → "Add an existing account" → human login).
const PW_PATH = process.env.PLAYWRIGHT_MODULE || "/Users/srijan/career-ops/node_modules/playwright/index.mjs";
const PORT = process.env.CDP_PORT || "9222";
const target = process.argv[2];
if (!target) { console.log(JSON.stringify({ ok: false, error: "usage: switch_account.mjs <handle>" })); process.exit(1); }

const { chromium } = await import(PW_PATH);
const b = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
try {
  const ctx = b.contexts()[0];
  let page = ctx.pages().find((p) => p.url().includes("x.com")) || (await ctx.newPage());
  await page.setViewportSize({ width: 1366, height: 900 }); // headless default is too narrow — SideNav hides
  await page.goto("https://x.com/home", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('[data-testid="SideNav_AccountSwitcher_Button"]', { timeout: 30000 });
  const current = await page
    .locator('[data-testid="SideNav_AccountSwitcher_Button"]')
    .innerText()
    .then((t) => (t.match(/@(\w+)/) || [])[1] || null)
    .catch(() => null);
  if (current && current.toLowerCase() === target.toLowerCase()) {
    console.log(JSON.stringify({ ok: true, handle: current, note: "already_active" }));
    process.exit(0);
  }
  await page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').click();
  await page.waitForTimeout(1500);
  // logged-in alternates appear as UserCells inside the switcher menu (follow-suggestion UserCells
  // elsewhere in the DOM say "Follow" — the hasText filter on the handle keeps us on the right one)
  const cell = page.locator(`[data-testid="UserCell"]`, { hasText: new RegExp(`@${target}`, "i") }).first();
  if (!(await cell.count())) {
    const items = await page.evaluate(() =>
      [...document.querySelectorAll('[role="menuitem"]')].map((e) => e.innerText.replace(/\n/g, " ").slice(0, 60)));
    console.log(JSON.stringify({ ok: false, error: `no session for @${target} in this profile`, menu: items }));
    process.exit(1);
  }
  await cell.click();
  await page.waitForTimeout(4000);
  const after = await page
    .locator('[data-testid="SideNav_AccountSwitcher_Button"]')
    .innerText()
    .then((t) => (t.match(/@(\w+)/) || [])[1] || "?");
  const ok = after.toLowerCase() === target.toLowerCase();
  console.log(JSON.stringify({ ok, handle: after }));
  process.exit(ok ? 0 : 1);
} finally {
  await b.close();
}
