from __future__ import annotations
from typing import List, Dict, Any, Tuple, Optional


def build_report_prompt(
    prices: List[Dict[str, Any]],
    links: List[str],
    region: str,
    timestamp: str,
    stats: Optional[Dict[int, Dict[str, float]]] = None,
) -> Tuple[str, str]:
    """
    Egypt-only, EGP-per-gram focused prompt with strict guardrails.
    - Ignores ounce/USD pages and non-Egypt country pages (e.g., Turkey).
    - Uses computed stats as authoritative (no invention / no conversion).
    - Produces a compact Arabic report with clear sections.
    """

    # ----------------------------
    # System: tone + HARD RULES
    # ----------------------------
    system = (
        "أنت خبير موثوق في أسواق الذهب في مصر. اكتب تقريراً عربياً واضحاً، موجزاً، وعملياً.\n"
        "اعتمد فقط على المعطيات المزوَّدة أدناه (الأسعار المستخرجة + الإحصائيات المحسوبة + الروابط).\n"
        "ممنوع اختلاق أرقام أو تحويل عملات/وحدات. إذا تعذّر الاستنتاج فاذكر ذلك صراحة.\n"
        "التزم بأن تكون جميع الأسعار بالجنيه المصري للجرام داخل مصر فقط."
    )

    # ----------------------------
    # Helper: format one extracted row
    # ----------------------------
    def fmt_price(p: Dict[str, Any]) -> str:
        title = p.get("title") or ""
        price = p.get("price", "")
        curr = p.get("currency") or ""
        karat = p.get("karat")
        karat_part = f" (عيار {karat})" if karat in (18, 21, 24) else ""
        site = p.get("site") or ""
        return f"- {title}{karat_part} → {price} {curr}\n  ({site})"

    # ----------------------------
    # Blocks: links / extracts / stats
    # ----------------------------
    price_lines = [fmt_price(p) for p in prices]
    extracted_block = (
        "\n".join(price_lines)
        if price_lines
        else "لم يتم استخراج أسعار مؤكدة من الصفحات. الرجاء مراجعة الروابط أدناه."
    )

    links_block = "\n".join(f"- {u}" for u in links) if links else "- لا توجد روابط."

    stats_lines: List[str] = []
    if stats:
        for k in (24, 21, 18):
            if k in stats and all(x in stats[k] for x in ("min", "max", "count")):
                s = stats[k]
                # Cast to int for tidy display; keep units explicit
                stats_lines.append(
                    f"- عيار {k}: {int(s['min'])} – {int(s['max'])} جنيه (n={int(s['count'])})"
                )
    stats_block = "\n".join(stats_lines) if stats_lines else "لا توجد إحصائيات محسوبة."

    region_label = "مصر" if region == "EG" else region

    # ----------------------------
    # User prompt: EXACT directions
    # ----------------------------
    user = f"""
المنطقة: {region_label}
الوقت المحلي: {timestamp}

# تعليمات مصر فقط (صارمة)
- اذكر الأسعار بالجنيه المصري **للجرام** فقط.
- تجاهل أي صفحة أو رقم يدل على:
  * عملات غير الجنيه المصري (مثل: USD/SAR/AED).
  * وحدات غير الجرام (مثل: أونصة/أوقية).
  * دول أخرى (مثل: تركيا، الخليج، ...).
- لا تقم بأي تحويلات عملة/وحدة، ولا تستنتج أسعار من عيارات أخرى.
- إذا لم تتوفر معطيات كافية، اكتب ذلك صراحة.

## الإحصائيات المحسوبة (مرجعية نهائية)
{stats_block}

## المعطيات المستخرجة (Raw Extracts)
{extracted_block}

## المطلوب من التقرير
1) **الملخص السريع (سطران بحد أقصى):** هل تُظهر البيانات استقراراً/ارتفاعاً/انخفاضاً اليوم داخل مصر؟ إذا تعذّر الاستنتاج، اكتب "غير حاسم".
2) **نطاق سعر جرام الذهب عيار 21 في {region_label}:** إذا كان مذكوراً في الإحصائيات أعلاه فـ**استخدمه كما هو حرفياً**. إن لم يكن موجوداً اكتب "غير متاح".
3) **ملاحظات اختلاف المصادر (حتى 3 نقاط):** اذكر أسباب الفروق الواضحة: اختلاف العيار (18/21/24)، اختلاف طريقة العرض، توقيت التحديث. تجاهل القيم الشاذة وغير المصرية.
4) **العوامل المؤثرة (سطران كحد أقصى):** عوامل عامة تؤثر على السوق المصري (الدولار مقابل الجنيه، أسعار الفائدة، التضخم المحلي...). بدون أرقام.
5) **اللغة والنبرة:** عربية فصيحة، مهنية، مختصرة، وبدون نصائح استثمارية.

## تنسيق الإخراج (استخدمه حرفياً)
### الملخص
- ...

### نطاق عيار 21
- ...

### ملاحظات اختلاف المصادر
- ...

### العوامل المؤثرة (مختصر)
- ...

### المصادر
{links_block}
"""
    return system, user
