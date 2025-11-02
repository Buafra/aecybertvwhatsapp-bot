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

# Payment links (set these!)
PREMIUM_PAY_URL   = os.environ.get("PREMIUM_PAY_URL",   "https://example.com/pay/premium")
EXECUTIVE_PAY_URL = os.environ.get("EXECUTIVE_PAY_URL", "https://example.com/pay/executive")
CASUAL_PAY_URL    = os.environ.get("CASUAL_PAY_URL",    "https://example.com/pay/casual")
KIDS_PAY_URL      = os.environ.get("KIDS_PAY_URL",      "https://example.com/pay/kids")

# Optional admin alert via Telegram
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN")  # Telegram bot token (optional)
ADMIN_CHAT_ID   = os.environ.get("ADMIN_CHAT_ID")    # Telegram chat id (optional, int or str)

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
            lang TEXT
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
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE users SET last_seen_utc=?, lang=? WHERE wa_number=?",
                    (now_iso(), lang, wa_number))
    else:
        cur.execute("INSERT INTO users (wa_number, first_seen_utc, last_seen_utc, lang) VALUES (?,?,?,?)",
                    (wa_number, now_iso(), now_iso(), lang))
    con.commit()
    con.close()

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
        log.info("Admin alert skipped (no ADMIN_BOT_TOKEN/ADMIN_CHAT_ID). Message: %s", text)
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

# ------------------------- Content -------------------------
OFFERS_EN = (
    "🎁 *AECyberTV Plans*\n"
    "• *Premium* — 12 months — UHD/4K — Stable & fastest\n"
    f"  Pay: {PREMIUM_PAY_URL}\n"
    "• *Executive* — 12 months — Full sports — High stability\n"
    f"  Pay: {EXECUTIVE_PAY_URL}\n"
    "• *Casual* — 12 months — Essentials\n"
    f"  Pay: {CASUAL_PAY_URL}\n"
    "• *Kids* — 12 months — Safe kids channels\n"
    f"  Pay: {KIDS_PAY_URL}\n\n"
    "Type: *buy premium*, *buy executive*, *buy casual*, *buy kids*"
)

OFFERS_AR = (
    "🎁 *باقات AECyberTV*\n"
    "• *Premium* — 12 شهر — UHD/4K — أسرع وأثبت أداءً\n"
    f"  الدفع: {PREMIUM_PAY_URL}\n"
    "• *Executive* — 12 شهر — رياضة كاملة — ثبات عالي\n"
    f"  الدفع: {EXECUTIVE_PAY_URL}\n"
    "• *Casual* — 12 شهر — القنوات الأساسية\n"
    f"  الدفع: {CASUAL_PAY_URL}\n"
    "• *Kids* — 12 شهر — قنوات آمنة للأطفال\n"
    f"  الدفع: {KIDS_PAY_URL}\n\n"
    "اكتب: *buy premium* أو *buy executive* أو *buy casual* أو *buy kids*"
)

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

SUPPORT_EN = "🛠 Support: please describe your issue; we’ll assist shortly."
SUPPORT_AR = "🛠 الدعم الفني: صف المشكلة وسنساعدك قريباً."

DIDNT_GET_EN = "I didn’t get that. Reply 1 / 2 / 3, or type 'start'."
DIDNT_GET_AR = "لم أفهم. أرسل 1 / 2 / 3 أو اكتب 'start'."

# ------------------------- Routes -------------------------
@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "service": "aecybertv-whatsapp-twilio"}, 200

@app.route("/webhook", methods=["GET", "POST"])
@app.route("/webhook/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "OK", 200

    form = request.form.to_dict()  # Twilio Sandbox uses form-encoded
    log.info("Inbound: %s", form)
    from_value = form.get("From", "") or ""
    body_raw = (form.get("Body") or "").strip()
    from_number = from_value.replace("whatsapp:", "") if from_value else None
    if not from_number:
        return ("", 200)

    # Language + user bookkeeping
    lang = "ar" if is_arabic(body_raw) else "en"
    upsert_user(from_number, lang)

    body = body_raw.lower()

    # --------- MENU / START ----------
    if body in ("start", "hi", "hello", "مرحبا", "السلام عليكم", "ابدأ", "menu", "القائمة"):
        send_whatsapp(from_number, f"{WELCOME_AR if lang=='ar' else WELCOME_EN}\n—\n{WELCOME_EN if lang=='ar' else WELCOME_AR}")
        return ("", 200)

    # --------- OFFERS ----------
    if body in ("1", "١", "offers", "العروض"):
        send_whatsapp(from_number, f"{OFFERS_AR if lang=='ar' else OFFERS_EN}\n—\n{OFFERS_EN if lang=='ar' else OFFERS_AR}")
        return ("", 200)

    # --------- TRIAL ----------
    if body in ("2", "٢", "trial", "free", "free trial", "تجربة", "تجربة مجانية"):
        send_whatsapp(from_number, f"{TRIAL_AR if lang=='ar' else TRIAL_EN}\n—\n{TRIAL_EN if lang=='ar' else TRIAL_AR}")
        return ("", 200)

    # If user sends contact/email after trial prompt
    if re.search(r"@.+\.", body_raw) or re.search(r"\+?\d{7,}", body_raw):
        # treat as contact lead
        save_lead(from_number, body_raw, source="trial")
        send_whatsapp(from_number,
            "✅ Received. Trial request is being processed.\n"
            "🕘 You’ll get activation details shortly.\n"
            "✅ تم الاستلام. يتم الآن معالجة طلب التجربة.\n"
            "🕘 ستصلك تفاصيل التفعيل قريباً."
        )
        notify_admin(f"[AECyberTV WhatsApp] Trial lead\nFrom: {from_number}\nContact: {body_raw}")
        return ("", 200)

    # --------- SUPPORT ----------
    if body in ("3", "٣", "support", "دعم", "الدعم", "الدعم الفني"):
        send_whatsapp(from_number, f"{SUPPORT_AR if lang=='ar' else SUPPORT_EN}\n—\n{SUPPORT_EN if lang=='ar' else SUPPORT_AR}")
        return ("", 200)

    # --------- BUY INTENTS ----------
    if body.startswith("buy "):
        plan = body.replace("buy ", "").strip()
        plan_map = {
            "premium": PREMIUM_PAY_URL,
            "executive": EXECUTIVE_PAY_URL,
            "casual": CASUAL_PAY_URL,
            "kids": KIDS_PAY_URL
        }
        pay_url = plan_map.get(plan)
        if pay_url:
            save_order(from_number, plan, status="initiated")
            send_whatsapp(from_number,
                f"🧾 {plan.title()} selected.\nPay here: {pay_url}\n"
                f"بعد الدفع، أرسل لقطة الشاشة لتفعيل الحساب.\n"
            )
            notify_admin(f"[AECyberTV WhatsApp] Order started\nFrom: {from_number}\nPlan: {plan}\nLink: {pay_url}")
        else:
            send_whatsapp(from_number, "Unknown plan. Try: buy premium / executive / casual / kids")
        return ("", 200)

    # --------- FALLBACK ----------
    send_whatsapp(from_number, f"{DIDNT_GET_AR if lang=='ar' else DIDNT_GET_EN}\n—\n{DIDNT_GET_EN if lang=='ar' else DIDNT_GET_AR}")
    return ("", 200)

# ------------------------- Entrypoint -------------------------
if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", "8000"))
    log.info("Starting server on 0.0.0.0:%s", port)
    serve(app, host="0.0.0.0", port=port)
