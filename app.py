# -*- coding: utf-8 -*-
"""
DZ Product Finder - لوحة اكتشاف المنتجات الرابحة (COD الجزائر - Shopify Dedicated & Smart Extractor)
تشغيل:  streamlit run app.py
"""
import io
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse, quote, parse_qs, unquote

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

st.set_page_config(page_title="DZ Product Finder - Shopify Dedicated", page_icon="🛍️", layout="wide")
st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; text-align: right; }
    .stDataFrame, .stCode, code, pre { direction: ltr; text-align: left; }
    </style>
    """,
    unsafe_allow_html=True,
)


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


st.sidebar.header("⚙️ الإعدادات والتحكم")
DEEPSEEK_KEY = secret("DEEPSEEK_API_KEY") or st.sidebar.text_input(
    "DeepSeek API Key", type="password", key="ds_manual"
)
SHOPIFY_ONLY_FILTER = st.sidebar.checkbox("حظر واستبعاد غير متاجر Shopify تلقائياً 🛡️", value=True)


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
                quality_score REAL, effectiveness_notes TEXT,
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
        existing_cols = [row["name"] for row in c.execute("PRAGMA table_info(products)").fetchall()]
        new_columns = {
            "quality_score": "REAL",
            "effectiveness_notes": "TEXT",
            "price": "REAL",
            "wholesale": "REAL",
            "delivery": "REAL",
            "ad_cost": "REAL",
            "delivery_rate": "REAL",
            "return_fee": "REAL",
            "break_even": "REAL",
            "net_profit": "REAL",
            "opportunity_index": "REAL",
            "updated_at": "TEXT"
        }
        for col_name, col_type in new_columns.items():
            if col_name not in existing_cols:
                try:
                    c.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass


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


STOCK_KEYS = ("inventory_quantity", "stock", "stock_quantity", "inventory", "quantity", "inventoryLevel")


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


def detect_shopify_strictly(html: str, url: str) -> tuple[bool, str]:
    low_html = html.lower()
    low_url = url.lower()

    if "youcan.shop" in low_url or "window.youcandata" in low_html or "youcan-cdn" in low_html:
        return False, "YouCan"
    if "storeino.com" in low_url or "window.storeino" in low_html:
        return False, "Storeino"
    if "wp-content" in low_html or "woocommerce" in low_html:
        return False, "WooCommerce"

    shopify_signatures = [
        "cdn.shopify.com",
        "myshopify.com",
        "window.shopifyanalytics",
        "shopify.theme",
        "shopify.pay",
        "booster-page-speed-optimizer",
        "shopify-assets",
        "cdn.shopify",
    ]

    for sig in shopify_signatures:
        if sig in low_html or sig in low_url:
            return True, "Shopify"

    try:
        domain = urlparse(url).netloc
        scheme = urlparse(url).scheme or "https"
        cart_res = requests.get(f"{scheme}://{domain}/cart.json", headers=UA, timeout=8)
        if cart_res.status_code == 200 and "token" in cart_res.text and "items" in cart_res.text:
            return True, "Shopify"
    except Exception:
        pass

    return False, "غير معروف / منصة أخرى"


def extract_store(url: str) -> dict:
    res = {"platform": "غير معروف", "title": "", "price": None, "stock": None, "error": None, "raw_text": "", "is_shopify": False}
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
    except Exception as e:
        res["error"] = f"تعذر فتح الرابط: {e}"
        return res

    html = r.text
    is_shopify, platform_name = detect_shopify_strictly(html, url)
    res["platform"] = platform_name
    res["is_shopify"] = is_shopify

    soup = BeautifulSoup(html, "html.parser")
    res["raw_text"] = soup.get_text(separator=" ", strip=True)[:2000]

    if is_shopify and "/products/" in url:
        try:
            js_url = url.split("?")[0].rstrip("/") + ".js"
            pj = requests.get(js_url, headers=UA, timeout=12).json()
            res["stock"] = find_key(pj.get("variants", []), ("inventory_quantity",))
            res["title"] = pj.get("title", "")
            if pj.get("price") is not None:
                res["price"] = float(pj["price"]) / 100
        except Exception:
            pass

    if not res["title"] or res["price"] is None:
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

    if not res["title"] and soup.title:
        res["title"] = soup.title.get_text(strip=True)
    return res


def stock_delta(url: str, new_stock):
    if new_stock is None:
        return {"sales_est": None, "note": "لا توجد بيانات مخزون مقتطعة"}
    with db() as c:
        row = c.execute(
            "SELECT stock FROM stock_history WHERE url=? ORDER BY id DESC LIMIT 1", (url,)
        ).fetchone()
        c.execute(
            "INSERT INTO stock_history (url, stock, ts) VALUES (?,?,?)",
            (url, int(new_stock), datetime.now(timezone.utc).isoformat()),
        )
    if row is None:
        return {"sales_est": None, "note": "أول قياس للمخزون"}
    prev = row["stock"]
    drop = prev - new_stock
    if drop < 0:
        return {"sales_est": 0, "note": f"تجديد المخزون ({prev} → {new_stock})"}
    return {"sales_est": drop, "note": f"انخفاض {drop} قطعة ({prev} → {new_stock})"}


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


QUALITY_SYS = (
    "أنت خبير تجارة إلكترونية بالدفع عند الاستلام (COD) في الجزائر. "
    "حلل عنوان وصفحة المنتج وقيم جودة وفكرته ومقومات نجاحه الإعلاني. "
    'أرجع JSON فقط: {"quality_score": رقم من 1.0 إلى 10.0, "notes": "ملخص فكرة المنتج وميزته التنافسية"}'
)


def analyze_product_quality(title: str, text_content: str):
    if not DEEPSEEK_KEY:
        return 7.0, "تم التقييم افتراضياً (أدخل مفتاح DeepSeek للتقييم الدقيق)"
    data, err = deepseek_json(QUALITY_SYS, f"عنوان المنتج: {title}\nنص الصفحة: {text_content[:1500]}")
    if not data:
        return 6.5, f"تعذر التحليل التفصيلي: {err}"
    try:
        score = min(max(float(data.get("quality_score")), 1.0), 10.0)
    except (TypeError, ValueError):
        score = 7.0
    return score, str(data.get("notes", "تحليل عام لمنتج Shopify"))


def financials(price, wholesale, delivery, ad_cost, delivery_rate, return_fee):
    d = min(max(delivery_rate, 0.0), 1.0)
    unit_margin = price - wholesale - delivery
    break_even = d * unit_margin - (1 - d) * return_fee
    net = break_even - ad_cost
    return {"unit_margin": unit_margin, "break_even": break_even, "net_profit": net}


def opportunity_index(quality_score, break_even):
    s = (quality_score / 10.0) * 50.0 + min(max(break_even / 3000.0, 0), 1) * 50.0
    return round(s, 1)


# ───────────────────────── دالة استخراج وتصفية روابط Shopify الذكية من الإعلانات ─────────────────────────
EXCLUDE_DOMAINS = [
    "facebook.com", "fb.me", "instagram.com", "whatsapp.com", "wa.me",
    "youtube.com", "google.com", "t.me", "telegram.me", "tiktok.com"
]


def clean_and_unmask_url(url_str: str) -> str:
    """فك روابط إعادة توجيه فيسبوك المفرغة (l.facebook.com)"""
    if "l.facebook.com/l.php" in url_str or "lm.facebook.com/l.php" in url_str:
        parsed = urlparse(url_str)
        qs = parse_qs(parsed.query)
        if "u" in qs:
            return unquote(qs["u"][0])
    return url_str


def extract_shopify_urls_from_raw_text(raw_text: str) -> list[str]:
    """
    استخراج الروابط من أي نص إعلاني مع فك التشفير وتصفية المنصات الاجتماعية.
    """
    url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+|[a-zA-Z0-9.-]+\.(?:com|shop|store|net|site|online|storeino|youcan)/[^\s<>"]*'
    found_urls = re.findall(url_pattern, raw_text)

    candidate_urls = []
    seen = set()

    for u in found_urls:
        if not u.startswith("http"):
            u = "https://" + u

        u = clean_and_unmask_url(u)
        domain = urlparse(u).netloc.lower()

        # استبعاد منصات التواصل
        if any(ex in domain for ex in EXCLUDE_DOMAINS):
            continue

        if u not in seen:
            seen.add(u)
            candidate_urls.append(u)

    # دعم الذكاء الاصطناعي DeepSeek لاستخراج الروابط غير المباشرة المكتوبة كنصوص
    if DEEPSEEK_KEY and len(candidate_urls) == 0 and len(raw_text.strip()) > 20:
        ai_sys = 'أنت أداة استخراج روابط تجارة إلكترونية. أخرج جميع روابط المتاجر الإلكترونية أو الدومينات المذكورة في النص بالشكل: {"urls": ["https://..."]}'
        ai_data, _ = deepseek_json(ai_sys, raw_text[:2500])
        if ai_data and isinstance(ai_data.get("urls"), list):
            for u in ai_data["urls"]:
                if isinstance(u, str) and u.startswith("http") and u not in seen:
                    candidate_urls.append(u)

    return candidate_urls


# ───────────────────────── الواجهة الرئيسية ─────────────────────────
st.title("🛍️ DZ Product Finder — Shopify Dedicated Engine")
st.caption("أداة استهداف واكتشاف إعلانات ومتاجر Shopify فقط في الجزائر مع الفحص الفني والتحليل المالي")

st.sidebar.divider()
st.sidebar.subheader("💾 قاعدة البيانات")
try:
    with open(DB_PATH, "rb") as f:
        st.sidebar.download_button("⬇️ تنزيل monopoly_finder.db", f.read(), file_name=DB_PATH)
except FileNotFoundError:
    pass

tab_links, tab_extractor, tab_batch, tab_res = st.tabs([
    "🔗 روابط Meta Ads بفلترة Shopify",
    "🧠 مستخرج روابط Shopify من الإعلانات والنصوص", 
    "⚡ الفحص الفني الحاسم والتحليل بالذكاء الاصطناعي", 
    "📊 قاعدة البيانات والنتائج المحفوظة"
])

# ── تبويب 1: روابط Meta Ads ──
with tab_links:
    st.subheader("🎯 روابط بحث مصممة لاستهداف Shopify حصراً")
    st.info(
        "💡 **سبب ظهور YouCan و Storeino عند البحث بـ `/products/`:** منصات YouCan و Storeino تستخدم نفس هيكلة المسار `/products/` في الروابط! "
        "لذلك، الخيار الأول أدناه يدمج الكلمة مع `'myshopify.com'` لضمان ظهور إعلانات شوبيفاي فقط في Meta Ads Library."
    )

    col_mode, col_filter = st.columns([2, 2])
    with col_mode:
        search_mode = st.radio(
            "اختر صيغة الاستهداف في فيسبوك:",
            [
                "استهداف نطاق شوبيفاي الصريح (myshopify.com) — الأضمن 🌟",
                "استهداف مسار الشراء (checkouts)",
                "استهداف مسار المنتجات العام (/products/)"
            ],
            horizontal=False
        )
    with col_filter:
        search_kw = st.text_input("🔍 تصفية القائمة بكلمة محددة:", "", placeholder="مثلاً: سيارة، مشد، منظم...")

    shopify_links_data = []
    for idx, kw in enumerate(KEYWORDS_100, 1):
        if not search_kw or search_kw.strip().lower() in kw.lower():
            if search_mode == "استهداف نطاق شوبيفاي الصريح (myshopify.com) — الأضمن 🌟":
                query_str = f"{kw} myshopify.com"
            elif search_mode == "استهداف مسار الشراء (checkouts)":
                query_str = f"{kw} checkouts"
            else:
                query_str = f"{kw} /products/"

            encoded = quote(query_str)
            link_url = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=DZ&q={encoded}"

            shopify_links_data.append({
                "الرقم": idx,
                "الكلمة المفتاحية": kw,
                "استعلام البحث الموجه": query_str,
                "رابط Meta Ads Library 🔗": link_url
            })

    df_links = pd.DataFrame(shopify_links_data)

    st.dataframe(
        df_links,
        column_config={
            "رابط Meta Ads Library 🔗": st.column_config.LinkColumn(
                "رابط البحث المباشر للجزائر 🚀",
                display_text="فتح نتائج فيسبوك 🛒"
            )
        },
        use_container_width=True,
        hide_index=True
    )

# ── تبويب 2: مستخرج روابط Shopify الذكي من الإعلانات والنصوص (الجديد 🚀) ──
with tab_extractor:
    st.subheader("🧠 استخراج وتصفية روابط Shopify المخبأة داخل الإعلانات والنصوص")
    st.markdown(
        """انسخ **جميع نصوص الإعلانات**، أو **كود صفحة Meta Ads Library**، أو **قائمة روابط متعددة مختلطة** والصقها أدناه. 
        سيتكفل الذكاء الاصطناعي مع كود Regex بـ:
        1. استخراج جميع الروابط الحقيقية واستبعاد روابط التواصل الاجتماعي (فيسبوك، واتساب، إنستغرام).
        2. فك التشفير عن روابط إعادة التوجيه المفرغة (`l.facebook.com`).
        3. **فحص الكود البرمجي للمتاجر المستخرجة وإبقاء متاجر Shopify المؤكدة فقط!**"""
    )

    raw_ad_content = st.text_area(
        "ضع محتوى الإعلانات / الروابط المنسوخة من فيسبوك هنا:",
        placeholder="مثال:\nاشتري الآن من متجرنا: https://l.facebook.com/l.php?u=https://brand.myshopify.com/products/item\nأو زورا موقعنا: www.store.com/products/cooler",
        height=180
    )

    if st.button("🔍 استخراج وتصفية متاجر Shopify الذكية"):
        if not raw_ad_content.strip():
            st.warning("يرجى لصق نص الإعلانات أو الروابط أولاً.")
        else:
            with st.spinner("جاري تحليل النص، فك الروابط، وفحص المنصات البرمجية للمتاجر..."):
                extracted_candidates = extract_shopify_urls_from_raw_text(raw_ad_content)

                if not extracted_candidates:
                    st.error("لم يتم العثور على أي روابط متاجر خارجية في النص المنسوخ.")
                else:
                    st.info(f"تم العثور على {len(extracted_candidates)} رابط مرشح. جاري التحقق الفني من منصة Shopify...")

                    verified_shopify = []
                    rejected_stores = []

                    for cand in extracted_candidates:
                        is_shop, plat = detect_shopify_strictly("", cand)
                        if is_shop:
                            verified_shopify.append(cand)
                        else:
                            rejected_stores.append({"الرابط": cand, "المنصة": plat})

                    st.success(f"✅ تم اكتشاف {len(verified_shopify)} متجر Shopify مؤكد!")

                    if verified_shopify:
                        st.subheader("🛒 متاجر Shopify المكتشفة الجاهزة للفحص:")
                        st.code("\n".join(verified_shopify), language="text")

                        if st.button("⚡ نقل المتاجر المكتشفة إلى الفحص الآلي والجرف المالي"):
                            st.session_state["auto_urls_input"] = "\n".join(verified_shopify)
                            st.success("تم نقل الروابط بنجاح إلى تبويب 'الفحص الفني'! انتقل للتبويب التالي لتشغيل التحليل.")

                    if rejected_stores:
                        with st.expander("🚫 المتاجر المستبعدة (منصات أخرى وليست Shopify):"):
                            st.dataframe(pd.DataFrame(rejected_stores), use_container_width=True)

# ── تبويب 3: الفحص الجرفي والذكاء الاصطناعي ──
with tab_batch:
    st.subheader("📥 إدخال روابط المتاجر المكتشفة من الإعلانات")
    st.write("أدخل الروابط المكتشفة هنا. وسيقوم النظام بالفحص التقني للكود لاستبعاد أي متجر ليس Shopify تلقائياً:")

    default_urls = st.session_state.get("auto_urls_input", "")
    urls_input = st.text_area(
        "قائمة الروابط (سطر لكل رابط):",
        value=default_urls,
        placeholder="https://brand-store.com/products/item-1\nhttps://example.myshopify.com/products/item-2",
        height=140
    )

    col_c1, col_c2 = st.columns(2)
    est_wholesale = col_c1.number_input("تقدير نسبة الجملة من سعر البيع %", value=35, min_value=10, max_value=80)
    est_deliv_rate = col_c2.slider("تقدير نسبة الاستلام (Delivery Rate) %", value=75, min_value=10, max_value=100)

    if st.button("🚀 بدء الفحص التقني والجرف والتحليل بالذكاء الاصطناعي"):
        urls_list = [u.strip() for u in urls_input.splitlines() if u.strip()]
        if not urls_list:
            st.warning("يرجى إدخال رابط واحد على الأقل.")
        else:
            prog = st.progress(0.0)
            status_box = st.empty()
            saved_count = 0
            skipped_count = 0

            for i, u in enumerate(urls_list):
                status_box.info(f"جاري الفحص التقني للمتجر ({i+1}/{len(urls_list)}): {u}")

                info = extract_store(u)

                if SHOPIFY_ONLY_FILTER and not info["is_shopify"]:
                    skipped_count += 1
                    status_box.warning(f"🚫 تم استبعاد {u} (المنصة المكتشفة: {info['platform']} - ليست Shopify)")
                    time.sleep(0.6)
                    prog.progress((i + 1) / len(urls_list))
                    continue

                q_score, q_notes = analyze_product_quality(info["title"], info["raw_text"])

                d = stock_delta(u, info["stock"])
                p = info["price"] or 3500.0
                wholesale_val = p * (est_wholesale / 100.0)
                fin = financials(p, wholesale=wholesale_val, delivery=600, ad_cost=1000, delivery_rate=est_deliv_rate/100.0, return_fee=400)
                opp_idx = opportunity_index(q_score, fin["break_even"])

                upsert_product({
                    "url": u,
                    "store": urlparse(u).netloc or "Shopify Store",
                    "platform": "Shopify",
                    "title": info["title"] or "منتج Shopify",
                    "stock": info["stock"],
                    "stock_note": d["note"],
                    "price": p,
                    "wholesale": wholesale_val,
                    "delivery": 600,
                    "ad_cost": 1000,
                    "delivery_rate": est_deliv_rate / 100.0,
                    "return_fee": 400,
                    "quality_score": q_score,
                    "effectiveness_notes": q_notes,
                    "break_even": fin["break_even"],
                    "net_profit": fin["net_profit"],
                    "opportunity_index": opp_idx,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                saved_count += 1
                prog.progress((i + 1) / len(urls_list))
                time.sleep(0.8)

            status_box.success(f"🎉 تم الفحص! تم حفظ {saved_count} منتج Shopify مؤكد (وتم استبعاد {skipped_count} متجر غير شوبيفاي).")

# ── تبويب 4: عرض النتائج والقاعدة ──
with tab_res:
    st.header("📊 مركز النتائج وقاعدة البيانات (`monopoly_finder.db`)")

    with db() as c:
        df_db = pd.read_sql_query("SELECT * FROM products WHERE platform='Shopify' ORDER BY opportunity_index DESC", c)

    if df_db.empty:
        st.info("لا توجد منتجات شوبيفاي محفوظة حتى الآن.")
    else:
        st.subheader("📋 قائمة المنتجات المكتشفة")

        # عرض الجدول بتهيئة مخصصة للروابط والأسماء والوصف
        st.dataframe(
            df_db,
            column_config={
                "url": st.column_config.LinkColumn("رابط Shopify 🔗", display_text="فتح المتجر 🛒"),
                "title": st.column_config.TextColumn("اسم المنتج 📦", width="medium"),
                "effectiveness_notes": st.column_config.TextColumn("وصف وتحليل AI 💡", width="large"),
                "price": st.column_config.NumberColumn("السعر (دج)", format="%.0f دج"),
                "stock": st.column_config.NumberColumn("المخزون 📦"),
                "quality_score": st.column_config.NumberColumn("تقييم الجودة ⭐", format="%.1f / 10"),
                "opportunity_index": st.column_config.NumberColumn("مؤشر الفرصة 🔥", format="%.1f / 100"),
                "break_even": st.column_config.NumberColumn("Break-Even CPA", format="%.0f دج"),
                "updated_at": st.column_config.DatetimeColumn("تاريخ التحديث ⏱️")
            },
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        st.subheader("🔍 تفاصيل المنتجات والوصف الشامل")

        # عرض بطاقات تفصيلية تحتوي على الاسم، رابط Shopify المباشر، والوصف الكامل
        for idx, row in df_db.iterrows():
            title_disp = row.get("title") or "منتج بدون عنوان"
            opp_disp = row.get("opportunity_index") or 0
            with st.expander(f"📦 {title_disp} — (مؤشر الفرصة: {opp_disp})"):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**🔗 رابط Shopify:** [{row.get('url')}]({row.get('url')})")
                    st.markdown(f"**📝 الوصف والتحليل:** {row.get('effectiveness_notes') or 'لا يوجد وصف متاح'}")
                    if row.get('stock_note'):
                        st.caption(f"📊 حركة المخزون: {row.get('stock_note')}")
                with c2:
                    st.metric("السعر المعروض", f"{row.get('price', 0):,.0f} دج")
                    st.metric("مؤشر الفرصة", f"{row.get('opportunity_index', 0)} / 100")
                    st.metric("تقييم AI", f"{row.get('quality_score', 0)} / 10")

        st.divider()
        col_ex1, col_ex2 = st.columns(2)
        col_ex1.download_button("⬇️ تصدير CSV", df_db.to_csv(index=False).encode("utf-8-sig"), "shopify_products_report.csv", "text/csv")
        col_ex2.download_button("⬇️ تصدير JSON", df_db.to_json(orient="records", force_ascii=False), "shopify_products_report.json", "application/json")
