# app.py
import os
import re
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import Flask, request
from twilio.rest import Client

# ------------------------- Logging -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aecybertv-whatsapp")

# ------------------------- Env Vars -------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g., "whatsapp:+14155238886"

# Payment links (you must set these)
PREMIUM_PAY_URL   = os.environ.get("PREMIUM_PAY_URL",   "https://example.com/pay/premium")
EXECUTIVE_PAY_URL = os.environ.get("EXECUTIVE_PAY_URL", "https://example.com/pay/executive")
CASUAL_PAY_URL    = os.environ.get("CASUAL_PAY_URL",    "https://example.com/pay/casual")
KIDS_PAY_URL      = os.environ.get("KIDS_PAY_URL",      "https://example.com/pay/kids")

# Optional admin alert via Telegram
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN")
ADMIN_CHAT_ID   = os.environ.get("ADMIN_CHAT_ID")

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
    raise RuntimeError("Missing one of TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")

# ------------------------- App / Twilio Client -------------------------
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = Flask(__name__)

# ------------------------- Storage (SQLite) -------------------------
DB_PATH = Path("/tmp/aecybertv_whatsapp.sqlite3")

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_number TEXT UNIQUE,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            lang TEXT,
            state TEXT,
            pending_plan TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_number TEXT,
            contact TEXT,
            created_utc TEXT,
            source TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_number TEXT,
            plan TEXT,
            created_utc TEXT,
            status TEXT
        )
    """)
    con.commit()
    con.close()

def db_conn():
    return sqlite3.connect(DB_PATH)

init_db()

# ------------------------- Utils -------------------------
AR_REGEX = re.compile(r"[\u0600-\u06FF]")

def is_arabic(text: str) -> bool:
    return bool(AR_REGEX.search(text or ""))

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def upsert_user(wa_number: str, lang: str):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT wa_number FROM users WHERE wa_number = ?", (wa_number,))
    if cur.fetchone():
        cur.execute("UPDATE users SET last_seen_utc=?, lang=? WHERE wa_number=?",
                    (now_iso(), lang, wa_number))
    else:
        cur.execute(
            "INSERT INTO users (wa_number, first_seen_utc, last_seen_utc, lang, state, pending_plan) "
            "VALUES (?,?,?,?,?,?)",
            (wa_number, now_iso(), now_iso(), lang, None, None)
        )
    con.commit()
    con.close()

def set_user_state(wa_number: str, state: str | None, pending_plan: str | None = None):
    con = db_conn()
    cur = con.cursor()
    cur.execute("UPDATE users SET state=?, pending_plan=?, last_seen_utc=? WHERE wa_number=?",
                (state, pending_plan, now_iso(), wa_number))
    con.commit()
    con.close()

def get_user_state(wa_number: str):
    con = db_conn()
    cur = con.cursor()
    cur.execute("SELECT state, pending_plan, lang FROM users WHERE wa_number=?", (wa_number,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None, None, "en"
    return row[0], row[1], row[2] or "en"

def save_lead(wa_number: str, contact: str, source: str = "trial"):
    con = db_conn()
    cur = con.cursor()
    cur.execute("INSERT INTO leads (wa_number, contact, created_utc, source) VALUES (?,?,?,?)",
                (wa_number, contact, now_iso(), source))
    con.commit()
    con.close()

def save_order(wa_number: str, plan: str, status: str = "initiated"):
    con = db_conn()
    cur = con.cursor()
    cur.execute("INSERT INTO orders (wa_number, plan, created_utc, status) VALUES (?,?,?,?)",
                (wa_number, plan, now_iso(), status))
    con.commit()
    con.close()

def notify_admin(text: str):
    if not (ADMIN_BOT_TOKEN and ADMIN_CHAT_ID):
        log.info("Admin alert skipped. Message: %s", text)
        return
    try:
        url = f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": text}, timeout=10)
        r.raise_for_status()
        log.info("Admin alert sent.")
    except Exception as e:
        log.exception("Failed to send admin alert: %s", e)

def send_whatsapp(to_number: str, body: str):
    try:
        client.messages.create(from_=TWILIO_WHATSAPP_FROM, to=f"whatsapp:{to_number}", body=body)
        log.info("Sent WhatsApp -> %s", to_number)
    except Exception as e:
        log.exception("Failed to send WhatsApp to %s: %s", to_number, e)

# ------------------------- Package Catalog -------------------------
# Keywords include English + Arabic variants to map user replies to plans
PLAN_KEYWORDS = {
    "premium": {"aliases": {"premium", "بريميوم", "برميوم", "بر يميم"}},
    "executive": {"aliases": {"executive", "اكزكيوتيف", "إكزكيوتيف", "تنفيذي"}},
    "casual": {"aliases": {"casual", "كاجوال", "عادي"}},
    "kids": {"aliases": {"kids", "كيدز", "أطفال", "اطفال"}}
}

PLAN_PAY_URL = {
    "premium": PREMIUM_PAY_URL,
    "executive": EXECUTIVE_PAY_URL,
    "casual": CASUAL_PAY_URL,
    "kids": KIDS_PAY_URL
}

# Full descriptions (adjust text to match your Telegram copy if needed)
DESC_EN = {
    "premium":
        "🌟 Premium — 12 months\n"
        "• Best for: Live sports in UHD/4K + top movies/series\n"
        "• Stability: ★★★★★ (fastest servers)\n"
        "• Updates: Very frequent\n"
        "• Devices: Phones, tablets, Smart TV, TV boxes\n"
        "• Support: Priority\n",
    "executive":
        "💼 Executive — 12 months\n"
        "• Best for: All major sports + entertainment\n"
        "• Stability: ★★★★☆ (very stable)\n"
        "• Updates: Frequent\n"
        "• Devices: Phones, tablets, Smart TV, TV boxes\n"
        "• Support: Fast response\n",
    "casual":
        "👍 Casual — 12 months\n"
        "• Best for: Essentials & everyday channels\n"
        "• Stability: ★★★★☆ (stable)\n"
        "• Updates: Regular\n"
        "• Devices: Phones, tablets, Smart TV, TV boxes\n"
        "• Support: Standard\n",
    "kids":
        "🧒 Kids — 12 months\n"
        "• Best for: Safe kids channels & cartoons\n"
        "• Stability: ★★★★☆ (stable)\n"
        "• Updates: Regular\n"
        "• Devices: Phones, tablets, Smart TV, TV boxes\n"
        "• Parental-friendly selection\n"
}
DESC_AR = {
    "premium":
        "🌟 Premium — ١٢ شهر\n"
        "• الأفضل: قنوات الرياضة المباشرة بدقة UHD/4K + أفلام ومسلسلات مميزة\n"
        "• الثبات: ★★★★★ (أسرع وأثبت الخوادم)\n"
        "• التحديثات: متكررة جداً\n"
        "• الأجهزة: جوال، تابلت، تلفزيون ذكي، أجهزة TV Box\n"
        "• الدعم: أولوية عالية\n",
    "executive":
        "💼 Executive — ١٢ شهر\n"
        "• الأفضل: كل البطولات الرياضية + ترفيه شامل\n"
        "• الثبات: ★★★★☆ (ثبات ممتاز)\n"
        "• التحديثات: متكررة\n"
        "• الأجهزة: جوال، تابلت، تلفزيون ذكي، أجهزة TV Box\n"
        "• الدعم: سريع\n",
    "casual":
        "👍 Casual — ١٢ شهر\n"
        "• الأنسب: القنوات الأساسية والاستخدام اليومي\n"
        "• الثبات: ★★★★☆ (ثابت)\n"
        "• التحديثات: منتظمة\n"
        "• الأجهزة: جوال، تابلت، تلفزيون ذكي، أجهزة TV Box\n"
        "• الدعم: عادي\n",
    "kids":
        "🧒 Kids — ١٢ شهر\n"
        "• الأنسب: قنوات أطفال آمنة وكرتون\n"
        "• الثبات: ★★★★☆ (ثابت)\n"
        "• التحديثات: منتظمة\n"
        "• الأجهزة: جوال، تابلت، تلفزيون ذكي، أجهزة TV Box\n"
        "• محتوى مناسب للعائلة\n"
}

WELCOME_EN = (
    "👋 Welcome to AECyberTV!\n\n"
    "1) Offers\n"
    "2) Free Trial (24h)\n"
    "3) Support\n\n"
    "Reply with: 1 / 2 / 3"
)
WELCOME_AR = (
    "👋 أهلاً بك في AECyberTV!\n\n"
    "١) العروض\n"
    "٢) تجربة مجانية (24 ساعة)\n"
    "٣) الدعم الفني\n\n"
    "أرسل: 1 / 2 / 3"
)

TRIAL_EN = (
    "✅ Free Trial (24h): please send your *email or phone* to activate.\n"
    "Example: user@email.com or +9715xxxxxxx"
)
TRIAL_AR = (
    "✅ تجربة مجانية (24 ساعة): الرجاء إرسال *بريدك الإلكتروني أو رقم هاتفك* للتفعيل.\n"
    "مثال: user@email.com أو +9715xxxxxxx"
)

SUPPORT_PROMPT_EN = (
    "🛠 Support mode ON.\n"
    "Please type your issue now (screenshots description, device, player, channel)."
)
SUPPORT_PROMPT_AR = (
    "🛠 تم تفعيل وضع الدعم.\n"
    "الرجاء كتابة المشكلة الآن (وصف، جهازك، المشغل، القناة)."
)

SUPPORT_THANKS_EN = "✅ Thanks. Our team will review and reply shortly."
SUPPORT_THANKS_AR = "✅ شكراً لك. سيتم مراجعة طلبك والرد قريباً."

CHOOSE_PLAN_EN = (
    "Please reply with a package name:\n"
    "- premium\n- executive\n- casual\n- kids"
)
CHOOSE_PLAN_AR = (
    "الرجاء كتابة اسم الباقة:\n"
    "- premium\n- executive\n- casual\n- kids"
)

# ------------------------- Routes -------------------------
@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "service": "aecybertv-whatsapp-twilio"}, 200

@app.route("/webhook", methods=["GET", "POST"])
@app.route("/webhook/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200

    form = request.form.to_dict()
    log.info("Inbound: %s", form)
    from_value = form.get("From", "") or ""
    body_raw = (form.get("Body") or "").strip()
    from_number = from_value.replace("whatsapp:", "") if from_value else None
    if not from_number:
        return ("", 200)

    lang = "ar" if is_arabic(body_raw) else "en"
    upsert_user(from_number, lang)
    state, pending_plan, _ = get_user_state(from_number)
    body = body_raw.lower()

    # --------- START / MENU ---------
    if body in ("start", "hi", "hello", "مرحبا", "السلام عليكم", "ابدأ", "menu", "القائمة"):
        set_user_state(from_number, None, None)
        send_whatsapp(from_number, f"{WELCOME_AR if lang=='ar' else WELCOME_EN}\n—\n{WELCOME_EN if lang=='ar' else WELCOME_AR}")
        return ("", 200)

    # --------- SUPPORT FLOW ---------
    if body in ("3", "٣", "support", "دعم", "الدعم", "الدعم الفني"):
        set_user_state(from_number, "support_open", None)
        send_whatsapp(from_number, f"{SUPPORT_PROMPT_AR if lang=='ar' else SUPPORT_PROMPT_EN}")
        return ("", 200)

    if state == "support_open":
        # Treat ANY next message as the support issue
        save_lead(from_number, body_raw, source="support")
        notify_admin(f"[AECyberTV WhatsApp] SUPPORT\nFrom: {from_number}\nMsg: {body_raw}")
        set_user_state(from_number, None, None)
        send_whatsapp(from_number, f"{SUPPORT_THANKS_AR if lang=='ar' else SUPPORT_THANKS_EN}")
        return ("", 200)

    # --------- TRIAL FLOW ---------
    if body in ("2", "٢", "trial", "free", "free trial", "تجربة", "تجربة مجانية"):
        set_user_state(from_number, "awaiting_trial_contact", None)
        send_whatsapp(from_number, f"{TRIAL_AR if lang=='ar' else TRIAL_EN}")
        return ("", 200)

    if state == "awaiting_trial_contact":
        if re.search(r"@.+\.", body_raw) or re.search(r"\+?\d{7,}", body_raw):
            save_lead(from_number, body_raw, source="trial")
            notify_admin(f"[AECyberTV WhatsApp] TRIAL LEAD\nFrom: {from_number}\nContact: {body_raw}")
            set_user_state(from_number, None, None)
            send_whatsapp(from_number,
                "✅ Received. Trial request is being processed.\n"
                "🕘 You’ll get activation details shortly.\n"
                "✅ تم الاستلام. يتم الآن معالجة طلب التجربة.\n"
                "🕘 ستصلك تفاصيل التفعيل قريباً."
            )
        else:
            send_whatsapp(from_number, f"{TRIAL_AR if lang=='ar' else TRIAL_EN}")
        return ("", 200)

    # --------- OFFERS + PACKAGE CHOICE ---------
    if body in ("1", "١", "offers", "العروض"):
        # Show FULL descriptions, then ask user to choose a package name
        msg_parts = []
        for plan in ("premium", "executive", "casual", "kids"):
            msg_parts.append((DESC_AR if lang=='ar' else DESC_EN)[plan])
        msg_parts.append(CHOOSE_PLAN_AR if lang=='ar' else CHOOSE_PLAN_EN)
        send_whatsapp(from_number, "\n".join(msg_parts))
        set_user_state(from_number, "awaiting_package_choice", None)
        return ("", 200)

    if state == "awaiting_package_choice":
        # Map user text to a plan
        chosen = None
        for plan, meta in PLAN_KEYWORDS.items():
            if body in meta["aliases"] or any(alias in body for alias in meta["aliases"]):
                chosen = plan
                break
        if chosen:
            set_user_state(from_number, None, chosen)
            # Immediately send pay link for the chosen plan
            pay_url = PLAN_PAY_URL.get(chosen)
            save_order(from_number, chosen, status="initiated")
            notify_admin(f"[AECyberTV WhatsApp] ORDER STARTED\nFrom: {from_number}\nPlan: {chosen}\nLink: {pay_url}")
            send_whatsapp(
                from_number,
                (DESC_AR if lang=='ar' else DESC_EN)[chosen]
                + ("\nادفع هنا: " if lang=='ar' else "\nPay here: ")
                + f"{pay_url}\n"
                + ("بعد الدفع، أرسل لقطة الشاشة للتفعيل." if lang=='ar' else "After payment, send a screenshot for activation.")
            )
        else:
            send_whatsapp(from_number, f"{CHOOSE_PLAN_AR if lang=='ar' else CHOOSE_PLAN_EN}")
        return ("", 200)

    # --------- BUY COMMAND (direct) ---------
    if body.startswith("buy "):
        plan = body.replace("buy ", "").strip()
        # find closest match
        normalized = None
        for p, meta in PLAN_KEYWORDS.items():
            if plan in meta["aliases"]:
                normalized = p
                break
        if not normalized and plan in PLAN_PAY_URL:
            normalized = plan
        if normalized:
            pay_url = PLAN_PAY_URL.get(normalized)
            save_order(from_number, normalized, status="initiated")
            notify_admin(f"[AECyberTV WhatsApp] ORDER STARTED\nFrom: {from_number}\nPlan: {normalized}\nLink: {pay_url}")
            send_whatsapp(
                from_number,
                (DESC_AR if lang=='ar' else DESC_EN)[normalized]
                + ("\nادفع هنا: " if lang=='ar' else "\nPay here: ")
                + f"{pay_url}\n"
                + ("بعد الدفع، أرسل لقطة الشاشة للتفعيل." if lang=='ar' else "After payment, send a screenshot for activation.")
            )
        else:
            send_whatsapp(from_number, f"{CHOOSE_PLAN_AR if lang=='ar' else CHOOSE_PLAN_EN}")
        return ("", 200)

    # --------- FALLBACK ---------
    send_whatsapp(
        from_number,
        ("لم أفهم. أرسل 1 / 2 / 3 أو اكتب 'start'." if lang=='ar' else "I didn’t get that. Reply 1 / 2 / 3, or type 'start'.")
    )
    return ("", 200)

# ------------------------- Entrypoint -------------------------
if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "8000"))
    log.info("Starting server on 0.0.0.0:%s", port)
    serve(app, host="0.0.0.0", port=port)
