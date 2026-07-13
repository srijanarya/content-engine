#!/usr/bin/env python3
"""Earnings filing ingester + deterministic draft generator for @TreumAlgotech.

Pipeline:
  results-season guard
  → poll NSE corporates-financial-results for each watchlist symbol, filter to today's broadCastDate
  → fetch + parse XBRL numbers (consolidated preferred over standalone)
  → upsert to data/earnings_history.db (INSERT OR REPLACE, idempotent)
  → compute YoY (4-quarter-prior) and QoQ (1-quarter-prior) deltas from DB
  → render NUMBERS-ONLY draft (no sentiment, no adjective, no verdict)
  → hard lint gate (a BLOCK is a bug; raise loudly, do not write)
  → write slugged .md with engine: earnings, status: needs-review

--backfill SYMBOL: fetch and upsert ~8 prior quarters for YoY/QoQ cold-start.
--date YYYY-MM-DD:  run for a specific date (default: today IST).
--dry-run:          print draft, do not write to disk.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, tempfile, time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
AKSH = Path(os.environ.get("AKSH_DIR", "/Users/srijan/aksh_backtesting_trading"))
sys.path.insert(0, str(AKSH))

IST = timezone(timedelta(hours=5, minutes=30))

# Per-run NSE call cap: guards against hammering on a bad NSE day.
# Each symbol makes ~2 NSE calls (results list + XBRL download); cap at 150 for a ~75-symbol run.
# ponytail: global counter per run; per-symbol counters only if throughput matters
NSE_RUN_CAP = 150

UNIVERSE_FILE = Path(__file__).parent / "earnings_universe.txt"
DB_PATH = ENGINE_DIR / "data" / "earnings_history.db"
DRAFTS   = ENGINE_DIR / "drafts"
HEALTH_FILE = ENGINE_DIR / "x" / "earnings_lane_health.json"
LIVE_FLAG = ENGINE_DIR / "x" / "EARNINGS_TREUM_LIVE"

DISCLAIMER = ("Data & language analysis, educational only. Not investment advice; "
              "no buy/sell/hold. Not a SEBI-registered analyst.")

NSE_RESULTS_PAGE = ("https://www.nseindia.com/companies-listing/"
                    "corporate-filings-financial-results")

# ─── DB ──────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS earnings_quarters (
    symbol       TEXT,
    period_end   TEXT,
    fiscal_label TEXT,
    consolidated INTEGER,
    revenue_cr   REAL,
    ebitda_cr    REAL,
    opm_pct      REAL,
    pbt_cr       REAL,
    pat_cr       REAL,
    eps          REAL,
    source       TEXT,
    xbrl_url     TEXT,
    verified     INTEGER DEFAULT 0,
    fetched_at   TEXT,
    PRIMARY KEY (symbol, period_end, consolidated)
)
"""


def _open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL)
    conn.commit()
    return conn


def _upsert(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO earnings_quarters
          (symbol, period_end, fiscal_label, consolidated,
           revenue_cr, ebitda_cr, opm_pct, pbt_cr, pat_cr, eps,
           source, xbrl_url, verified, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["symbol"], row["period_end"], row["fiscal_label"], row["consolidated"],
        row.get("revenue_cr"), row.get("ebitda_cr"), row.get("opm_pct"),
        row.get("pbt_cr"), row.get("pat_cr"), row.get("eps"),
        row.get("source", "xbrl"), row.get("xbrl_url"), row.get("verified", 0),
        row.get("fetched_at", datetime.now(IST).isoformat()),
    ))
    conn.commit()


def _get_prev(conn: sqlite3.Connection, symbol: str, period_end: str,
              consolidated: int, offset: int) -> Optional[sqlite3.Row]:
    """Prior quarter: offset=1 → QoQ, offset=4 → YoY."""
    rows = conn.execute("""
        SELECT * FROM earnings_quarters
        WHERE symbol=? AND consolidated=? AND period_end < ?
        ORDER BY period_end DESC
    """, (symbol, consolidated, period_end)).fetchall()
    return rows[offset - 1] if len(rows) >= offset else None


# ─── dates + labels ──────────────────────────────────────────────────────────

def _parse_nse_date(s: str) -> Optional[date]:
    """Parse '31-Dec-2024' or '09-Jan-2025 21:39:43' → date."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip().split()[0], "%d-%b-%Y").date()
    except ValueError:
        return None


def _fiscal_label(period_end: date) -> str:
    m, y = period_end.month, period_end.year
    if m in (4, 5, 6):
        return f"Q1FY{(y + 1) % 100:02d}"
    elif m in (7, 8, 9):
        return f"Q2FY{(y + 1) % 100:02d}"
    elif m in (10, 11, 12):
        return f"Q3FY{(y + 1) % 100:02d}"
    else:
        return f"Q4FY{y % 100:02d}"


def _period_str(period_end_iso: str) -> str:
    """'2024-12-31' → 'Oct-Dec 2024'"""
    d = date.fromisoformat(period_end_iso)
    m = d.month
    if m in (4, 5, 6):
        return f"Apr-Jun {d.year}"
    elif m in (7, 8, 9):
        return f"Jul-Sep {d.year}"
    elif m in (10, 11, 12):
        return f"Oct-Dec {d.year}"
    else:
        return f"Jan-Mar {d.year}"


# ─── season guard ────────────────────────────────────────────────────────────

# Results seasons: Q3 (Jan 10–Feb 28), Q4 (Apr 10–May 31), Q1 (Jul 10–Aug 31), Q2 (Oct 10–Nov 30).
# Off the other ~8 months → no-op so we don't poll NSE year-round.
_SEASON_MONTHS = {
    1: 10, 2: 1, 4: 10, 5: 1, 7: 10, 8: 1, 10: 10, 11: 1,
    # key=month, value=start_day (1 = entire month; 10 = from 10th onward)
}


def in_results_season(today: Optional[date] = None) -> bool:
    """True during the four Indian results seasons (mid-Jan/Apr/Jul/Oct through end of next month)."""
    if today is None:
        today = date.today()
    start_day = _SEASON_MONTHS.get(today.month)
    if start_day is None:
        return False
    return today.day >= start_day


# ─── NSE fetch ───────────────────────────────────────────────────────────────

def _load_universe() -> list[str]:
    return [l.strip() for l in UNIVERSE_FILE.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def _screener_key_metrics(symbol: str) -> Optional[dict]:
    """Best-effort: fetch Screener.in consolidated quarterly data for `symbol`.
    Returns {'revenue_cr': float|None, 'pat_cr': float|None} for the most recent quarter,
    or None on any failure. Fail-closed: login required / network error / parse miss → None.
    """
    try:
        import requests as _r
        s = _r.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 (compatible; content-engine/1.0)"
        resp = s.get(f"https://www.screener.in/company/{symbol}/consolidated/", timeout=10)
        if resp.status_code != 200:
            return None
        html = resp.text
        # Screener quarterly table: label td then first value td per row.
        # ponytail: simple regex; no BeautifulSoup dependency; fails gracefully on structure changes.
        def _first_td_val(label: str) -> Optional[float]:
            m = re.search(
                rf'<td[^>]*class="[^"]*text[^"]*"[^>]*>\s*{re.escape(label)}\s*</td>\s*<td[^>]*>([\d,]+(?:\.\d+)?)</td>',
                html, re.IGNORECASE,
            )
            return float(m.group(1).replace(",", "")) if m else None
        rev = _first_td_val("Sales") or _first_td_val("Revenue")
        pat = _first_td_val("Net Profit") or _first_td_val("PAT")
        if rev is None and pat is None:
            return None
        return {"revenue_cr": rev, "pat_cr": pat}
    except Exception:
        return None


def _try_cross_validate(symbol: str, xbrl_metrics: dict, fetcher) -> int:
    """Cross-validate XBRL numbers against Screener.in. Returns 1 (verified) or 0 (fail-closed).

    verified=1 only when Screener agrees within tolerance (VERIFIED or MINOR_DIFF).
    Any failure — unavailable second source, SUSPICIOUS diff, exception — returns 0.
    """
    try:
        from services.nse_xbrl_fetcher import cross_validate
        screener_vals = _screener_key_metrics(symbol)
        if not screener_vals:
            print(f"  {symbol}: Screener unavailable — verified=0 (fail-closed)", file=sys.stderr)
            return 0
        result = cross_validate(xbrl_metrics, screener_vals, symbol=symbol)
        if result.status in ("VERIFIED", "MINOR_DIFF"):
            return 1
        print(
            f"  {symbol}: cross-validate {result.status} "
            f"(max_diff={result.max_diff_pct:.1f}%) — verified=0",
            file=sys.stderr,
        )
        return 0
    except Exception as e:
        print(f"  {symbol}: cross-validate error — {e}; verified=0", file=sys.stderr)
        return 0


def _fetch_and_parse_filings(
    symbol: str,
    fresh_now: Optional[datetime] = None,
    fetcher=None,
    nse_calls: Optional[list] = None,
) -> list[dict]:
    """Return upsert-ready rows for `symbol`.

    fresh_now=None     → return ALL available quarterly filings (backfill mode).
    fresh_now=datetime → only filings that are FRESH relative to it (is_fresh: same-day, or a
      late-evening filing seen the next morning). This is why a morning run surfaces yesterday-late
      filings but still drops anything stale. Prefers Consolidated over Non-Consolidated per period.

    fetcher  → a shared NSEXbrlFetcher instance (created once per run by run_today / run_backfill).
               If None, one is created for this call only (backfill convenience).
    nse_calls → mutable [int] counter shared with run_today for the per-run cap.
    """
    from services.nse_xbrl_fetcher import NSEXbrlFetcher
    from compliance.earnings_check import is_fresh
    if fetcher is None:
        fetcher = NSEXbrlFetcher()  # caller didn't share one; isolated call (e.g. test)

    if nse_calls is not None:
        nse_calls[0] += 1   # count: fetch_financial_results
    filings = fetcher.fetch_financial_results(symbol, period="Quarterly")
    if not filings:
        return []

    rows: dict[tuple, dict] = {}   # (period_end_iso, consolidated) → row

    for fi in filings:
        if not fi.xbrl_url:
            continue
        if fresh_now is not None:
            ok, _why = is_fresh(fi.broad_cast_date or "", fresh_now)
            if not ok:
                continue
        period_d = _parse_nse_date(fi.period or "")
        if not period_d:
            continue
        # Use exact equality: "Non-Consolidated" contains "consolidated" as a substring
        # so substring check would incorrectly mark standalone filings as consolidated.
        raw_cons = (fi.raw.get("consolidated") or "").strip().lower()
        is_cons = 1 if raw_cons == "consolidated" else 0
        key = (period_d.isoformat(), is_cons)

        if nse_calls is not None:
            nse_calls[0] += 1  # count: download_xbrl
        content = fetcher.download_xbrl(fi.xbrl_url)
        if not content:
            print(f"  {symbol}: XBRL download failed for {fi.xbrl_url[:60]}", file=sys.stderr)
            continue
        metrics = fetcher.parse_xbrl(content)
        if not metrics:
            continue

        verified = _try_cross_validate(symbol, metrics, fetcher)

        rows[key] = {
            "symbol": symbol,
            "period_end": period_d.isoformat(),
            "fiscal_label": _fiscal_label(period_d),
            "consolidated": is_cons,
            "revenue_cr": metrics.get("revenue_cr"),
            "ebitda_cr": metrics.get("ebitda_cr"),
            "opm_pct": metrics.get("opm_pct"),
            "pbt_cr": metrics.get("pbt_cr"),
            "pat_cr": metrics.get("pat_cr"),
            "eps": metrics.get("eps"),
            "source": "xbrl",
            "xbrl_url": fi.xbrl_url,
            "verified": verified,
            "fetched_at": datetime.now(IST).isoformat(),
            "_bcast": fi.broad_cast_date or "",
        }

    return list(rows.values())


# ─── delta math ──────────────────────────────────────────────────────────────

def _pct_delta(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None or old == 0:
        return None
    return round(100.0 * (new - old) / abs(old), 1)


def _bps_delta(new: Optional[float], old: Optional[float]) -> Optional[float]:
    if new is None or old is None:
        return None
    return round((new - old) * 100, 0)   # OPM in %, bps = 100x pp difference


def _compute_deltas(conn: sqlite3.Connection, row: dict) -> dict:
    """Compute YoY (4Q) and QoQ (1Q) for revenue/ebitda/pbt/pat; bps for OPM."""
    sym, pe, cons = row["symbol"], row["period_end"], row["consolidated"]
    yoy = _get_prev(conn, sym, pe, cons, 4)
    qoq = _get_prev(conn, sym, pe, cons, 1)
    out: dict = {}
    for field in ("revenue_cr", "ebitda_cr", "pbt_cr", "pat_cr"):
        for kind, prev in (("yoy", yoy), ("qoq", qoq)):
            key = f"{kind}_{field.replace('_cr', '')}_pct"
            out[key] = _pct_delta(row.get(field), dict(prev)[field] if prev else None)
    # OPM in bps
    for kind, prev in (("yoy", yoy), ("qoq", qoq)):
        key = f"{kind}_opm_bps"
        out[key] = _bps_delta(row.get("opm_pct"), dict(prev)["opm_pct"] if prev else None)
    return out


# ─── thread builder ──────────────────────────────────────────────────────────

def _cr_str(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"₹{v:,.0f} cr"


def _delta_str(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    return f" ({pct:+.1f}%"


def _yoy_qoq(row: dict, field_stem: str) -> str:
    """'(+4.5% YoY, +1.2% QoQ)' or '(+4.5% YoY)' or ''"""
    yoy = row.get(f"yoy_{field_stem}_pct")
    qoq = row.get(f"qoq_{field_stem}_pct")
    if yoy is None and qoq is None:
        return ""
    if yoy is not None and qoq is not None:
        return f" ({yoy:+.1f}% YoY, {qoq:+.1f}% QoQ)"
    if yoy is not None:
        return f" ({yoy:+.1f}% YoY)"
    return f" ({qoq:+.1f}% QoQ)"


def _build_thread(row: dict, bcast_date: str) -> tuple[str, str]:
    """Return (newsletter_text, x_thread_text).

    FACTS ONLY — no adjective, no sentiment, no buy/sell/verdict.
    Numbers sourced exclusively from the XBRL filing.
    """
    sym        = row["symbol"]
    label      = row["fiscal_label"]
    cons_label = "Consolidated" if row["consolidated"] else "Standalone"
    period_s   = _period_str(row["period_end"])
    _bd = _parse_nse_date(bcast_date or "")
    bcast_s    = str(_bd) if _bd else ""   # YYYY-MM-DD from "09-Jan-2025 21:39:43"

    # crore values
    rev  = _cr_str(row.get("revenue_cr"))
    ebit = _cr_str(row.get("ebitda_cr"))
    pat  = _cr_str(row.get("pat_cr"))
    pbt  = _cr_str(row.get("pbt_cr"))
    opm  = f"{row['opm_pct']:.1f}%" if row.get("opm_pct") is not None else "N/A"
    eps  = f"{row['eps']:.2f}" if row.get("eps") is not None else "N/A"

    # deltas
    rev_delta  = _yoy_qoq(row, "revenue")
    ebit_delta = _yoy_qoq(row, "ebitda")
    pat_delta  = _yoy_qoq(row, "pat")
    pbt_delta  = _yoy_qoq(row, "pbt")

    t1 = (f"{sym} {label} ({cons_label}):\n"
          f"Revenue: {rev}{rev_delta}\n"
          f"EBITDA: {ebit}{ebit_delta} | OPM: {opm}")

    t2_lines = [f"PAT: {pat}{pat_delta}", f"EPS: {eps}", f"PBT: {pbt}{pbt_delta}"]
    t2 = "\n".join(t2_lines)

    t3 = (f"NSE filing: {NSE_RESULTS_PAGE}\n"
          f"Period: {period_s} | Broadcast: {bcast_s}\n"
          f"#{sym} #earnings #NSEIndia")

    thread = "\n\n".join(f"**{i}/**\n{t}" for i, t in enumerate([t1, t2, t3], 1))

    newsletter = (
        f"{sym} {label} ({cons_label}, {period_s}).\n\n"
        f"Revenue: {rev}{rev_delta}.\n"
        f"EBITDA: {ebit}{ebit_delta} | OPM: {opm}.\n"
        f"PAT: {pat}{pat_delta}. EPS: {eps}. PBT: {pbt}{pbt_delta}.\n\n"
        f"Source: NSE XBRL filing (broadcast {bcast_s}).\n"
        f"Period: {period_s}.\n\n"
        f"{DISCLAIMER}"
    )
    return newsletter, thread


def _build_record(row: dict, deltas: dict) -> dict:
    """Flat dict for the ## SOURCE block (what earnings_check re-derives against)."""
    return {
        "symbol": row["symbol"],
        "period_end": row["period_end"],
        "fiscal_label": row["fiscal_label"],
        "consolidated": row["consolidated"],
        "revenue_cr": row.get("revenue_cr"),
        "ebitda_cr": row.get("ebitda_cr"),
        "opm_pct": row.get("opm_pct"),
        "pbt_cr": row.get("pbt_cr"),
        "pat_cr": row.get("pat_cr"),
        "eps": row.get("eps"),
        **deltas,
        "source": row.get("source", "xbrl"),
        "xbrl_url": row.get("xbrl_url", ""),
        "verified": row.get("verified", 0),
        "bcast_date": row.get("_bcast", ""),
    }


# ─── main ────────────────────────────────────────────────────────────────────

def write_lane_health(outcomes: dict) -> None:
    """Atomically persist the earnings lane's fetch outcome and escalate live failures."""
    now = datetime.now(IST).isoformat()
    try:
        previous = json.loads(HEALTH_FILE.read_text())
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, json.JSONDecodeError):
        previous = {}

    previous_empty = previous.get("consecutive_empty_runs", 0)
    if not isinstance(previous_empty, int):
        previous_empty = 0
    if outcomes["filings_found"]:
        consecutive_empty_runs = 0
    elif not outcomes["fetch_successes"]:
        consecutive_empty_runs = 0
    elif in_results_season():
        consecutive_empty_runs = previous_empty + 1
    else:
        consecutive_empty_runs = previous_empty

    health = {
        "last_run": now,
        "last_fetch_ok": now if outcomes["fetch_successes"] else previous.get("last_fetch_ok"),
        "last_403": now if outcomes["is_403"] else previous.get("last_403"),
        "last_error": outcomes["last_error"],
        "fetch_attempts": outcomes["fetch_attempts"],
        "fetch_successes": outcomes["fetch_successes"],
        "fetch_failures": outcomes["fetch_failures"],
        "filings_found": outcomes["filings_found"],
        "drafts_written": outcomes["drafts_written"],
        "consecutive_empty_runs": consecutive_empty_runs,
    }
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=HEALTH_FILE.parent, delete=False) as tmp:
        json.dump(health, tmp)
        tmp.write("\n")
        tmp_name = tmp.name
    os.replace(tmp_name, HEALTH_FILE)

    reasons = []
    if outcomes["fetch_attempts"] and outcomes["fetch_failures"] == outcomes["fetch_attempts"]:
        reasons.append("total-failure")
    if outcomes["is_403"]:
        reasons.append("403")
    if consecutive_empty_runs >= 3:
        reasons.append(f"consecutive-empty-runs={consecutive_empty_runs}")
    if reasons and LIVE_FLAG.exists():
        line = f"FAILED earnings-treum {now} {','.join(reasons)}"
        with (ENGINE_DIR / "x" / "x-cron-status.md").open("a") as status:
            status.write(line + "\n")
        print(f"ESCALATION {line}", file=sys.stderr)

def _slug(sym: str, fiscal: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{sym}-{fiscal}".lower()).strip("-")


def _write_draft(row: dict, deltas: dict, today_iso: str, dry_run: bool) -> Optional[Path]:
    newsletter, thread = _build_thread({**row, **deltas}, row.get("_bcast", ""))
    record = _build_record(row, deltas)

    # HARD lint gate — a BLOCK on deterministic earnings text is a bug; refuse loudly.
    from compliance.lint import report
    hits = [v for v in report(newsletter + "\n" + thread) if v["severity"] == "block"]
    if hits:
        raise SystemExit(f"earnings_post: SEBI lint BLOCK on {row['symbol']} "
                         f"(bug — should never happen on factual numbers): {hits[:3]}")

    sym    = row["symbol"]
    fiscal = row["fiscal_label"]
    slug   = _slug(sym, fiscal)
    result_id = f"earnings-{slug}"            # STABLE per (symbol, fiscal): the idempotency key so an
                                              # evening draft and a next-morning re-draft can't double-post
                                              # (post_x dedups by frontmatter id).
    draft_id  = f"{today_iso}-{result_id}"    # dated FILENAME — keeps the lane-slug + generated-day gating
    out = DRAFTS / f"{draft_id}.md"

    body = (
        f"---\n"
        f"id: {result_id}\n"
        f"engine: earnings\n"
        f"topic: {sym} {fiscal} results\n"
        f"status: needs-review\n"
        f"model: deterministic\n"
        f"generated: {today_iso}\n"
        f"---\n\n"
        f"## NEWSLETTER\n\n{newsletter}\n\n"
        f"## X / TWITTER THREAD\n\n{thread}\n\n"
        f"## SOURCE\n\n```json\n{json.dumps(record, indent=2)}\n```\n\n"
        f"---\n> {DISCLAIMER}\n"
    )

    if dry_run:
        print(f"\nDRY earnings_post: would write {out.name}\n\n{body}")
        return None

    DRAFTS.mkdir(exist_ok=True)
    out.write_text(body)
    print(f"Earnings draft: {out.name}")
    return out


def run_today(now: datetime, dry_run: bool) -> int:
    """Scan watchlist for FRESH filings (same-day, or a late-evening filing seen next morning);
    generate one draft per new consolidated filing."""
    today = now.date()
    outcomes = {
        "fetch_attempts": 0, "fetch_successes": 0, "fetch_failures": 0,
        "filings_found": 0, "drafts_written": 0, "last_error": None, "is_403": False,
    }
    n = 0
    try:
        if not in_results_season(today):
            print(f"earnings_post: {today} is off-season for NSE results; nothing to do")
            return 0

        from services.nse_xbrl_fetcher import NSEXbrlFetcher
        # ponytail: one fetcher/session per run — NSE cookie warmed once, not per symbol (the 403-storm fix)
        fetcher = NSEXbrlFetcher()
        print(f"earnings_post: NSE session initialised (one per run)")

        universe = _load_universe()
        conn = _open_db()
        nse_calls = [0]   # mutable counter across symbols; checked before each symbol

        for sym in universe:
            if nse_calls[0] >= NSE_RUN_CAP:
                print(f"earnings_post: NSE run cap ({NSE_RUN_CAP} calls) reached; "
                      f"skipping remaining {len(universe) - universe.index(sym)} symbols", file=sys.stderr)
                break

            outcomes["fetch_attempts"] += 1
            rows = None
            for attempt in range(3):
                try:
                    rows = _fetch_and_parse_filings(sym, fresh_now=now, fetcher=fetcher, nse_calls=nse_calls)
                    outcomes["fetch_successes"] += 1
                    outcomes["filings_found"] += len(rows)
                    break
                except Exception as e:
                    outcomes["last_error"] = f"{sym}: {e}"
                    outcomes["is_403"] |= "403" in str(e)
                    if attempt == 2:
                        outcomes["fetch_failures"] += 1
                        print(f"  {sym}: 3 failures — {e}", file=sys.stderr)
                    else:
                        time.sleep(2 ** attempt)   # 1s, 2s backoff

            if not rows:
                time.sleep(0.2)    # polite rate limit
                continue

            # Prefer consolidated; fall back to standalone if only standalone is available.
            cons = [r for r in rows if r["consolidated"] == 1]
            best = cons[0] if cons else rows[0]

            _upsert(conn, best)
            deltas = _compute_deltas(conn, best)
            try:
                _write_draft(best, deltas, today.isoformat(), dry_run)
                n += 1
            except SystemExit as e:
                print(f"  {sym}: {e}", file=sys.stderr)
            time.sleep(0.5)

        conn.close()
        print(f"earnings_post: {n} draft(s) for {today} (NSE calls: {nse_calls[0]})")
        return 0
    finally:
        outcomes["drafts_written"] = n
        write_lane_health(outcomes)


def run_backfill(symbol: str) -> int:
    """Fetch and upsert all available quarterly filings for SYMBOL. No draft generation."""
    from services.nse_xbrl_fetcher import NSEXbrlFetcher
    sym = symbol.strip().upper()
    print(f"Backfilling {sym}...")
    fetcher = NSEXbrlFetcher()
    rows = _fetch_and_parse_filings(sym, fetcher=fetcher)
    if not rows:
        print(f"No XBRL filings found for {sym}")
        return 1
    # Process oldest-first so QoQ/YoY deltas chain correctly after upsert.
    rows.sort(key=lambda r: r["period_end"])
    conn = _open_db()
    for r in rows:
        _upsert(conn, r)
        print(f"  upserted {sym} {r['fiscal_label']} period={r['period_end']} "
              f"cons={r['consolidated']} rev={r.get('revenue_cr')} pat={r.get('pat_cr')}")
    conn.close()
    print(f"Backfill done: {len(rows)} rows for {sym}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date",     default=None,
                    help="YYYY-MM-DD to scan (default: today IST)")
    ap.add_argument("--dry-run",  action="store_true")
    ap.add_argument("--backfill", metavar="SYMBOL",
                    help="Seed DB with prior quarters for SYMBOL; no draft generated")
    args = ap.parse_args()

    if args.backfill:
        return run_backfill(args.backfill)

    if args.date:
        d = date.fromisoformat(args.date)
        now = datetime(d.year, d.month, d.day, 20, 0, tzinfo=IST)  # representative evening for historical/test runs
    else:
        now = datetime.now(IST)
    # No trading-day guard: results board meetings land on weekends all through earnings season;
    # is_fresh makes no-filing days a clean no-op (see x/cron/run.sh for the 2026-07-11 misses).

    return run_today(now, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
