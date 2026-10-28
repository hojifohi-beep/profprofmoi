# -*- coding: utf-8 -*-
"""
DZ Product Finder - لوحة اكتشاف المنتجات الرابحة (COD الجزائر - Shopify Dedicated)
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
    """
    فحص دقيق ومؤكد 100% للتأكد من أن المتجر يتبع منصة Shopify
    ويستبعد تماماً YouCan و Storeino و WooCommerce.
    """
    low_html = html.lower()
    low_url = url.lower()

    # استبعاد صريح لمنصات YouCan و Storeino
    if "youcan.shop" in low_url or "window.youcandata" in low_html or "youcan-cdn" in low_html:
        return False, "YouCan"
    if "storeino.com" in low_url or "window.storeino" in low_html:
        return False, "Storeino"
    if "wp-content" in low_html or "woocommerce" in low_html:
        return False, "WooCommerce"

    # بصمات Shopify الحصرية المؤكدة
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

    # فحص إضافي عبر طلب cart.json الخاص بـ Shopify فقط
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

tab_links, tab_batch, tab_res = st.tabs([
    "🔗 روابط Meta Ads بفلترة Shopify الحصرية", 
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

# ── تبويب 2: الفحص الجرفي والذكاء الاصطناعي ──
with tab_batch:
    st.subheader("📥 إدخال روابط المتاجر المكتشفة من الإعلانات")
    st.write("أدخل الروابط المكتشفة هنا. وسيقوم النظام بالفحص التقني للكود لاستبعاد أي متجر ليس Shopify تلقائياً:")
    
    urls_input = st.text_area(
        "قائمة الروابط (سطر لكل رابط):",
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
                
                # 1. جرف المتجر والفحص التقني المؤكد
                info = extract_store(u)
                
                # 2. الاستبعاد الصريح إذا لم يكن المتجر Shopify
                if SHOPIFY_ONLY_FILTER and not info["is_shopify"]:
                    skipped_count += 1
                    status_box.warning(f"🚫 تم استبعاد {u} (المنصة المكتشفة: {info['platform']} - ليست Shopify)")
                    time.sleep(0.6)
                    prog.progress((i + 1) / len(urls_list))
                    continue
                
                # 3. تحليل جودة وفعالية المنتج عبر DeepSeek
                q_score, q_notes = analyze_product_quality(info["title"], info["raw_text"])
                
                # 4. الحسابات المالية وتتبع المخزون
                d = stock_delta(u, info["stock"])
                p = info["price"] or 3500.0
                wholesale_val = p * (est_wholesale / 100.0)
                fin = financials(p, wholesale=wholesale_val, delivery=600, ad_cost=1000, delivery_rate=est_deliv_rate/100.0, return_fee=400)
                opp_idx = opportunity_index(q_score, fin["break_even"])
                
                # 5. الحفظ في SQLite
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

# ── تبويب 3: عرض النتائج والقاعدة ──
with tab_res:
    st.header("📊 قاعدة البيانات والمنتجات المحفوظة (`monopoly_finder.db`)")
    with db() as c:
        df_db = pd.read_sql_query("SELECT * FROM products WHERE platform='Shopify' ORDER BY opportunity_index DESC", c)
        
    if df_db.empty:
        st.info("لا توجد منتجات شوبيفاي محفوظة حتى الآن.")
    else:
        st.dataframe(df_db, use_container_width=True)
        col_ex1, col_ex2 = st.columns(2)
        col_ex1.download_button("⬇️ تصدير CSV", df_db.to_csv(index=False).encode("utf-8-sig"), "shopify_report.csv", "text/csv")
        col_ex2.download_button("⬇️ تصدير JSON", df_db.to_json(orient="records", force_ascii=False), "shopify_report.json", "application/json")
