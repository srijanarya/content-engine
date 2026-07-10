# X account switching / session repair — runbook (model-agnostic)

Written 2026-07-10 after the treum-lane incident. Binds any model or human operating the X
automation Chrome profiles. The tools referenced live in this directory.

## Profile map (verify before trusting — sessions drift)

| Workspace | Profile dir | CDP port | Expected handle |
|---|---|---|---|
| default / finance lanes | `~/.chrome-automation` | 9222 | @aryasrijan |
| ai channel cross-post | `~/.chrome-automation-ai` | 9331 | @aryasrijan |
| treum earnings lane | `~/.chrome-automation-treum` | 9332 | @TreumAlgotech |

`post_x.py` has **no expected-handle guard** — it posts as whatever session is active. Always
check identity before lifting any kill switch:

```sh
CHROME_AUTOMATION_PROFILE=<profile> CDP_PORT=<port> node x_browser.mjs verify-login
```

## Switch the active account (session already in the profile)

```sh
CDP_PORT=<port> node switch_account.mjs <handle>
```

JSON out. `{"ok":false,"error":"no session for @<handle>..."}` means the account was never
logged in (or its session was lost) → go to "Fresh login" below. The `menu` field in that
error lists what IS logged in.

## Fresh login (the only human step)

No X passwords are stored on this machine (.env files, ~/.zshrc.local, Keychain — all checked
2026-07-10). A model cannot complete this alone; it prepares, the human types:

1. Kill the headless instance **gracefully** (plain `pkill -f <profile-dir>`, never `-9`).
2. Relaunch headed:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=<profile> --remote-debugging-port=<port> --no-first-run --no-default-browser-check --hide-crash-restore-bubble "https://x.com/home"`
3. Drive over CDP: sidebar account switcher (`[data-testid="SideNav_AccountSwitcher_Button"]`)
   → `AccountSwitcher_AddAccount_Button` → the human enters credentials.
4. `verify-login` until it returns the expected handle.
5. Close gracefully, relaunch headless via `launch_chrome.sh`, verify again, THEN lift kill
   switches.

## Hard-won rules (each cost an incident on 2026-07-10)

- **Never SIGKILL an automation Chrome right after a login.** `pkill -9` before Chrome flushes
  cookies destroys the fresh session (a just-completed @TreumAlgotech login was lost this way).
  SIGTERM, wait, then relaunch.
- **Killswitch semantics:** `POSTING_DISABLED` (this dir) halts EVERY X lane — it is what
  `post_x` writes on a login/challenge (`halt_fleet`). `POSTING_DISABLED-<account>` halts one
  account (checked by post_x.py only, not by x_browser.mjs). To unblock healthy lanes while one
  account is broken: create the per-account switch first, then remove the fleet one.
- **"unknown error" from cross_post.py usually means the fleet killswitch**, not auth —
  x_browser returns `{ok:false, halt:true, reason:"killswitch"}` and cross_post only reads the
  `error` key. Check for POSTING_DISABLED before debugging tokens.
- **Headless viewport hides the switcher** — X collapses the SideNav below ~1000px wide; set
  the viewport to 1366x900 before waiting for `SideNav_AccountSwitcher_Button`.
- **Playwright CDP-attach crash on profiles with extensions** (seen on 9222: adblock service
  worker trips the career-ops playwright-core bundle). Workaround: raw CDP via Node's built-in
  WebSocket (`GET /json` → connect page target's webSocketDebuggerUrl), or keep automation
  profiles extension-free.
- **Identity guard:** a headed login window may end up signed into the WRONG account (it
  happened: the treum window got @aryasrijan). Verify the handle string, not just `ok:true`,
  before unpausing a lane.
