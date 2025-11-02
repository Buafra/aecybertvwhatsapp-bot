# app.py
import os
from flask import Flask, request
from twilio.rest import Client

# --- Env vars ---
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")  # e.g., "whatsapp:+1415XXXXXXX"

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM):
    raise RuntimeError("Missing one of TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
app = Flask(__name__)

def send_whatsapp(to_number: str, body: str) -> None:
    """
    to_number: number without the 'whatsapp:' prefix, e.g., '+9715XXXXXXXX'
    """
    client.messages.create(
        from_=TWILIO_WHATSAPP_FROM,  # format: 'whatsapp:+1415XXXXXXX'
        to=f"whatsapp:{to_number}",
        body=body
    )

@app.route("/health", methods=["GET"])
def health():
    return {"ok": True, "service": "aecybertv-whatsapp-twilio"}, 200

@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Twilio Sandbox sends x-www-form-urlencoded payload by default.
    Useful keys:
      - From = 'whatsapp:+9715XXXXXX'
      - Body = 'text message'
    """
    data = request.form.to_dict()
    from_value = data.get("From", "")
    body = (data.get("Body") or "").strip()

    # Normalize sender
    from_number = from_value.replace("whatsapp:", "") if from_value else None
    if not from_number:
        return ("", 200)

    text_lc = body.lower()

    # --- Simple bilingual router (EN/AR) ---
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
            "• Premium — 12m — UHD/4K — ...\n"
            "• Executive — 12m — ...\n"
            "• Casual — 12m — ...\n"
            "• Kids — 12m — ...\n\n"
            "Reply 'buy premium' / 'buy executive' / ...\n"
            "أرسل 'premium شراء' أو اسم الباقة للشراء"
        )
    elif text_lc in ("2", "٢", "trial", "free", "free trial", "تجربة", "تجربة مجانية"):
        send_whatsapp(
            from_number,
            "✅ Free Trial (24h): please send your email or phone.\n"
            "✅ تجربة مجانية (24 ساعة): أرسل بريدك الإلكتروني أو رقم هاتفك."
        )
    elif text_lc in ("3", "٣", "support", "دعم", "الدعم", "الدعم الفني"):
        send_whatsapp(
            from_number,
            "🛠 Support: please describe your issue; we’ll assist shortly.\n"
            "🛠 الدعم الفني: صف المشكلة وسنقوم بالمساعدة قريباً."
        )
    elif text_lc.startswith("buy "):
        send_whatsapp(
            from_number,
            "🧾 Order received. We’ll contact you with payment & activation.\n"
            "🧾 تم استلام الطلب. سنتواصل معك لإتمام الدفع والتفعيل."
        )
    else:
        send_whatsapp(
            from_number,
            "I didn’t get that. Reply 1 / 2 / 3, or type 'start'.\n"
            "لم أفهم. أرسل 1 / 2 / 3 أو اكتب 'start'."
        )

    return ("", 200)

if __name__ == "__main__":
    # Waitress is recommended for production; Flask built-in for quick run.
    from waitress import serve
    port = int(os.environ.get("PORT", "8000"))
    serve(app, host="0.0.0.0", port=port)
