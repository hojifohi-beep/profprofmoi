# -*- coding: utf-8 -*-
"""
DZ Product Finder - لوحة اكتشاف المنتجات الرابحة (COD الجزائر)
تشغيل:  streamlit run app.py
"""
import io
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, quote

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

DB_PATH = "monopoly_finder.db"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ar,fr;q=0.8,en;q=0.5",
}

# قائمة الكلمات المفتاحية الـ 100 المخصصة للسوق الجزائري
KEYWORDS_100 = [
    "عرض لفترة محدودة", "احصل على قطعتين", "خصم 50%", "الكمية جد محدودة", "اطلب قطعتين والثانية",
    "المنتج الأصلي", "ضمان لمدة سنة", "السعر الجديد", "تخفيض استثنائي", "هدية مجانية",
    "استفد من العرض", "قبل نفاد الكمية", "أطلب الآن واستفد", "باك اقتصادي", "عرض العيد",
    "توفير حصري", "الأكثر مبيعاً", "السعر الأصلي", "عرض خاص جداً", "احصل عليه اليوم",
    "حل مشكلة", "تخلص من", "سهل الاستخدام", "بدون عناء", "توفير المساحة",
    "مضاد للماء", "مضاد للانزلاق", "تنظيف عميق", "أداة ذكية", "حماية كاملة",
    "بديل احترافي", "تصميم عصري", "متعدد الاستخدامات", "قابل للطي", "بدون حفر",
    "نتيجة فورية", "توفير الوقت", "مقاوم الصدمات", "تقنية حديثة", "حجم مصغر",
    "مشد ظهر", "مصحح القامة", "جهاز مساج", "فرشاة حرارية", "آلة إزالة الشعر",
    "سيروم علاج", "كريم تبييض", "مساج محمول", "تخفيف آلام", "آلة حلاقة احترافية",
    "مشد جسم", "عناية بالبشرة", "تبييض الأسنان", "تكثيف الشعر", "جهاز تنظيف الوجه",
    "حزام تخسيس", "مقشر طبيعي", "مساج للقدمين", "زيت طبيعي", "علاج المفاصل",
    "فرامة كهربائية", "قاطعة الخضار", "ممسحة سحرية", "منظم مطبخ", "منظم ملابس",
    "إضاءة استشعار", "حامل ذكي", "أداة ضغط", "وعاء حافظ للحرارة", "مطحنة توابل",
    "موزع ماء أوتوماتيكي", "منظم ثلاجة", "مقلاة هوائية", "بخاخ زيت", "رفوف تنظيم",
    "غطاء سيليكون", "ماكينة خياطة محمولة", "أداة تنظيف الزجاج", "عصارة فواكه", "منظم حمام",
    "حامل هاتف للسيارة", "منفاخ عجلات", "كاميرا مراقبة", "بخاخ تنظيف المحرك", "سماعات لاسلكية",
    "شاحن سريع", "مضخة غسيل السيارات", "غطاء سيارة", "جهاز تتبع", "إضاءة LED للسيارة",
    "معطر سيارة آلي", "منظم مقعد السيارة", "ساعة ذكية", "مكبر صوت بلوتوث", "أداة فحص الأعطال",
    "عازل حراري", "شريط إضاءة ذكي", "حامل أيباد", "محول كهرباء للسيارة", "قفل ذكي"
]

st.set_page_config(page_title="DZ Product Finder", page_icon="📦", layout="wide")
st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; text-align: right; }
    .stDataFrame, .stCode, code, pre { direction: ltr; text-align: left; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ───────────────────────── 1) الحماية والأسرار ─────────────────────────
def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def check_password() -> None:
    required = secret("APP_PASSWORD")
    if not required:
        return
    entered = st.sidebar.text_input("🔒 كلمة المرور", type="password", key="pwd")
    if entered != required:
        st.info("أدخل كلمة المرور في الشريط الجانبي للمتابعة.")
        st.stop()


check_password()

st.sidebar.header("⚙️ الإعدادات")
DEEPSEEK_KEY = secret("DEEPSEEK_API_KEY") or st.sidebar.text_input(
    "DeepSeek API Key (طوارئ)", type="password", key="ds_manual"
)
META_TOKEN = secret("META_ACCESS_TOKEN") or st.sidebar.text_input(
    "Meta Access Token (اختياري)", type="password", key="meta_manual"
)


# ───────────────────────── 7) قاعدة البيانات ─────────────────────────
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE, store TEXT, platform TEXT, title TEXT,
                ad_age_days INTEGER, ad_copies INTEGER,
                stock INTEGER, stock_note TEXT,
                intent_ratio REAL, top_questions TEXT,
                risk_score REAL, risk_reasons TEXT,
                price REAL, wholesale REAL, delivery REAL, ad_cost REAL,
                delivery_rate REAL, return_fee REAL,
                break_even REAL, net_profit REAL,
                opportunity_index REAL, updated_at TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT, stock INTEGER, ts TEXT
            )"""
        )


init_db()


def upsert_product(rec: dict) -> None:
    cols = list(rec.keys())
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "url")
    with db() as c:
        c.execute(
            f"INSERT INTO products ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(url) DO UPDATE SET {updates}",
            [rec[k] for k in cols],
        )


# ───────────────────────── 2) مصدر الإعلانات ─────────────────────────
def parse_date(s: str):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00")[:25])
    except ValueError:
        try:
            d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def age_days(start) -> int:
    d = parse_date(start)
    if not d:
        return 0
    return max((datetime.now(timezone.utc) - d).days, 0)


def fetch_ads_api(keywords, token, limit=200):
    rows, err = [], None
    for kw in keywords:
        try:
            r = requests.get(
                "https://graph.facebook.com/v19.0/ads_archive",
                params={
                    "access_token": token,
                    "search_terms": kw,
                    "ad_reached_countries": json.dumps(["DZ"]),
                    "ad_active_status": "ACTIVE",
                    "fields": "page_name,ad_delivery_start_time,ad_creative_link_captions,"
                    "ad_creative_link_titles,ad_snapshot_url",
                    "limit": min(limit, 100),
                },
                timeout=30,
            )
            data = r.json()
            if "error" in data:
                err = data["error"].get("message", "خطأ غير معروف من Meta")
                continue
            for ad in data.get("data", []):
                caps = ad.get("ad_creative_link_captions") or []
                rows.append(
                    {
                        "store": ad.get("page_name", ""),
                        "url": ("https://" + caps[0]) if caps else "",
                        "start": ad.get("ad_delivery_start_time", ""),
                        "snapshot": ad.get("ad_snapshot_url", ""),
                    }
                )
        except Exception as e:
            err = str(e)
    return rows, err


def filter_and_group(rows, min_age=7):
    groups = {}
    for r in rows:
        key = r.get("url") or r.get("store")
        if not key:
            continue
        g = groups.setdefault(
            key, {"url": r.get("url", ""), "store": r.get("store", ""), "copies": 0, "oldest": None}
        )
        g["copies"] += 1
        d = parse_date(r.get("start"))
        if d and (g["oldest"] is None or d < g["oldest"]):
            g["oldest"] = d
    out = []
    for g in groups.values():
        a = age_days(g["oldest"].isoformat()) if g["oldest"] else 0
        if a >= min_age:
            out.append({**g, "age_days": a})
    return sorted(out, key=lambda x: (x["age_days"], x["copies"]), reverse=True)


# ───────────────────────── 3) استخراج المتجر والمخزون ─────────────────────────
STOCK_KEYS = ("inventory_quantity", "stock", "stock_quantity", "inventory", "quantity", "inventoryLevel")


def json_after(html: str, marker: str):
    i = html.find(marker)
    if i < 0:
        return None
    j = html.find("{", i)
    if j < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[j:])
        return obj
    except Exception:
        return None


def find_key(obj, keys):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys:
                if isinstance(v, dict) and "value" in v:
                    v = v["value"]
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    pass
        for v in obj.values():
            r = find_key(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, keys)
            if r is not None:
                return r
    return None


def detect_platform(html: str) -> str:
    low = html.lower()
    if "youcan" in low:
        return "YouCan"
    if "storeino" in low:
        return "Storeino"
    if "cdn.shopify" in low or "shopify" in low:
        return "Shopify"
    return "غير معروف"


def extract_store(url: str) -> dict:
    res = {"platform": "غير معروف", "title": "", "price": None, "stock": None, "error": None}
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
    except Exception as e:
        res["error"] = f"تعذر فتح الرابط: {e}"
        return res
    html = r.text
    res["platform"] = detect_platform(html)
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "Product":
                res["title"] = res["title"] or it.get("name", "")
                offers = it.get("offers")
                if isinstance(offers, list) and offers:
                    offers = offers[0]
                if isinstance(offers, dict):
                    try:
                        res["price"] = res["price"] or float(offers.get("price"))
                    except (TypeError, ValueError):
                        pass
                    lvl = find_key(offers, ("inventoryLevel",))
                    if lvl is not None and res["stock"] is None:
                        res["stock"] = lvl

    for marker in (
        "window.YouCanData",
        "window.storeino.product",
        "window.storeino",
        "var meta =",
        "window.ShopifyAnalytics",
    ):
        obj = json_after(html, marker)
        if obj is not None and res["stock"] is None:
            res["stock"] = find_key(obj, STOCK_KEYS)
        if obj is not None and not res["title"]:
            t = find_key_str(obj, ("title", "name"))
            if t:
                res["title"] = t

    if res["stock"] is None and res["platform"] == "Shopify" and "/products/" in url:
        try:
            pj = requests.get(url.split("?")[0].rstrip("/") + ".js", headers=UA, timeout=15).json()
            res["stock"] = find_key(pj.get("variants", []), ("inventory_quantity",))
            res["title"] = res["title"] or pj.get("title", "")
            if res["price"] is None and pj.get("price") is not None:
                res["price"] = float(pj["price"]) / 100
        except Exception:
            pass

    if not res["title"] and soup.title:
        res["title"] = soup.title.get_text(strip=True)
    return res


def find_key_str(obj, keys):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            r = find_key_str(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key_str(v, keys)
            if r:
                return r
    return None


def stock_delta(url: str, new_stock):
    if new_stock is None:
        return {"sales_est": None, "note": "لا توجد بيانات مخزون"}
    with db() as c:
        row = c.execute(
            "SELECT stock FROM stock_history WHERE url=? ORDER BY id DESC LIMIT 1", (url,)
        ).fetchone()
        c.execute(
            "INSERT INTO stock_history (url, stock, ts) VALUES (?,?,?)",
            (url, int(new_stock), datetime.now(timezone.utc).isoformat()),
        )
    if row is None:
        return {"sales_est": None, "note": "أول قياس — أعد الفحص لاحقاً لتقدير المبيعات"}
    prev = row["stock"]
    drop = prev - new_stock
    if drop < 0:
        return {"sales_est": 0, "note": f"إعادة تخزين ({prev} → {new_stock})"}
    if prev >= 1000 and drop >= 500 and drop / prev >= 0.3:
        return {"sales_est": None, "note": f"قفزة مشبوهة ({prev} → {new_stock}) = تعديل أدمين، تم تجاهلها"}
    return {"sales_est": drop, "note": f"انخفاض {drop} قطعة منذ آخر فحص ({prev} → {new_stock})"}


# ───────────────────────── 4+5) DeepSeek ─────────────────────────
def deepseek_json(system: str, user: str):
    if not DEEPSEEK_KEY:
        return None, "مفتاح DeepSeek غير متوفر"
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content), None
    except Exception as e:
        return None, str(e)


INTENT_SYS = (
    "أنت محلل تعليقات تجارة إلكترونية في الجزائر. التعليقات بالدارجة الجزائرية والفرنسية والعربية. "
    "نية الشراء الصريحة = سؤال عن السعر (شحال، بشحال، combien)، طلب (حاب نطلب، نحب نشري)، "
    "سؤال عن التوصيل لولاية، أو طلب رقم/طريقة الطلب. "
    'أرجع JSON فقط بالشكل: {"intent_ratio": رقم بين 0 و1, "top_questions": ["...","...","..."]}'
)
RISK_SYS = (
    "أنت محلل مخاطر المرتجعات في الدفع عند الاستلام بالجزائر. حلل نصوص الشكاوى "
    "(منتج مختلف عن الصورة، جودة رديئة، تأخر التوصيل، رفض الاستلام، عدم رد الموصل...). "
    'أرجع JSON فقط: {"risk_score": رقم من 1.0 إلى 10.0, "reasons": ["..."]}'
)


def analyze_intent(comments: list[str]):
    if not comments:
        return None, [], "لا توجد تعليقات"
    data, err = deepseek_json(INTENT_SYS, "\n".join(f"- {c}" for c in comments[:150]))
    if not data:
        return None, [], err
    ratio = data.get("intent_ratio")
    try:
        ratio = float(ratio)
        ratio = ratio / 100 if ratio > 1 else ratio
        ratio = min(max(ratio, 0.0), 1.0)
    except (TypeError, ValueError):
        ratio = None
    return ratio, list(data.get("top_questions", []))[:3], None


def analyze_risk(complaints: list[str]):
    if not complaints:
        return None, [], "لا توجد شكاوى"
    data, err = deepseek_json(RISK_SYS, "\n".join(f"- {c}" for c in complaints[:100]))
    if not data:
        return None, [], err
    try:
        score = min(max(float(data.get("risk_score")), 1.0), 10.0)
    except (TypeError, ValueError):
        return None, [], "تعذر تحليل التقييم"
    return score, list(data.get("reasons", []))[:5], None


# ───────────────────────── 6) الحاسبة المالية ─────────────────────────
def financials(price, wholesale, delivery, ad_cost, delivery_rate, return_fee):
    d = min(max(delivery_rate, 0.0), 1.0)
    unit_margin = price - wholesale - delivery
    break_even = d * unit_margin - (1 - d) * return_fee
    net = break_even - ad_cost
    return {"unit_margin": unit_margin, "break_even": break_even, "net_profit": net}


def opportunity_index(age, copies, intent, risk, break_even):
    s = min(age / 30, 1) * 25 + min(copies / 5, 1) * 15
    s += (intent if intent is not None else 0.0) * 25
    s += min(max(break_even / 3000, 0), 1) * 25
    s += ((10 - risk) / 10 * 10) if risk is not None else 5
    return round(s, 1)


# ───────────────────────── الواجهة ─────────────────────────
st.title("📦 DZ Product Finder")
st.caption("اكتشاف المنتجات الرابحة في الجزائر (COD) — إعلانات ▸ متجر ▸ دارجة ▸ مالية")

# حفظ/استرجاع قاعدة البيانات
st.sidebar.divider()
st.sidebar.subheader("💾 قاعدة البيانات")
try:
    with open(DB_PATH, "rb") as f:
        st.sidebar.download_button("⬇️ تنزيل monopoly_finder.db", f.read(), file_name=DB_PATH)
except FileNotFoundError:
    pass
up = st.sidebar.file_uploader("⬆️ استرجاع قاعدة بيانات", type=["db"], key="dbup")
if up is not None and st.sidebar.button("استرجاع الآن"):
    with open(DB_PATH, "wb") as f:
        f.write(up.getvalue())
    st.sidebar.success("تم الاسترجاع.")
    st.rerun()

tab_disc, tab_one, tab_res = st.tabs(["🔎 الاكتشاف", "🧪 تحليل منتج", "📊 النتائج"])

# ── تبويب الاكتشاف ──
with tab_disc:
    st.markdown(
        "**مصدر الإعلانات:** Meta Ad Library API الرسمي، أو الاستيراد اليدوي / البحث المباشر.\n"
        "ملاحظة: الـ API الرسمي يغطي الإعلانات التجاريّة خارج أوروبا بشكل محدود. الخيار اليدوي يمنحك روابط بحث مباشرة ومجانية في مكتبة الإعلانات."
    )
    min_age = st.number_input("الحد الأدنى لعمر الإعلان (أيام)", 1, 90, 7)
    src = st.radio("المصدر", ["البحث المباشر والاستيراد اليدوي (موصى به)", "Meta Ad Library API"], horizontal=True)
    rows = []
    
    if src == "Meta Ad Library API":
        kws = st.text_area("الكلمات المفتاحية (سطر لكل كلمة)", "\n".join(KEYWORDS_100[:5])).splitlines()
        if st.button("🚀 ابدأ المسح عبر API"):
            if not META_TOKEN:
                st.error("أدخل META_ACCESS_TOKEN في الشريط الجانبي أو استعمل خيار البحث المباشر.")
            else:
                with st.spinner("جارٍ الاستعلام..."):
                    rows, err = fetch_ads_api([k for k in kws if k.strip()], META_TOKEN)
                if err:
                    st.warning(f"Meta: {err}")
                if not rows:
                    st.info("لا نتائج من API Meta. استخدم خيار «البحث المباشر والاستيراد اليدوي».")
    else:
        st.subheader("🔎 مولد روابط البحث المباشرة في Meta Ads Library")
        col_k1, col_k2 = st.columns([2, 1])
        with col_k1:
            selected_kw = st.selectbox("اختر كلمة مفتاحية من الـ 100 كلمة المجهزة للجزائر:", KEYWORDS_100)
        
        encoded_kw = quote(selected_kw)
        search_link = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=DZ&q={encoded_kw}"
        
        with col_k2:
            st.write(" ")
            st.write(" ")
            st.markdown(f'<a href="{search_link}" target="_blank"><button style="background-color:#1877F2;color:white;border:none;padding:10px 18px;border-radius:8px;cursor:pointer;font-weight:bold;width:100%;">🔗 فتح الكلمة في Meta Ads Library</button></a>', unsafe_allow_html=True)
        
        st.markdown(f"> 💡 **الرابط المباشر:** [اضغط هنا للفتح المباشر لكلمة '{selected_kw}' في الجزائر]({search_link})")
        st.divider()

        st.subheader("📥 استيراد بيانات الإعلانات المكتشفة")
        st.caption("الأعمدة المطلوبة: url, store, start (YYYY-MM-DD) — صف لكل نسخة إعلانية.")
        csv_up = st.file_uploader("ملف CSV", type=["csv"], key="adscsv")
        pasted = st.text_area("أو الصق CSV هنا", "url,store,start\n", height=120)
        try:
            df_in = pd.read_csv(csv_up) if csv_up else pd.read_csv(io.StringIO(pasted))
            rows = df_in.fillna("").to_dict("records")
        except Exception as e:
            if csv_up or (pasted and len(pasted.strip().splitlines()) > 1):
                st.error(f"تعذرت قراءة الجدول: {e}")

    if rows:
        grouped = filter_and_group(rows, min_age)
        st.success(f"{len(grouped)} حملة معمّرة (≥ {min_age} أيام) من أصل {len(rows)} إعلان")
        st.session_state["candidates"] = grouped
        
    cands = st.session_state.get("candidates", [])
    if cands:
        st.dataframe(pd.DataFrame(cands), use_container_width=True)
        if st.button("⚙️ افحص مخزون كل المرشحين أوتوماتيكياً"):
            prog = st.progress(0.0)
            for i, c in enumerate(cands):
                if c["url"]:
                    info = extract_store(c["url"])
                    d = stock_delta(c["url"], info["stock"])
                    upsert_product(
                        {
                            "url": c["url"], "store": c["store"], "platform": info["platform"],
                            "title": info["title"], "ad_age_days": c["age_days"],
                            "ad_copies": c["copies"], "stock": info["stock"], "stock_note": d["note"],
                            "price": info["price"],
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                prog.progress((i + 1) / len(cands))
                time.sleep(1)
            st.success("تم الحفظ. أكمل التحليل من تبويب «تحليل منتج».")

# ── تبويب تحليل منتج ──
with tab_one:
    url = st.text_input("رابط صفحة الهبوط", key="one_url")
    c1, c2, c3 = st.columns(3)
    price = c1.number_input("سعر البيع (دج)", 0.0, value=0.0, step=100.0)
    wholesale = c2.number_input("سعر الجملة (دج)", 0.0, value=0.0, step=100.0)
    delivery = c3.number_input("التوصيل (دج)", 0.0, value=600.0, step=50.0)
    c4, c5, c6 = st.columns(3)
    ad_cost = c4.number_input("تكلفة الإعلان لكل طلب (دج)", 0.0, value=1000.0, step=100.0)
    d_rate = c5.slider("نسبة الاستلام %", 0, 100, 100) / 100
    ret_fee = c6.number_input("تكلفة شحن الرجوع (دج)", 0.0, value=400.0, step=50.0)
    ad_age = st.number_input("عمر الإعلان (أيام)", 0, 365, 0)
    ad_copies = st.number_input("عدد النسخ الإعلانية", 0, 100, 1)
    comments_txt = st.text_area("تعليقات الإعلان/المنشور (سطر لكل تعليق)", height=140)
    complaints_txt = st.text_area("شكاوى/مراجعات سلبية (اختياري)", height=100)

    if st.button("🧮 حلّل"):
        if not url:
            st.error("أدخل الرابط.")
            st.stop()
        with st.spinner("فحص المتجر..."):
            info = extract_store(url)
        if info["error"]:
            st.warning(info["error"])
        d = stock_delta(url, info["stock"])
        p = price or info["price"] or 0.0
        fin = financials(p, wholesale, delivery, ad_cost, d_rate, ret_fee)
        with st.spinner("تحليل الدارجة عبر DeepSeek..."):
            intent, qs, ierr = analyze_intent([x for x in comments_txt.splitlines() if x.strip()])
            risk, reasons, rerr = analyze_risk([x for x in complaints_txt.splitlines() if x.strip()])
        idx = opportunity_index(ad_age, ad_copies, intent, risk, fin["break_even"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("مؤشر الفرصة", f"{idx}/100")
        m2.metric("نقطة التعادل CPA", f"{fin['break_even']:.0f} دج")
        m3.metric("الربح الصافي/طلب", f"{fin['net_profit']:.0f} دج")
        m4.metric("نية الشراء", f"{intent*100:.0f}%" if intent is not None else "غير محدد")
        if fin["break_even"] < 1200:
            st.warning("⚠️ نقطة التعادل أقل من 1200 دج: هامش ضيق جداً أمام تكلفة إعلان واقعية.")
        st.write(f"**المنصة:** {info['platform']} | **المنتج:** {info['title'] or '—'} | **المخزون:** "
                 f"{info['stock'] if info['stock'] is not None else 'غير متاح'} — {d['note']}")
        if qs:
            st.write("**أبرز الاستفسارات:**", " • ".join(qs))
        if ierr and intent is None:
            st.caption(f"نية الشراء: {ierr}")
        st.write("**خطر المرتجعات:**", f"{risk:.1f}/10" if risk is not None else "غير محدد")
        if reasons:
            st.write("الأسباب:", " • ".join(reasons))

        upsert_product(
            {
                "url": url, "store": urlparse(url).netloc, "platform": info["platform"],
                "title": info["title"], "ad_age_days": ad_age, "ad_copies": ad_copies,
                "stock": info["stock"], "stock_note": d["note"],
                "intent_ratio": intent, "top_questions": json.dumps(qs, ensure_ascii=False),
                "risk_score": risk, "risk_reasons": json.dumps(reasons, ensure_ascii=False),
                "price": p, "wholesale": wholesale, "delivery": delivery, "ad_cost": ad_cost,
                "delivery_rate": d_rate, "return_fee": ret_fee,
                "break_even": fin["break_even"], "net_profit": fin["net_profit"],
                "opportunity_index": idx,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        st.success("تم الحفظ في قاعدة البيانات.")

# ── تبويب النتائج ──
with tab_res:
    with db() as c:
        df = pd.read_sql_query("SELECT * FROM products ORDER BY opportunity_index DESC", c)
    if df.empty:
        st.info("لا توجد نتائج بعد.")
    else:
        st.dataframe(df, use_container_width=True)
        e1, e2 = st.columns(2)
        e1.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8-sig"), "report.csv", "text/csv")
        e2.download_button(
            "⬇️ JSON", df.to_json(orient="records", force_ascii=False), "report.json", "application/json"
        )
    
