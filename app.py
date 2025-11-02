# app.py
import os
import logging
from flask import Flask, request
from twilio.rest import Client

# ------------------------- Logging -------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("aecybertv-whatsapp")

# ------------------------- Env Vars -------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g., "whatsapp:+14155238886"

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
    raise RuntimeError("Missing one of TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")

# ------------------------- App / Twilio Client -------------------------
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = Flask(__name__)

def send_whatsapp(to_number: str, body: str) -> None:
    """
    Sends a WhatsApp message via Twilio.
    to_number: phone in E.164 (e.g., +9715XXXXXXXX) WITHOUT 'whatsapp:' prefix.
    """
    try:
        client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,       # e.g., "whatsapp:+14155238886"
            to=f"whatsapp:{to_number}",
            body=body
        )
        log.info("Sent WhatsApp message to %s", to_number)
    except Exception as e:
        log.exception("Failed to send WhatsApp message to %s: %s", to_number, e)

# ------------------------- Routes -------------------------
@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "service": "aecybertv-whatsapp-twilio"}, 200

# Accept both GET and POST; also handle optional trailing slash
@app.route("/webhook", methods=["GET", "POST"])
@app.route("/webhook/", methods=["GET", "POST"])
def webhook():
    """
    Twilio Sandbox usually sends x-www-form-urlencoded with keys:
      From='whatsapp:+9715XXXXXXX'
      Body='message text'
    """
    if request.method == "GET":
        # Twilio may probe/validate; respond 200 to avoid warnings
        return "OK", 200

    # Log raw form for troubleshooting
    form = request.form.to_dict()
    log.info("Incoming webhook: method=%s form=%s", request.method, form)

    from_value = form.get("From", "") or ""
    body = (form.get("Body") or "").strip()
    from_number = from_value.replace("whatsapp:", "") if from_value else None

    if not from_number:
        log.warning("No 'From' found on inbound request.")
        return ("", 200)

    text_lc = body.lower()

    # ----------------- Simple bilingual menu/router -----------------
    if text_lc in ("start", "hi", "hello", "مرحبا", "السلام عليكم", "ابدأ", "start aecybertv"):
        send_whatsapp(
            from_number,
            "👋 Welcome to AECyberTV!\n\n"
            "1) Offers\n"
            "2) Free Trial (24h)\n"
            "3) Support\n\n"
            "Reply with: 1 / 2 / 3\n"
            "—\n"
            "👋 أهلاً بك في AECyberTV!\n\n"
            "١) العروض\n"
            "٢) تجربة مجانية (24 ساعة)\n"
            "٣) الدعم الفني\n\n"
            "أرسل: 1 / 2 / 3"
        )

    elif text_lc in ("1", "١", "offers", "العروض"):
        send_whatsapp(
            from_number,
            "🎁 Offers / العروض:\n"
            "• Premium — 12m — UHD/4K — …\n"
            "• Executive — 12m — …\n"
            "• Casual — 12m — …\n"
            "• Kids — 12m — …\n\n"
            "Reply 'buy premium' / 'buy executive' / 'buy casual' / 'buy kids'\n"
            "أرسل 'شراء premium' أو اسم الباقة"
        )

    elif text_lc in ("2", "٢", "trial", "free", "free trial", "تجربة", "تجربة مجانية"):
        send_whatsapp(
            from_number,
            "✅ Free Trial (24h): please send your email or phone to activate.\n"
            "✅ تجربة مجانية (24 ساعة): أرسل بريدك الإلكتروني أو رقم هاتفك للتفعيل."
        )

    elif text_lc in ("3", "٣", "support", "دعم", "الدعم", "الدعم الفني"):
        send_whatsapp(
            from_number,
            "🛠 Support: please describe your issue; we’ll assist shortly.\n"
            "🛠 الدعم الفني: صف المشكلة وسنساعدك قريباً."
        )

    elif text_lc.startswith("buy "):
        send_whatsapp(
            from_number,
            "🧾 Order received. We’ll contact you for payment & activation.\n"
            "🧾 تم استلام الطلب. سنتواصل معك لإتمام الدفع والتفعيل."
        )

    else:
        send_whatsapp(
            from_number,
            "I didn’t get that. Reply 1 / 2 / 3, or type 'start'.\n"
            "لم أفهم. أرسل 1 / 2 / 3 أو اكتب 'start'."
        )

    return ("", 200)

# ------------------------- Entrypoint -------------------------
if __name__ == "__main__":
    # Use Waitress in production; it binds to the PORT Render provides.
    from waitress import serve
    port = int(os.environ.get("PORT", "8000"))
    log.info("Starting server on 0.0.0.0:%s", port)
    serve(app, host="0.0.0.0", port=port)
