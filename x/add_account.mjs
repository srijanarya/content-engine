#!/usr/bin/env node
// Add an existing X account to an automation Chrome profile by driving the login form, reading the
// password from macOS Keychain (never a flag, never a file). Model-agnostic self-serve fresh login.
//
//   store once:  security add-generic-password -s x-treum -a TreumAlgotech -w
//   run:         CDP_PORT=9332 node add_account.mjs --keychain x-treum --account TreumAlgotech
//
// Prints {"ok":true,"handle":...} once the new account is active. If X raises a challenge it cannot
// answer headlessly (OTP / email code), it prints {"ok":false,"reason":"challenge",...} and leaves the
// headed window on that step for a human — it never guesses a code.
import { execFileSync } from "node:child_process";

const PW_PATH = process.env.PLAYWRIGHT_MODULE || "/Users/srijan/career-ops/node_modules/playwright/index.mjs";
const PORT = process.env.CDP_PORT || "9222";
const args = process.argv.slice(2);
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : null; };
const service = opt("--keychain");
const account = opt("--account");           // the X handle to end up active
const identifier = opt("--identifier") || account;  // what to type in the username field
if (!service || !account) { console.log(JSON.stringify({ ok: false, error: "usage: --keychain <service> --account <handle> [--identifier <login>]" })); process.exit(1); }

let password;
try {
  password = execFileSync("security", ["find-generic-password", "-s", service, "-w"], { encoding: "utf8" }).trim();
} catch { console.log(JSON.stringify({ ok: false, error: `no keychain item for service '${service}'` })); process.exit(1); }
if (!password) { console.log(JSON.stringify({ ok: false, error: "empty keychain password" })); process.exit(1); }

const { chromium } = await import(PW_PATH);
const b = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
// Real keystrokes: X's jf-form inputs are React-controlled; fill()/force bypasses the input events
// React needs, so the form submits empty. focus + pressSequentially updates component state properly.
const type = async (page, sel, val) => {
  const el = page.locator(sel).first();
  await el.scrollIntoViewIfNeeded().catch(() => {});
  await el.click({ force: true }).catch(() => el.focus());
  await el.pressSequentially(val, { delay: 30 });
};
try {
  const ctx = b.contexts()[0];
  let page = ctx.pages().find((p) => p.url().includes("x.com")) || (await ctx.newPage());
  await page.setViewportSize({ width: 1366, height: 900 });

  // already logged in somewhere? open the switcher's Add-account; else go straight to the login flow.
  await page.goto("https://x.com/home", { waitUntil: "domcontentloaded" }).catch(() => {});
  const switcher = page.locator('[data-testid="SideNav_AccountSwitcher_Button"]');
  if (await switcher.count().catch(() => 0)) {
    // already active as the target? nothing to do.
    const cur = (await switcher.innerText().catch(() => "")).match(/@(\w+)/)?.[1];
    if (cur && cur.toLowerCase() === account.toLowerCase()) { console.log(JSON.stringify({ ok: true, handle: cur, note: "already_active" })); process.exit(0); }
    await switcher.click();
    await page.waitForTimeout(1200);
    const alt = page.locator('[data-testid="UserCell"]', { hasText: new RegExp(`@${account}`, "i") }).first();
    if (await alt.count()) { await alt.click(); await page.waitForTimeout(3500); const h = (await switcher.innerText()).match(/@(\w+)/)?.[1]; console.log(JSON.stringify({ ok: h?.toLowerCase() === account.toLowerCase(), handle: h, note: "existing_session" })); process.exit(0); }
    await page.locator('[data-testid="AccountSwitcher_AddAccount_Button"]').click();
  } else {
    await page.goto("https://x.com/i/flow/login", { waitUntil: "domcontentloaded" });
  }

  // The "Add an existing account" jf-form (onboarding/web) is a multi-step wizard, but it preloads
  // BOTH username_or_email and password inputs into the DOM at once — so an isVisible() check is
  // useless. The reliable path: type the identifier, press Enter to advance to the enter-password
  // step, type the password on that step, click the (testid-less) Continue button, Enter as fallback.
  const USER_SEL = 'input[name="username_or_email"], input[autocomplete="username"], input[name="text"]';
  const PASS_SEL = 'input[name="password"], input[autocomplete="current-password"]';
  await page.waitForSelector(USER_SEL, { timeout: 30000 });
  const userEl = page.locator(USER_SEL).first();
  await userEl.click({ force: true }).catch(() => userEl.focus());
  await userEl.pressSequentially(identifier, { delay: 30 });
  await userEl.press("Enter");
  await page.waitForTimeout(1800);

  // unusual-activity interstitial: X re-asks for the handle before the password step
  const ocf = page.locator('[data-testid="ocfEnterTextTextInput"]');
  if (await ocf.count().catch(() => 0)) { await ocf.fill(account); await page.getByRole("button", { name: /^Next$/ }).click().catch(() => {}); await page.waitForTimeout(1500); }

  await page.waitForSelector(PASS_SEL, { timeout: 20000 });
  await type(page, PASS_SEL, password);
  await page.waitForTimeout(300);
  const submitted = await page.getByRole("button", { name: /^Continue$|^Log in$/ }).first().click({ timeout: 5000 }).then(() => true).catch(() => false);
  if (!submitted) await page.locator(PASS_SEL).first().press("Enter");
  await page.waitForTimeout(5000);

  // inline validation error (wrong password / rate limit) — surface it, don't silently claim failure.
  const errText = await page.evaluate(() => {
    const e = [...document.querySelectorAll('[role="alert"], .jf-error, [data-testid*="rror"]')].map(n => n.innerText).filter(Boolean);
    return e.join(" | ").slice(0, 200);
  }).catch(() => "");
  if (errText) { console.log(JSON.stringify({ ok: false, reason: "form_error", detail: errText })); process.exit(1); }

  // challenge? (email/OTP verification) — bail to human, do NOT guess.
  const challenge = await page.locator('[data-testid="ocfEnterTextTextInput"], input[name="verfication_code"], input[data-testid="LoginVerificationCodeForm"]').count().catch(() => 0);
  const url = page.url();
  if (challenge || /login_challenge|verification|account_access/.test(url)) {
    console.log(JSON.stringify({ ok: false, reason: "challenge", detail: "OTP/verification required — headed window left on this step for a human", url }));
    process.exit(2);
  }

  // confirm
  await page.goto("https://x.com/home", { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForSelector('[data-testid="SideNav_AccountSwitcher_Button"]', { timeout: 20000 });
  const handle = (await page.locator('[data-testid="SideNav_AccountSwitcher_Button"]').innerText()).match(/@(\w+)/)?.[1] || "?";
  const ok = handle.toLowerCase() === account.toLowerCase();
  console.log(JSON.stringify({ ok, handle }));
  process.exit(ok ? 0 : 1);
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: String(e.message || e).slice(0, 300) }));
  process.exit(1);
} finally {
  await b.close().catch(() => {});
}
