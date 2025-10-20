from __future__ import annotations

import os
import re
from typing import Dict, Any, List
from collections import defaultdict
import datetime as dt
import pytz

from scraper import arabic_search, fetch_and_extract_prices
from prompts import build_report_prompt
from utils import now_cairo

# If your original file already had a custom _llm_call, you can keep it.
# Below is a safe default using langchain-groq.
try:
    from langchain_groq import ChatGroq
except Exception:  # pragma: no cover
    ChatGroq = None


# ---------------------------
# Helpers
# ---------------------------

BAD_SUBSTRINGS = ("xau-usd", "/oz", "/ounce", "/currencies/", "/turkey-")


def _likely_irrelevant(url: str) -> bool:
    u = url.lower()
    return any(s in u for s in BAD_SUBSTRINGS)


def _is_today(hint: str | None) -> bool:
    """
    Accepts 'اليوم' or simple dates:
      - 2025-10-20
      - 20-10-2025
      - 20/10/2025
    Compares against Africa/Cairo 'today'.
    """
    if not hint:
        return False
    if hint.strip() == "اليوم":
        return True

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", hint) or re.match(
        r"^(\d{1,2})[-/](\d{1,2})[-/](20\d{2})$", hint
    )
    if not m:
        return False

    try:
        # ISO form
        if len(m.groups()) == 3 and len(m.group(1)) == 4:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            # dd-mm-yyyy or dd/mm/yyyy
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        today = (
            now_cairo().date()
            if callable(now_cairo)
            else dt.datetime.now(pytz.timezone("Africa/Cairo")).date()
        )
        return dt.date(y, mo, d) == today
    except Exception:
        return False


def _llm_call(system: str, user: str) -> str:
    """
    Minimal Groq LLM wrapper. If you already had one, feel free to keep yours.
    """
    if ChatGroq is None:
        return "تعذّر استدعاء نموذج اللغة (ChatGroq غير متوفر)."

    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return "لم يتم ضبط GROQ_API_KEY. الرجاء إضافته إلى ملف .env."

    llm = ChatGroq(model=model, api_key=api_key, temperature=0.2, timeout=60)
    msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        resp = llm.invoke(msgs)
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        return f"حدث خطأ أثناء توليد التقرير: {e}"


# ---------------------------
# Agents
# ---------------------------


def search_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Arabic web search, de-dupe, and Egypt-focused link filtering.
    """
    query = state.get("query") or "سعر الذهب اليوم"
    region = state.get("region") or os.getenv("DEFAULT_REGION", "EG")

    links: List[str] = arabic_search(
        query,
        region=region,
        max_results=int(os.getenv("MAX_SOURCES", 6)),
    )

    # Drop irrelevant URLs: ounce/USD/Turkey/currencies listings
    links = [u for u in links if not _likely_irrelevant(u)]

    # Save back
    return {**state, "region": region, "links": links}


def fetch_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch pages, extract EGP per-gram prices, prefer 'today', build stats.
    Also computes split stats for 21k with/without making charge.
    """
    links = state.get("links", [])
    pages, prices = fetch_and_extract_prices(links)

    # Egypt filters (EGP + sensible numeric range)
    region = state.get("region") or os.getenv("DEFAULT_REGION", "EG")
    if region == "EG":
        egp_aliases = ("جنيه", "جنيه مصري", "ج.م", "EGP")
        prices = [
            p
            for p in prices
            if any(a in (p.get("currency") or "") for a in egp_aliases)
        ]
        MIN_EGP, MAX_EGP = 500.0, 20000.0
        prices = [
            p
            for p in prices
            if isinstance(p.get("price"), (int, float))
            and MIN_EGP <= p["price"] <= MAX_EGP
        ]

    # Prefer today's prices when available (based on published_hint from scraper)
    today_prices = [p for p in prices if _is_today(p.get("published_hint"))]
    if today_prices:
        prices = today_prices

    # Overall per-karat stats
    by_k = defaultdict(list)
    for p in prices:
        k = p.get("karat")
        pr = p.get("price")
        if k in (18, 21, 24) and isinstance(pr, (int, float)):
            by_k[k].append(float(pr))

    stats = {}
    for k, arr in by_k.items():
        stats[k] = {"min": min(arr), "max": max(arr), "count": len(arr)}

    # Split by making charge (مصنعية)
    stats_wm = defaultdict(
        lambda: {"min": float("inf"), "max": float("-inf"), "count": 0}
    )
    for p in prices:
        k = p.get("karat")
        pr = p.get("price")
        if k in (18, 21, 24) and isinstance(pr, (int, float)):
            key = (k, bool(p.get("with_making")))
            bucket = stats_wm[key]
            bucket["min"] = min(bucket["min"], pr)
            bucket["max"] = max(bucket["max"], pr)
            bucket["count"] += 1

    # Clean infinities and JSONify keys
    for bucket in stats_wm.values():
        if bucket["min"] == float("inf"):
            bucket["min"] = 0
        if bucket["max"] == float("-inf"):
            bucket["max"] = 0
    stats_wm = {
        f"{k}:{'with' if w else 'without'}": v for (k, w), v in stats_wm.items()
    }

    return {
        **state,
        "region": region,
        "pages": pages,
        "prices": prices,
        "stats": stats,
        "stats_wm": stats_wm,
    }


def report_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the strict Egypt-only prompt and call the LLM to produce the Arabic report.
    """
    region = state.get("region") or os.getenv("DEFAULT_REGION", "EG")
    system, user = build_report_prompt(
        prices=state.get("prices", []),
        links=state.get("links", []),
        region=region,
        timestamp=now_cairo().strftime("%Y-%m-%d %H:%M %Z"),
        stats=state.get("stats", {}),
    )
    report = _llm_call(system, user)
    return {**state, "region": region, "report": report}
