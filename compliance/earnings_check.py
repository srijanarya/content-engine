#!/usr/bin/env python3
"""Value-correctness gate for earnings threads.

Every ₹-crore figure, margin %, EPS, and signed YoY/QoQ delta stated in the tweet
must re-derive from the SOURCE record. Orphan numbers (present in the text, absent in
the record) block. Fail-closed: no record or unverified record blocks immediately.

Mirrors value_check.py's _disagrees/tolerance style.

  python3 compliance/earnings_check.py --selfcheck
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
# Freshness / relevance window (Srijan's rule 2026-07-09): a result posts the SAME DAY; a filing
# broadcast late in the evening (>= FRESH_LATE_HOUR IST) may still post until FRESH_MORNING_HOUR the
# next morning; nothing older. Freshness IS relevance — the market-pulse "never post a day-old read"
# rule, applied to earnings. Tunable.
FRESH_LATE_HOUR = 18
FRESH_MORNING_HOUR = 11

TOL_CR  = 0.6   # ₹-crore rounding tolerance (matches 1-decimal display, e.g. 63973.0 vs 63973.4)
TOL_PCT = 0.2   # %-point tolerance for OPM / YoY / QoQ
TOL_EPS = 0.05  # EPS tolerance (2 decimal display)

# Regex: ₹ amounts in crore ("₹63,973 cr" or "₹18277 cr")
_CR_RE = re.compile(r"₹([\d,]+(?:\.\d+)?)\s*cr", re.IGNORECASE)
# Regex: OPM label ("OPM: 28.6%")
_OPM_RE = re.compile(r"\bOPM:\s*([\d.]+)%")
# Regex: EPS label ("EPS: 34.21")
_EPS_RE = re.compile(r"\bEPS:\s*([\d.]+)")
# Regex: signed YoY/QoQ delta ("(+4.5% YoY)" or "+4.5% YoY")
_DELTA_RE = re.compile(r"([+\-−][\d.]+)%\s*(YoY|QoQ)", re.IGNORECASE)

# All delta keys the SOURCE block may carry
_YOY_KEYS = ("yoy_revenue_pct", "yoy_ebitda_pct", "yoy_pbt_pct", "yoy_pat_pct")
_QOQ_KEYS = ("qoq_revenue_pct", "qoq_ebitda_pct", "qoq_pbt_pct", "qoq_pat_pct")
# Absolute crore fields that every ₹ amount must map to
_CR_KEYS  = ("revenue_cr", "ebitda_cr", "pbt_cr", "pat_cr")


def _to_float(s: str) -> float:
    return float(s.replace(",", "").replace("−", "-"))


def _parse_bcast(s):
    """NSE broadcast string -> aware IST datetime, or None. Keeps the TIME (unlike the generator's
    date-only parse) so the late-evening window can be judged. Accepts '09-Jan-2025 21:39:43',
    '09-Jan-2025 21:39', and date-only '31-Dec-2024' (→ 00:00, which fails the late-evening test)."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def is_fresh(bcast, now=None) -> tuple[bool, str]:
    """Relevance gate: is an earnings result fresh enough to post? Returns (ok, reason).

    Srijan's rule (2026-07-09): post the SAME DAY; a result filed late in the evening
    (broadcast hour >= FRESH_LATE_HOUR IST) may still post until FRESH_MORNING_HOUR the next
    morning; nothing older. FAIL-CLOSED on a missing/unparseable/future broadcast timestamp.
    `bcast` is the NSE broadcast string or a datetime; `now` defaults to datetime.now(IST)."""
    if now is None:
        now = datetime.now(IST)
    bts = bcast if isinstance(bcast, datetime) else _parse_bcast(bcast)
    if bts is None:
        return False, "no/unparseable broadcast timestamp"
    if bts.tzinfo is None:
        bts = bts.replace(tzinfo=IST)
    age = (now.date() - bts.date()).days
    if age < 0:
        return False, f"broadcast in the future ({bts:%Y-%m-%d %H:%M} IST)"
    if age == 0:
        return True, ""
    if age == 1 and bts.hour >= FRESH_LATE_HOUR and now.hour < FRESH_MORNING_HOUR:
        return True, ""   # late-evening filing, posted next morning
    return False, f"stale: filed {bts:%Y-%m-%d %H:%M} IST, now {now:%Y-%m-%d %H:%M} IST"


def verify_earnings(thread_text: str, record: dict | None) -> tuple[bool, str]:
    """(ok, reason).

    Blocks when:
    - record is None or verified != 1
    - any ₹ amount in the thread cannot be reconciled with a record field (orphan)
    - OPM, EPS, or any signed YoY/QoQ delta mismatches the record beyond tolerance
    """
    if not record:
        return False, "no SOURCE record to verify earnings numbers against"
    if record.get("verified") != 1:
        return False, f"SOURCE record not verified (verified={record.get('verified')!r})"

    cr_values = {k: record.get(k) for k in _CR_KEYS}

    # ── 1. crore amounts ────────────────────────────────────────────────────────
    for raw in _CR_RE.findall(thread_text):
        val = _to_float(raw)
        if not any(v is not None and abs(val - v) <= TOL_CR for v in cr_values.values()):
            return False, f"orphan ₹{val:,.0f} cr in thread not matched by any SOURCE field"

    # ── 2. OPM ─────────────────────────────────────────────────────────────────
    m = _OPM_RE.search(thread_text)
    if m:
        claimed = float(m.group(1))
        actual  = record.get("opm_pct")
        if actual is not None and abs(claimed - actual) > TOL_PCT:
            return False, f"OPM mismatch: text {claimed:.1f}% vs SOURCE {actual:.2f}%"

    # ── 3. EPS ─────────────────────────────────────────────────────────────────
    m = _EPS_RE.search(thread_text)
    if m:
        claimed = float(m.group(1))
        actual  = record.get("eps")
        if actual is not None and abs(claimed - actual) > TOL_EPS:
            return False, f"EPS mismatch: text {claimed} vs SOURCE {actual}"

    # ── 4. signed YoY / QoQ deltas ─────────────────────────────────────────────
    for dm in _DELTA_RE.finditer(thread_text):
        claimed = float(dm.group(1).replace("−", "-"))
        kind    = dm.group(2).lower()
        keys    = _YOY_KEYS if kind == "yoy" else _QOQ_KEYS
        valids  = [record[k] for k in keys if record.get(k) is not None]
        if valids and not any(abs(claimed - d) <= TOL_PCT for d in valids):
            return False, (f"{kind.upper()} delta {claimed:+.1f}% in thread not matched "
                           f"by any SOURCE delta (candidates: {valids})")

    return True, ""


if __name__ == "__main__":
    if "--selfcheck" not in sys.argv:
        print(__doc__)
        sys.exit(0)

    # ── happy path ─────────────────────────────────────────────────────────────
    rec = {
        "symbol": "TCS", "fiscal_label": "Q3FY25", "verified": 1,
        "revenue_cr": 63973.0, "ebitda_cr": 18277.0, "opm_pct": 28.57,
        "pbt_cr": 16666.0, "pat_cr": 12444.0, "eps": 34.21,
        "yoy_revenue_pct": 4.5, "yoy_pat_pct": 5.2,
        "qoq_revenue_pct": 1.2, "qoq_pat_pct": 0.8,
    }
    thread = (
        "TCS Q3FY25 (Consolidated):\n"
        "Revenue: ₹63,973 cr (+4.5% YoY, +1.2% QoQ)\n"
        "EBITDA: ₹18,277 cr | OPM: 28.6%\n\n"
        "PAT: ₹12,444 cr (+5.2% YoY, +0.8% QoQ)\n"
        "EPS: 34.21\nPBT: ₹16,666 cr"
    )
    ok, why = verify_earnings(thread, rec)
    assert ok, f"happy path failed: {why}"

    # ── no record ───────────────────────────────────────────────────────────────
    ok, why = verify_earnings(thread, None)
    assert not ok and "no SOURCE" in why, why

    # ── unverified ─────────────────────────────────────────────────────────────
    ok, why = verify_earnings(thread, {**rec, "verified": 0})
    assert not ok and "not verified" in why, why

    # ── tampered crore ─────────────────────────────────────────────────────────
    bad = thread.replace("₹63,973 cr", "₹70,000 cr")
    ok, why = verify_earnings(bad, rec)
    assert not ok and "orphan" in why, why

    # ── tampered OPM ───────────────────────────────────────────────────────────
    bad = thread.replace("OPM: 28.6%", "OPM: 35.0%")
    ok, why = verify_earnings(bad, rec)
    assert not ok and "OPM" in why, why

    # ── tampered EPS ───────────────────────────────────────────────────────────
    bad = thread.replace("EPS: 34.21", "EPS: 45.00")
    ok, why = verify_earnings(bad, rec)
    assert not ok and "EPS" in why, why

    # ── tampered YoY delta ─────────────────────────────────────────────────────
    bad = thread.replace("+4.5% YoY", "+15.0% YoY")
    ok, why = verify_earnings(bad, rec)
    assert not ok and "YoY".upper() in why.upper(), why

    # ── no prior data: deltas absent from record are not checked ────────────────
    rec_no_delta = {**rec, "yoy_revenue_pct": None, "yoy_pat_pct": None,
                    "qoq_revenue_pct": None, "qoq_pat_pct": None}
    thread_no_delta = (
        "TCS Q3FY25 (Consolidated):\n"
        "Revenue: ₹63,973 cr\nEBITDA: ₹18,277 cr | OPM: 28.6%\n\n"
        "PAT: ₹12,444 cr\nEPS: 34.21\nPBT: ₹16,666 cr"
    )
    ok, why = verify_earnings(thread_no_delta, rec_no_delta)
    assert ok, f"no-delta path failed: {why}"

    # ── freshness gate (is_fresh) ───────────────────────────────────────────────
    _T = datetime  # brevity
    same_day = _T(2025, 1, 9, 22, 0, tzinfo=IST)
    assert is_fresh("09-Jan-2025 21:39:43", same_day)[0], "same-day must be fresh"
    next_morning = _T(2025, 1, 10, 8, 30, tzinfo=IST)
    assert is_fresh("09-Jan-2025 21:39:43", next_morning)[0], "late-evening -> next-morning must be fresh"
    next_afternoon = _T(2025, 1, 10, 14, 0, tzinfo=IST)
    ok, why = is_fresh("09-Jan-2025 21:39:43", next_afternoon)
    assert not ok and "stale" in why, "late-evening filing is stale by next afternoon"
    ok, why = is_fresh("09-Jan-2025 10:00:00", next_morning)   # yesterday DAYTIME filing
    assert not ok, "a daytime filing is stale the next morning (only late-evening qualifies)"
    two_days = _T(2025, 1, 11, 9, 0, tzinfo=IST)
    assert not is_fresh("09-Jan-2025 21:39:43", two_days)[0], "two-days-old must be stale"
    for bad in ("", None, "garbage", 12345):
        ok, why = is_fresh(bad, same_day)
        assert not ok, f"fail-closed expected for {bad!r}"
    assert is_fresh("31-Dec-2024", _T(2024, 12, 31, 20, 0, tzinfo=IST))[0], "date-only same-day fresh"
    assert not is_fresh("31-Dec-2024", _T(2025, 1, 1, 8, 0, tzinfo=IST))[0], "date-only (00:00) not late-evening"

    print("earnings_check selfcheck OK")
