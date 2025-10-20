from __future__ import annotations
from typing import Optional
import re
from datetime import datetime
import pytz

# Arabic-Indic digits → Western
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Precompiled helpers
_WS = re.compile(r"\s+")
# Extract the first plausible numeric token (keeps digits, separators, and sign)
_NUM_TOKEN = re.compile(r"[+-]?\d[\d\s.,\u066B\u066C]*")


def _standardize_separators(s: str) -> str:
    """
    Normalize decimal/thousands separators safely:
    - Convert Arabic-Indic digits.
    - Remove NBSP.
    - If both ',' and '.' appear -> ',' is thousands, '.' is decimal (drop commas).
    - If only ',' appears -> treat it as decimal (replace with '.').
    - Always drop Arabic thousands '٬' (U+066C).
    - Convert Arabic decimal '٫' (U+066B) to '.'.
    """
    s = s.translate(_ARABIC_DIGITS)
    s = s.replace("\xa0", " ")  # NBSP → space
    s = s.replace("\u066b", ".")  # Arabic decimal → '.'
    s = s.replace("\u066c", "")  # Arabic thousands → remove
    s = _WS.sub("", s)  # remove all spaces

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # e.g., "3,500.75" -> drop commas (thousands), keep dot as decimal
        s = s.replace(",", "")
    elif has_comma and not has_dot:
        # e.g., "12,5" (decimal comma) -> use dot
        s = s.replace(",", ".")
    # else: only dot or neither -> fine
    return s


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def normalize_number(text: str) -> Optional[float]:
    """
    Robustly parse a float from messy Arabic/English numeric text.
    Examples handled:
      - "٣,٥٠٠" -> 3500.0
      - "3,500.75" -> 3500.75
      - "12,5 جنيه" -> 12.5
      - "EGP 4,250" -> 4250.0
      - "٦٠٫٢" -> 60.2
    Returns None if no numeric token is found.
    """
    if not text:
        return None

    # Try direct clean of the whole string
    cleaned = _standardize_separators(text.strip())
    val = _to_float(cleaned)
    if val is not None:
        return val

    # Fallback: extract the first numeric-looking token and try again
    m = _NUM_TOKEN.search(text)
    if not m:
        return None

    token = _standardize_separators(m.group(0))
    return _to_float(token)


def now_cairo() -> datetime:
    return datetime.now(pytz.timezone("Africa/Cairo"))
