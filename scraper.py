from __future__ import annotations
from typing import List, Dict, Any, Tuple, Iterable
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
from utils import normalize_number
from tenacity import retry, stop_after_attempt, wait_exponential
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "ar-EG, en:q=0.8",
}

AR_QUERIES = ["سعر الذهب اليوم", "أسعار الذهب اليوم", "سعر جرام الذهب اليوم"]
SOCIAL_BLOCK = (
    "facebook.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "instagram.com",
    "tiktok.com",
)

# (Optional) we still filter noisy results later in agents.py; here we keep search permissive.

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _to_western_digits(text: str) -> str:
    return text.translate(_AR_DIGITS)


def _unique(seq: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def arabic_search(query: str, region: str = "EG", max_results: int = 6) -> List[str]:
    links: List[str] = []
    with DDGS() as ddgs:
        for q in [query] + AR_QUERIES:
            try:
                for r in ddgs.text(q, region=region, max_results=max_results):
                    url = r.get("href") or r.get("link") or r.get("url")
                    if not url:
                        continue
                    if any(bad in url for bad in SOCIAL_BLOCK):
                        continue
                    links.append(url)
                    if len(_unique(links)) >= max_results:
                        break
            except Exception:
                # swallow DDG hiccups and continue with next query
                pass
            if len(_unique(links)) >= max_results:
                break
    return _unique(links)[:max_results]


def _extract_candidates(soup: BeautifulSoup) -> List[str]:
    texts: List[str] = []
    for sel in (".price", ".gold", "table", "body"):
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt:
                texts.append(txt)
    if not texts:
        body_txt = soup.get_text(" ", strip=True)
        if body_txt:
            texts.append(body_txt[:3000])
    # normalize Arabic digits to western for parsing
    return [_to_western_digits(t) for t in texts]


# === Patterns (EGP-only) ===
# Only Egyptian pound notations
_CURRENCY = r"(?:جنيه(?:\s*مصري)?|ج\.م|EGP)"
_NUM = r"(\d[\d\.\,\s]*)"

# price with currency (e.g., 3450 جنيه)
PAT_PRICE_CURR = re.compile(rf"{_NUM}\s*{_CURRENCY}", re.IGNORECASE)

# number near gram/karat 21/24 (fallback)
PAT_GRAM_21_24 = re.compile(
    rf"{_NUM}\s*(?:ل|)جرام\s*(?:عيار\s*)?(?:21|24)", re.IGNORECASE
)

# karat-aware patterns
PAT_KARAT_THEN_PRICE = re.compile(
    r"عيار\s*(?P<karat>18|21|24)\D{0,8}(?P<price>\d[\d.,\s]*)", re.IGNORECASE
)
PAT_PRICE_THEN_KARAT = re.compile(
    r"(?P<price>\d[\d.,\s]*)\D{0,8}عيار\s*(?P<karat>18|21|24)", re.IGNORECASE
)


# === Helpers ===
def _looks_like_year(x: float) -> bool:
    return 1900 <= x <= 2100 and float(x).is_integer()


_GOLD_CONTEXT_WORDS = ("ذهب", "جرام", "عيار", "ذهبية", "سعر")


def _has_gold_context(text: str) -> bool:
    return any(w in text for w in _GOLD_CONTEXT_WORDS)


_DATE_PATS = [
    r"\b(20\d{2}-\d{2}-\d{2})\b",  # 2025-10-20
    r"\b(\d{1,2}/\d{1,2}/20\d{2})\b",  # 20/10/2025
    r"\b(\d{1,2}-\d{1,2}-20\d{2})\b",  # 20-10-2025
]


def _maybe_find_date(text: str) -> str | None:
    for pat in _DATE_PATS:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    if "اليوم" in text:
        return "اليوم"
    return None


def _heuristic_price_parse(text: str):
    """
    Returns a list of candidate tuples: (price, currency, karat or None)
    NOTE:
      - Guards against year-like numbers (e.g., 2024/2025).
      - For generic "<num> جنيه", requires gold context in the surrounding text.
    """
    out = []

    # 1) Prefer karat-specific matches
    for m in PAT_KARAT_THEN_PRICE.finditer(text):
        karat = int(m.group("karat"))
        num = normalize_number(m.group("price"))
        if num is None or _looks_like_year(num):
            continue  # ignore invalid or year-like numbers
        out.append((num, "جنيه", karat))

    for m in PAT_PRICE_THEN_KARAT.finditer(text):
        karat = int(m.group("karat"))
        num = normalize_number(m.group("price"))
        if num is None or _looks_like_year(num):
            continue
        out.append((num, "جنيه", karat))

    if out:
        return out  # List of tuples: (price, currency, karat)

    # 2) Fall back: number + currency (no karat), but require gold context
    for m in PAT_PRICE_CURR.finditer(text):
        if not _has_gold_context(text):
            continue
        num = normalize_number(m.group(1))
        if num is None or _looks_like_year(num):
            continue
        curr = m.group(0)[len(m.group(1)) :].strip()
        out.append((num, curr, None))

    # 3) Last resort: number near "جرام" (assume EGP)
    if not out:
        for m in PAT_GRAM_21_24.finditer(text):
            num = normalize_number(m.group(1))
            if num is None or _looks_like_year(num):
                continue
            # If the pattern mentions 21/24 implicitly, infer karat from match
            karat = 21 if "21" in m.group(0) else (24 if "24" in m.group(0) else None)
            out.append((num, "جنيه", karat))

    return out


def _score_snippet(snippet: str) -> int:
    """Heuristic: prefer text that mentions gram/karat or table-like blocks."""
    score = 0
    if "جرام" in snippet:
        score += 2
    if "عيار 21" in snippet or "عيار21" in snippet:
        score += 2
    if "عيار 24" in snippet or "عيار24" in snippet:
        score += 1
    if "سعر" in snippet:
        score += 1
    if "price" in snippet.lower():
        score += 1
    if "|" in snippet or "\t" in snippet:
        score += 1  # table-ish
    return score


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=2))
def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=12)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    return r.text


def fetch_and_extract_prices(
    links: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pages: List[Dict[str, Any]] = []
    prices: List[Dict[str, Any]] = []

    for url in links:
        try:
            html = _get(url)
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else url

            best_pair = None
            best_score = -1
            best_text = ""

            candidates = _extract_candidates(soup)
            for txt in candidates:
                score = _score_snippet(txt)
                pairs = _heuristic_price_parse(txt)
                if pairs:
                    # take the first pair in the best-scoring snippet
                    if score > best_score:
                        best_score = score
                        best_pair = pairs[0]
                        best_text = txt  # keep text for context flags

            pages.append({"url": url, "title": title, "ok": True})
            if best_pair:
                price_val, currency, karat = best_pair

                # Flags derived from the best snippet's text
                has_making = any(
                    w in best_text for w in ("مصنعية", "بالمصنعية", "شاملة المصنعية")
                )
                published_hint = _maybe_find_date(best_text)

                prices.append(
                    {
                        "site": url,
                        "title": title,
                        "price": price_val,
                        "currency": currency,  # EGP variants only, by pattern
                        "karat": karat,  # 18/21/24 or None
                        "unit": "جرام",  # clarity
                        "with_making": has_making,
                        "published_hint": published_hint,
                    }
                )
        except Exception as e:
            pages.append({"url": url, "ok": False, "error": str(e)})

    return pages, prices
