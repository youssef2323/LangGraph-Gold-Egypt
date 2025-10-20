from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv
from graph import build_graph

# NEW: for CSV export
import pandas as pd

load_dotenv()
st.set_page_config(
    page_title="تقرير أسعار الذهب اليوم", page_icon="🏅", layout="centered"
)
st.title("🏅 تقرير أسعار الذهب في مصر")
st.caption("يبحث تلقائيًا في الويب (عربي)، يستخلص الأسعار، ويولّد تقريرًا بالعربية")

with st.sidebar:
    st.header("الإعدادات")
    query = st.text_input("استعلام البحث", value="سعر الذهب اليوم")
    region = "EG"  # مصر فقط
    run_btn = st.button("تشغيل التحليل")

ph_links = st.empty()
ph_prices = st.empty()
ph_report = st.empty()

if run_btn:
    app = build_graph()
    state = {
        "query": query,
        "region": region,
        "links": [],
        "pages": [],
        "prices": [],
        "report": None,
    }

    with st.spinner("جارٍ تشغيل التحليل…"):
        saw_anything = False

        for cur in app.stream(state, stream_mode="values"):
            # ---------------- Links ----------------
            if cur.get("links"):
                saw_anything = True
                with ph_links.container():
                    st.subheader("الروابط التي تم العثور عليها")
                    for u in cur["links"]:
                        st.write(f"🔗 {u}")

            # ---------------- Prices ----------------
            if cur.get("prices"):
                saw_anything = True
                with ph_prices.container():
                    st.subheader("الأسعار المستخرجة (تجريبية)")

                    # Sort by karat if present (so 24/21/18 appear clearly)
                    data = cur["prices"]
                    try:
                        data = sorted(
                            data,
                            key=lambda p: (p.get("karat") is None, p.get("karat", 0)),
                        )
                    except Exception:
                        pass

                    # Show the raw extracted rows as a table
                    st.dataframe(data, use_container_width=True)

                    # ---- Quick summary by karat (EG only) ----
                    if region == "EG":
                        from collections import defaultdict

                        by_karat = defaultdict(list)
                        for p in data:
                            if p.get("karat") in (18, 21, 24) and p.get("currency") in (
                                "جنيه",
                                "جنيه مصري",
                                "ج.م",
                                "EGP",
                            ):
                                try:
                                    by_karat[p["karat"]].append(float(p["price"]))
                                except Exception:
                                    pass

                        if by_karat:
                            st.caption("ملخص سريع بالنطاقات (جنيه/جرام):")
                            for k in (24, 21, 18):
                                if by_karat.get(k):
                                    rng = (min(by_karat[k]), max(by_karat[k]))
                                    st.write(
                                        f"• عيار {k}: {int(rng[0])} – {int(rng[1])} جنيه"
                                    )

                    # ---- NEW: 21k split (بدون/بالمصنعية) if available ----
                    stats_wm = cur.get("stats_wm") or {}
                    w_key, wo_key = "21:with", "21:without"
                    has_split = (stats_wm.get(wo_key, {}).get("count", 0) > 0) or (
                        stats_wm.get(w_key, {}).get("count", 0) > 0
                    )
                    if has_split:
                        st.subheader("تفصيل عيار 21")
                        col1, col2 = st.columns(2)
                        with col1:
                            wo = stats_wm.get(wo_key, {})
                            if wo.get("count", 0) > 0:
                                st.markdown(
                                    f"**بدون مصنعية:** {int(wo['min'])} – {int(wo['max'])} جنيه (n={int(wo['count'])})"
                                )
                            else:
                                st.caption("بدون مصنعية: غير متاح")
                        with col2:
                            w = stats_wm.get(w_key, {})
                            if w.get("count", 0) > 0:
                                st.markdown(
                                    f"**بالمصنعية:** {int(w['min'])} – {int(w['max'])} جنيه (n={int(w['count'])})"
                                )
                            else:
                                st.caption("بالمصنعية: غير متاح")

                    # ---- NEW: CSV download for transparency ----
                    try:
                        df = pd.DataFrame(data)
                        st.download_button(
                            "تنزيل الأسعار كملف CSV",
                            df.to_csv(index=False).encode("utf-8-sig"),
                            file_name="gold_prices_eg.csv",
                            mime="text/csv",
                        )
                    except Exception:
                        pass

            # ---------------- Report ----------------
            if cur.get("report"):
                saw_anything = True
                with ph_report.container():
                    st.subheader("التقرير النهائي")
                    st.markdown(cur["report"])

                    # Optional: Let the user download the report as text
                    st.download_button(
                        "تنزيل التقرير كنص",
                        (cur["report"] or "").encode("utf-8"),
                        file_name="gold_report_eg.txt",
                        mime="text/plain",
                    )

        if not saw_anything:
            st.error("لم يتم الحصول على نتائج. حاول تغيير الاستعلام ثم أعد المحاولة.")

else:
    st.info('اضبط الإعدادات ثم اضغط "تشغيل التحليل".')
