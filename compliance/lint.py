#!/usr/bin/env python3
"""
SEBI compliance linter — the hard gate before any market content is published or sold.

The line (primary-sourced, see reports/deep-research/2026-06-21-sebi-compliance.json):
  SAFE   = market data, broad-index/regime DESCRIPTION, sector-level commentary, macro,
           statistical summaries, non-recommendatory language analysis.
  BLOCK  = ANY per-security buy/sell/hold/short/avoid/target/stop-loss/bias — i.e. a
           recommendation on a SPECIFIC stock. Illegal to publish/sell unregistered.

This is a code-level gate, NOT a prompt suggestion. `is_safe()` returns False on any BLOCK.

ponytail: regex + word-list, no NER dependency. Ceiling = it keys off a known ticker/name
list + directional-word proximity; an unlisted micro-cap referenced by a novel nickname could
slip through. Upgrade path: add NER (spaCy) if the ticker list proves too narrow. The list is
seeded from the FNO universe; extend via tickers.txt.
"""
from __future__ import annotations
import json, re, sys, unicodedata
from pathlib import Path

HERE = Path(__file__).parent

# HIGH-PRECISION directional terms — near a specific stock = a per-security call (BLOCK).
# Deliberately excludes ambiguous English words (call/book/hold/add/reduce/exit/target/long/short
# bare) to avoid false positives on "earnings call", "order book", "household", "short-term", etc.
# Those ambiguous forms, when they ARE real calls, live in structured fields (DANGER_KEYS) which the
# structured linter catches exactly. Bare long/short are caught only when IMMEDIATELY adjacent to a
# ticker (see lint_text), so "short TCS" blocks but "short-term" does not.
DIRECTIONAL = {
    "buy", "sell", "accumulate", "strongbuy", "overweight", "underweight",
    "longonly", "shortonly", "bullish", "bearish", "avoid",
    # Valuation-flavored calls (added 2026-07-06 with the AKSH valuation workbench: a
    # "fair value"/"undervalued" claim NEAR a named security is a per-stock view even
    # with no buy/sell verb). Proximity-gated like every other token here, so DCF
    # methodology education with no named stock still passes. Two-word forms are fused
    # to one token in _prep_tokens (see _VALUATION_TERMS).
    "undervalued", "overvalued", "mispriced", "fairvalue", "intrinsicvalue",
}
DIRECTIONAL_ADJACENT = {"short", "long"}  # only count when right next to a ticker (window 1)
# Phrases (checked on the joined text) that are explicit calls.
DIRECTIONAL_PHRASES = ("strong buy", "stop loss", "price target", "target price", "book profit",
                       "go long", "go short", "trading call", "buy call", "sell call")
# Contexts where a directional word is NOT a call — skip these.
STOP_PHRASES = ("sell-side", "sell side", "buy-side", "buy side", "buyback", "buy back",
                "sell-off", "sell off", "short-term", "short term", "long-term", "long term",
                "buyers", "sellers", "buying", "selling", "longer", "shorter")
# "avoid" is a directional term ("avoid Reliance" = a per-stock call), but these are analytical idioms, NOT
# calls. They are blanked from the sentence BEFORE tokenizing (unlike STOP_PHRASES, which only affect the
# phrase scan), so the bare "avoid" can't register as a directional hit next to a company name. Without this
# the audit would false-DELETE "HDFC earnings beat; avoid reading too much into one quarter."
_DIR_IDIOMS = ("avoid reading", "avoid extrapolating", "avoid conflating", "avoid confusing",
               "avoid overreading", "avoid over-reading")
DISCLAIMER_MARKERS = ("not investment advice", "no buy/sell", "not a recommendation",
                      "not a research report", "buy/sell/hold", "for educational",
                      "do your own research", "consult a sebi",
                      # Hindi disclaimer markers (2026-07-06, Hinglish pulse lane)
                      "निवेश सलाह नहीं", "सिफारिश नहीं", "शैक्षिक उद्देश्य", "शिक्षा के लिए",
                      "सेबी पंजीकृत नहीं", "सेबी-पंजीकृत नहीं")

# ---------------------------------------------------------------- Hindi / Hinglish (2026-07-06)
# The Hinglish register keeps tickers/acronyms/digits in Latin (so TICKERS matching still works);
# the danger surface is Hindi directional verbs/phrases near a (Latin or Devanagari) name.
# Same precision philosophy as English: IMPERATIVE forms are directional tokens; oblique/
# infinitive forms (खरीदने/बेचना) are NOT — they are the descriptive backbone of market prose
# ("बेचने का दबाव" = selling pressure) and their directive uses are caught by the advice
# phrases below. ponytail: wordlist, not morphology — extend from red-team findings, and
# romanized-Hinglish coverage is the imperatives only; NER stays the upgrade path.
HINDI_DIRECTIONAL = {
    "खरीदें", "खरीदो", "खरीदिए", "खरीदेंगे", "बेचें", "बेचो", "बेचिए",
    "बुलिश", "बेयरिश", "बचें", "बचो",           # बचें = avoid (proximity-gated like English)
    "kharido", "kharidiye", "kharidein", "becho", "bechiye", "bechein",
}
HINDI_DIRECTIONAL_PHRASES = (
    "टारगेट प्राइस", "प्राइस टारगेट", "स्टॉप लॉस", "स्टॉपलॉस", "मुनाफा बुक", "प्रॉफिट बुक",
    "खरीदने की सलाह", "बेचने की सलाह", "खरीदने की सिफारिश", "बेचने की सिफारिश",
    "निवेश की सलाह", "खरीद लो", "बेच दो", "निवेश करें", "निवेश कर लें",
    "kharid lo", "bech do",
)
HINDI_NAME_VARIANTS = {
    "रिलायंस", "इंफोसिस", "टीसीएस", "एचडीएफसी", "आईसीआईसीआई", "कोटक", "एक्सिस",
    "विप्रो", "मारुति", "टाइटन", "अडानी", "अदानी", "एसबीआई", "आईटीसी", "एलएंडटी",
}
HINDI_MULTIWORD = ("टाटा मोटर्स", "टाटा स्टील", "बजाज फाइनेंस", "एशियन पेंट्स",
                   "सन फार्मा", "हिंदुस्तान यूनिलीवर", "भारती एयरटेल")
# निफ्टी/सेंसेक्स are unambiguous index names → always match (Devanagari has no uppercase
# signal, so the isupper() precision trick can't apply); common-word sectors (बैंक, आईटी…)
# match only with a follower, mirroring the English follower rule.
HINDI_INDEX_ALWAYS = {"निफ्टी", "बैंकनिफ्टी", "सेंसेक्स"}
HINDI_INDEX_SECTOR = {"आईटी", "बैंक", "ऑटो", "फार्मा", "एफएमसीजी", "मेटल",
                      "एनर्जी", "रियल्टी", "मीडिया", "इंफ्रा", "पीएसयू"}
HINDI_SECTOR_FOLLOWERS = {"सेक्टर", "सेक्टरों", "इंडेक्स", "शेयर", "शेयरों", "स्टॉक्स"}


def _deva_fold(s: str) -> str:
    """Fold Devanagari nukta variants (ख़रीदें == खरीदें) so wordlists and text can't
    disagree on a diacritic: NFD → drop nukta (U+093C) → NFC."""
    return unicodedata.normalize(
        "NFC", unicodedata.normalize("NFD", s).replace("़", ""))

# Structured-data keys that encode a per-stock directional view.
DANGER_KEYS = {
    "side_bias", "strong_buy", "strong_buys", "aksh_strong_buys", "recommendation",
    "rec", "trade_signal", "price_target", "tp_pct", "sl_pct", "stop_loss",
    "stoploss", "action", "verdict",
    # Valuation-workbench output fields (2026-07-06): fine inside the tier-gated B2B API,
    # but if a content script ever embeds them in public copy that IS a per-stock view.
    "fair_value", "intrinsic_value", "fair_value_per_share", "upside_downside_pct",
    "implied_upside", "pv_vs_user_price_pct",
}
SAFE_BIAS_VALUES = {"neutral", "none", "", None}  # side_bias=neutral isn't a directional call

# Sector/index tokens — matched only when UPPERCASE or followed by sector/index/stocks (precise),
# since most are common English words (it/bank/auto/media/metal/energy). Directional-near-sector = WARN.
INDEX_SECTOR = {
    "NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCAP", "SMALLCAP", "VIX",
    "IT", "BANK", "AUTO", "PHARMA", "FMCG", "METAL", "ENERGY", "REALTY", "MEDIA",
    "INFRA", "PSU", "PSUBANK",
}
_SECTOR_FOLLOWERS = {"sector", "sectors", "index", "stocks", "pack", "space"}

_CORE_TICKERS = (
    "RELIANCE HDFCBANK ICICIBANK TCS INFY HINDUNILVR ITC SBIN BHARTIARTL KOTAKBANK LT "
    "AXISBANK BAJFINANCE ASIANPAINT MARUTI SUNPHARMA TITAN ULTRACEMCO WIPRO NESTLEIND "
    "HCLTECH ONGC NTPC POWERGRID TATAMOTORS TATASTEEL JSWSTEEL ADANIENT ADANIPORTS COALINDIA "
    "BAJAJFINSV GRASIM HINDALCO DIVISLAB DRREDDY CIPLA BRITANNIA EICHERMOT HEROMOTOCO "
    "BPCL IOC TECHM INDUSINDBK UPL APOLLOHOSP TATACONSUM SBILIFE HDFCLIFE BAJAJ-AUTO "
    "LTIM LTIMINDTREE DMART PIDILITIND DABUR GODREJCP HAVELLS SIEMENS PNB BANKBARODA "
    "DLF"
).split()  # standard Nifty/FNO names (public). Personal watchlist → gitignored tickers.txt.
# Common company-name variants (lowercased) that aren't the ticker. Single-token names only — multi-word
# names live in _MULTIWORD and are FUSED to one token before tokenizing (e.g. "asian paints" -> "asianpaints")
# so they actually match; left as two tokens they were dead code and "Buy Asian Paints, target 3200" slipped
# past the SEBI gate.
_MULTIWORD = ("asian paints", "bajaj finance", "tata motors", "tata steel", "dr reddy",
              "hindustan unilever", "sun pharma")
_NAME_VARIANTS = {
    "reliance", "infosys", "hdfc", "icici", "kotak", "axis", "wipro", "maruti", "titan",
    "adani", "hul", "larsen", "ultratech", "nestle",
    *(m.replace(" ", "") for m in _MULTIWORD),  # asianpaints, bajajfinance, tatamotors, ...
}


def _load_tickers() -> set[str]:
    tickers = set(_CORE_TICKERS)
    f = HERE / "tickers.txt"
    if f.exists():
        for line in f.read_text().splitlines():
            t = line.strip().upper()
            if t and not t.startswith("#"):
                tickers.add(t)
    return tickers


TICKERS = _load_tickers()
# Devanagari included (danda ।॥ U+0964/65 excluded — they are sentence punctuation, and a
# trailing danda glued to a token would break exact-match against the wordlists).
_WORD = re.compile(r"[A-Za-zऀ-ॣ०-ॿ][A-Za-zऀ-ॣ०-ॿ&\-]+")

# Merge the Hindi lists into the live sets (before the *_NORMS snapshots below).
DIRECTIONAL |= HINDI_DIRECTIONAL
DIRECTIONAL_PHRASES = DIRECTIONAL_PHRASES + HINDI_DIRECTIONAL_PHRASES
_MULTIWORD = _MULTIWORD + HINDI_MULTIWORD
_NAME_VARIANTS |= HINDI_NAME_VARIANTS | {m.replace(" ", "") for m in HINDI_MULTIWORD}
INDEX_SECTOR |= HINDI_INDEX_SECTOR | HINDI_INDEX_ALWAYS
_SECTOR_FOLLOWERS |= HINDI_SECTOR_FOLLOWERS


def _norm(tok: str) -> str:
    return _deva_fold(tok.lower()).replace("_", "").replace("-", "")


_NAME_NORMS = {_norm(n) for n in _NAME_VARIANTS}
_DIR_NORMS = {_norm(d) for d in DIRECTIONAL}
_HINDI_INDEX_ALWAYS_NORMS = {_norm(x) for x in HINDI_INDEX_ALWAYS}


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?।\n])\s+", text)


# Two-word valuation terms fused to one token (like _MULTIWORD company names) so they can
# sit in DIRECTIONAL and stay proximity-gated: "TCS fair value is 3800" blocks, while
# "a DCF turns assumptions into a fair value estimate" (no named security nearby) passes.
_VALUATION_TERMS = ("fair value", "intrinsic value")


def _prep_tokens(text: str) -> str:
    """Sentence as the token matcher should see it: collapse multi-word company names to one token
    ("Asian Paints" -> "AsianPaints") so they actually match, and blank analytical "avoid <gerund>" idioms
    so the bare directional "avoid" can't fire next to a name."""
    for name in _MULTIWORD:
        text = re.sub(re.escape(name), name.replace(" ", ""), text, flags=re.I)
    for term in _VALUATION_TERMS:
        text = re.sub(re.escape(term), term.replace(" ", ""), text, flags=re.I)
    for idiom in _DIR_IDIOMS:
        text = re.sub(re.escape(idiom), " " * len(idiom), text, flags=re.I)
    return text


def lint_text(text: str, window: int = 5) -> list[dict]:
    """Return violations in free text. severity 'block' (per-stock call) or 'warn' (sector/index call).
    Precision-biased: skips disclaimers and stop-phrase contexts; bare long/short only block when
    immediately adjacent to a ticker; sector words match only when UPPERCASE or sector-qualified."""
    violations = []
    for sent in _sentences(text):
        low = _deva_fold(sent.lower())
        if any(m in low for m in DISCLAIMER_MARKERS):
            continue  # the disclaimer SAYS "no buy/sell/hold" — that's not a call
        # blank out stop-phrase regions so their words don't match
        scrubbed = low
        for sp in STOP_PHRASES:
            scrubbed = scrubbed.replace(sp, " " * len(sp))
        # explicit call phrases anywhere in the sentence
        if any(p in scrubbed for p in DIRECTIONAL_PHRASES):
            violations.append({"severity": "block", "snippet": sent.strip()[:120],
                               "reason": "explicit directional phrase"})
            continue

        tokens = _WORD.findall(_prep_tokens(sent))
        norm = [_norm(t) for t in tokens]
        upper = [t.upper() for t in tokens]
        for i, tok in enumerate(tokens):
            up, nl = upper[i], norm[i]
            is_ticker = up in TICKERS
            is_name = nl in _NAME_NORMS
            # sector only if uppercase token OR next token is sector/index/stocks; Devanagari
            # has no case, so निफ्टी/सेंसेक्स match unconditionally and common-word sectors
            # (बैंक, आईटी…) need a follower, mirroring the English precision rule
            nxt = _norm(tokens[i + 1]) if i + 1 < len(tokens) else ""
            is_index = ((tok.isupper() and up in INDEX_SECTOR)
                        or (up in INDEX_SECTOR and nxt in _SECTOR_FOLLOWERS)
                        or nl in _HINDI_INDEX_ALWAYS_NORMS)
            if not (is_ticker or is_name or is_index):
                continue
            lo, hi = max(0, i - window), min(len(tokens), i + window + 1)
            near = set(norm[lo:i] + norm[i + 1:hi])
            # if this token region was stop-phrased, skip (e.g. "selling" near a name)
            hits = near & _DIR_NORMS
            # bare long/short only count if immediately adjacent to a TICKER
            if (is_ticker):
                adj = {norm[j] for j in (i - 1, i + 1) if 0 <= j < len(norm)}
                hits |= (adj & DIRECTIONAL_ADJACENT)
            if not hits:
                continue
            sev = "warn" if (is_index and not is_ticker and not is_name) else "block"
            violations.append({
                "severity": sev, "entity": tok, "directional": sorted(hits),
                "snippet": " ".join(tokens[lo:hi]),
                "reason": ("per-security directional call" if sev == "block"
                           else "sector/index directional — review (sector TA exempt; a sector CALL is not)"),
            })
    return violations


def lint_structured(obj, path: str = "") -> list[dict]:
    """Walk a dict/list (e.g. a regime JSON) and flag danger keys + non-neutral biases."""
    violations = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            here = f"{path}.{k}" if path else k
            if kl in DANGER_KEYS:
                # side_bias=neutral / tp=null are not calls; everything else under a danger key is.
                if kl in ("side_bias", "bias") and (str(v).lower() in {b for b in SAFE_BIAS_VALUES if b}):
                    pass
                elif v in (None, "", [], {}):
                    pass
                else:
                    violations.append({
                        "severity": "block", "path": here, "key": k, "value": v,
                        "reason": f"structured per-stock directional field '{k}'",
                    })
            violations += lint_structured(v, here)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            violations += lint_structured(item, f"{path}[{idx}]")
    elif isinstance(obj, str):
        violations += [{**v, "path": path} for v in lint_text(obj)]
    return violations


def is_safe(content) -> bool:
    """True only if there are ZERO block-level violations. Warns do not fail the gate."""
    v = lint_structured(content) if not isinstance(content, str) else lint_text(content)
    return not any(x["severity"] == "block" for x in v)


def report(content) -> list[dict]:
    return lint_structured(content) if not isinstance(content, str) else lint_text(content)


def demo():
    # BLOCK: explicit per-stock call
    assert not is_safe("STRONG_BUY RELIANCE — accumulate on dips"), "must block per-stock buy call"
    assert not is_safe("I'd short TCS here, target 3800"), "must block short call"
    assert not is_safe({"symbol": "HDFCBANK", "side_bias": "long-only"}), "must block structured side_bias"
    assert not is_safe({"aksh_strong_buys": [{"symbol": "DYNAMIC", "score": 95}]}), "must block strong_buys"
    assert not is_safe("Buy Asian Paints here, target 3200"), "multi-word name call must block (was dead code)"
    assert not is_safe("Accumulate Bajaj Finance on this dip"), "multi-word name call must block"
    # SAFE: regime / data / sector description
    assert is_safe("Nifty closed -1.62% at 23,430, below its 75-EMA. Pullback regime; VIX 19.3."), "regime desc is safe"
    assert is_safe("FII net -1,987 Cr, DII +4,224 Cr. IT sector -3.73%, the weakest of the day."), "sector data is safe"
    assert is_safe({"symbol": "RELIANCE", "side_bias": "neutral"}), "neutral bias is not a call"
    assert is_safe("HDFC Bank earnings beat; avoid reading too much into one quarter."), "analytical 'avoid reading' near a name is not a call"
    assert is_safe("Infosys guidance held; avoid extrapolating one print to the sector."), "'avoid extrapolating' near a name is not a call"
    # WARN (not block): a sector-level directional phrase
    v = lint_text("avoid IT this week")
    assert any(x["severity"] == "warn" for x in v), "sector directional should warn"
    assert is_safe("avoid IT this week"), "a sector warn must not hard-fail the gate"
    # Valuation terms (2026-07-06): per-stock valuation views block; methodology education passes
    assert not is_safe("TCS looks undervalued at these levels"), "per-stock undervalued must block"
    assert not is_safe("Infosys fair value works out to 1800"), "per-stock fair value must block"
    assert not is_safe("intrinsic value of Reliance is well above the market"), "per-stock intrinsic value must block"
    assert is_safe("A DCF turns growth assumptions into a fair value estimate; garbage in, garbage out."), \
        "valuation methodology education with no named stock must pass"
    assert not is_safe({"symbol": "TCS", "fair_value_per_share": 3800}), "structured fair_value field must block"
    # Hindi / Hinglish (2026-07-06): Devanagari used to tokenize to NOTHING (the _WORD regex
    # was [A-Za-z]-only), so per-stock calls in Hindi sailed through. These canaries pin the fix.
    assert not is_safe("Reliance खरीदें, टारगेट 3200"), "Hindi imperative near Latin name must block"
    assert not is_safe("रिलायंस में बुलिश हूं, गिरावट पर खरीदें"), "Devanagari name + बुलिश must block"
    assert not is_safe("टाटा मोटर्स बेच दो, स्टॉप लॉस 900"), "Hindi sell phrase must block"
    assert not is_safe("ख़रीदें HDFCBANK अभी"), "nukta variant ख़रीदें must fold and block"
    assert not is_safe("TCS kharido, target strong"), "romanized-Hinglish imperative must block"
    assert is_safe("आईटी सेक्टर में बिकवाली रही, बैंक शेयरों में खरीदारी दिखी।"), \
        "descriptive बिकवाली/खरीदारी (market activity) must pass"
    assert is_safe("11 में से 8 निफ्टी सेक्टरों में ज़्यादातर शेयर 50 दिन के एवरेज के ऊपर हैं।"), \
        "pulse breadth read must pass"
    assert is_safe("बाजार में बेचने का दबाव रहा, मुनाफावसूली हावी रही।"), \
        "oblique बेचने (selling pressure) is descriptive, must pass"
    assert is_safe("यह निवेश सलाह नहीं है, खरीदने या बेचने की कोई सिफारिश नहीं।"), \
        "the Hindi disclaimer itself must not trip the gate"
    v = lint_text("आईटी सेक्टर से बचें इस हफ्ते")
    assert any(x["severity"] == "warn" for x in v), "Hindi sector-avoid should warn"
    assert is_safe("आईटी सेक्टर से बचें इस हफ्ते"), "a Hindi sector warn must not hard-fail"
    print("lint demo: all assertions passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    elif len(sys.argv) > 1:
        p = Path(sys.argv[1])
        content = json.loads(p.read_text()) if p.suffix == ".json" else p.read_text()
        vs = report(content)
        blocks = [v for v in vs if v["severity"] == "block"]
        print(f"{p.name}: {len(blocks)} BLOCK, {len(vs) - len(blocks)} warn")
        for v in vs:
            print(f"  [{v['severity']}] {v.get('path') or v.get('snippet','')}: {v['reason']}")
        sys.exit(1 if blocks else 0)
    else:
        demo()
