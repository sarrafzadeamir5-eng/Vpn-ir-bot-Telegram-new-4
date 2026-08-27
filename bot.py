import telebot
import os
import time
import random
import string
import logging
import threading
import requests
from datetime import datetime, timedelta, timezone
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")]
)
log = logging.getLogger("VpnIrBot")

TOKEN = "8611627525:AAEgDRKFC7-S6dOpv7tKMI8XLl7aveWgBK8"
ADMIN_ID = 8356825459
CHANNEL_ID = "@Vpn_IRan140"
CHANNEL_LINK = "https://t.me/Vpn_IRan140"
WEBSITE = "https://vpnir.netlify.app"
SUPPORT_ID = "@ad_vpnir"
OPENROUTER_KEY = "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"

SUPABASE_URL = "https://oeicsokgyrirjiufwjnf.supabase.co"
SUPABASE_KEY = "sb_secret_FY68ybbvXtMDZbUj-qWWVA_6NDvii2f"

db = create_client(SUPABASE_URL, SUPABASE_KEY)

CARD_NUMBER = "6280231392863212"
CARD_OWNER = "امیرحسین صراف زاده"
BANK_NAME = "بانک مسکن"
SHABA_NUMBER = "IR620140040004110181136923"
SHABA_LIMIT = 15_000_000

bot = telebot.TeleBot(TOKEN)
user_conversations = {}
_bot_username = None
_checkout_cache = {}

def get_bot_username():
    global _bot_username
    if _bot_username is None:
        _bot_username = bot.get_me().username
    return _bot_username

FRANCE_PRICE_PER_GB = 6000
FRANCE_MIN_GB = 5
FRANCE_MAX_GB = 200
FRANCE_MIN_DAYS = 1
FRANCE_MAX_DAYS = 365

VPN_PRICE_PER_GB = 15000
VPN_MIN_GB = 15
VPN_MAX_GB = 100

STARS_PRICE = 4000
STARS_MIN = 50
STARS_MAX = 10_000_000

UNLIMITED_PRICE = 399000
UNLIMITED_DOWNTIME_NOTE = "در روز حداکثر ۱۰ تا ۲۰ دقیقه قطعی داره."

REFERRAL_PERCENT = 10

VPN_PLAN_CONFIG = {
    "france": {
        "label": "🇫🇷 سرور فرانسه", "price_per_gb": FRANCE_PRICE_PER_GB,
        "min_gb": FRANCE_MIN_GB, "max_gb": FRANCE_MAX_GB, "fixed_days": None,
        "desc": "زیر قیمت کل بازار، همراه با پشتیبانی\nفقط لوکیشن فرانسه\nمدت دلخواه: چند روز تا یک سال"
    },
    "multi": {
        "label": "🌍 سرور مولتی (۱۸ کشور)", "price_per_gb": VPN_PRICE_PER_GB,
        "min_gb": VPN_MIN_GB, "max_gb": VPN_MAX_GB, "fixed_days": 30,
        "desc": "اتصال از بین ۱۸ کشور مختلف"
    }
}

CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

def gen_code(length=6):
    return "".join(random.choice(CODE_CHARS) for _ in range(length))

def gen_tracking_code(prefix):
    return f"{prefix}-{gen_code(6)}"

def get_expiry_date(days=30):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

def get_payment_info(amount):
    if amount >= SHABA_LIMIT:
        return f"""💳 لطفاً مبلغ رو به شبا زیر واریز کن:
<code>{SHABA_NUMBER}</code>
👤 {CARD_OWNER}
🏦 {BANK_NAME}
⚠️ مبلغ بالای ۱۵ میلیون، فقط از طریق شبا قابل پرداخت است."""
    return f"""💳 لطفاً مبلغ رو به کارت زیر واریز کن:
<code>{CARD_NUMBER}</code>
👤 {CARD_OWNER}
🏦 {BANK_NAME}"""

# ============================================================
# دیتابیس - کاربران
# ============================================================
_user_cache = {}

def get_user(telegram_id, force_refresh=False):
    if not force_refresh and telegram_id in _user_cache:
        return _user_cache[telegram_id]
    try:
        res = db.table("app_users").select("*").eq("telegram_id", telegram_id).execute()
        user = res.data[0] if res.data else None
        if user:
            _user_cache[telegram_id] = user
        return user
    except Exception as e:
        log.error(f"خطا در get_user: {e}")
        return None

def get_user_by_referral_code(code):
    try:
        res = db.table("app_users").select("*").eq("referral_code", code).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"خطا در get_user_by_referral_code: {e}")
        return None

def create_or_update_user(telegram_id, username, start_payload=None):
    existing = get_user(telegram_id)
    if existing:
        if username and existing.get("username") != username:
            try:
                db.table("app_users").update({"username": username}).eq("telegram_id", telegram_id).execute()
                existing["username"] = username
            except Exception as e:
                log.error(f"خطا در به‌روزرسانی کاربر: {e}")
        return existing

    referred_by = None
    if start_payload:
        ref_user = get_user_by_referral_code(start_payload.strip().upper())
        if ref_user and ref_user["telegram_id"] != telegram_id:
            referred_by = ref_user["telegram_id"]

    while True:
        code = gen_code(6)
        if not get_user_by_referral_code(code):
            break

    row = {
        "telegram_id": telegram_id,
        "username": username,
        "wallet_balance": 0,
        "referral_code": code,
        "referred_by": referred_by,
        "is_banned": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        db.table("app_users").insert(row).execute()
        _user_cache[telegram_id] = row
        return row
    except Exception as e:
        log.error(f"خطا در ایجاد کاربر: {e}")
        return None

def ensure_user_exists(telegram_id, username=None):
    """اطمینان از وجود کاربر در دیتابیس — کش‌محور، فقط اگه واقعاً پیدا نشد به DB سر می‌زنه."""
    user = get_user(telegram_id)
    if not user:
        user = create_or_update_user(telegram_id, username)
    return user

def is_banned(telegram_id):
    u = get_user(telegram_id)
    return bool(u and u.get("is_banned"))

def set_banned(telegram_id, banned):
    try:
        db.table("app_users").update({"is_banned": banned}).eq("telegram_id", telegram_id).execute()
        if telegram_id in _user_cache:
            _user_cache[telegram_id]["is_banned"] = banned
    except Exception as e:
        log.error(f"خطا در set_banned: {e}")

def adjust_wallet(telegram_id, delta, reason, ref_order_id=None):
    user = get_user(telegram_id, force_refresh=True)
    if not user:
        return None
    new_balance = user["wallet_balance"] + delta
    try:
        db.table("app_users").update({"wallet_balance": new_balance}).eq("telegram_id", telegram_id).execute()
        db.table("wallet_transactions").insert({
            "telegram_id": telegram_id, "amount": delta, "reason": reason, "ref_order_id": ref_order_id
        }).execute()
        if telegram_id in _user_cache:
            _user_cache[telegram_id]["wallet_balance"] = new_balance
        return new_balance
    except Exception as e:
        log.error(f"خطا در adjust_wallet: {e}")
        return None

# ============================================================
# دیتابیس - کدهای تخفیف
# ============================================================
def check_discount_code(code):
    try:
        res = db.table("discount_codes").select("*").eq("code", code.strip().upper()).execute()
        if not res.data:
            return None, "❌ کد تخفیف پیدا نشد."
        d = res.data[0]
        if not d["active"]:
            return None, "❌ این کد غیرفعال شده."
        if d.get("expires_at"):
            exp = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00"))
            if exp < datetime.now(timezone.utc):
                return None, "❌ این کد منقضی شده."
        if d.get("max_uses") is not None and d["used_count"] >= d["max_uses"]:
            return None, "❌ ظرفیت استفاده از این کد تمام شده."
        return d, None
    except Exception as e:
        log.error(f"خطا در check_discount_code: {e}")
        return None, "❌ خطا در بررسی کد تخفیف"

def consume_discount_code(code):
    try:
        row = db.table("discount_codes").select("used_count").eq("code", code).execute().data
        if not row:
            return
        db.table("discount_codes").update({"used_count": row[0]["used_count"] + 1}).eq("code", code).execute()
    except Exception as e:
        log.error(f"خطا در consume_discount_code: {e}")

# ============================================================
# دیتابیس - سفارش‌ها
# ============================================================
def create_order(telegram_id, product, base_amount, final_amount, order_type, tracking_prefix,
                  discount_code=None, pay_method="card", gb=None, days=None, plan=None, status="pending"):
    tracking_code = gen_tracking_code(tracking_prefix)
    row = {
        "tracking_code": tracking_code, "telegram_id": telegram_id, "product": product,
        "base_amount": base_amount, "discount_code": discount_code, "final_amount": final_amount,
        "pay_method": pay_method, "type": order_type, "status": status,
        "gb": gb, "days": days, "plan": plan
    }
    try:
        res = db.table("orders").insert(row).execute()
        return res.data[0]
    except Exception as e:
        log.error(f"خطا در create_order: {e}")
        return None

def get_order(order_id):
    try:
        res = db.table("orders").select("*").eq("id", order_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"خطا در get_order: {e}")
        return None

def get_latest_pending_order(telegram_id):
    try:
        res = db.table("orders").select("*").eq("telegram_id", telegram_id).eq("status", "pending") \
            .order("created_at", desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"خطا در get_latest_pending_order: {e}")
        return None

def update_order_status(order_id, status, server_info=None):
    payload = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if server_info is not None:
        payload["server_info"] = server_info
    try:
        db.table("orders").update(payload).eq("id", order_id).execute()
    except Exception as e:
        log.error(f"خطا در update_order_status: {e}")

def process_referral_commission(order):
    if order["type"] == "wallet_topup":
        return
    buyer = get_user(order["telegram_id"])
    if not buyer or not buyer.get("referred_by"):
        return
    referrer_id = buyer["referred_by"]
    commission = round(order["final_amount"] * REFERRAL_PERCENT / 100)
    if commission <= 0:
        return
    adjust_wallet(referrer_id, commission, "referral_commission", ref_order_id=order["id"])
    try:
        bot.send_message(
            referrer_id,
            f"🎁 <b>تبریک! یکی از زیرمجموعه‌های شما خرید کرد</b>\n\n"
            f"💰 {commission:,} تومان ({REFERRAL_PERCENT}٪) به کیف پولت اضافه شد.",
            parse_mode="HTML"
        )
    except telebot.apihelper.ApiTelegramException:
        pass

# ============================================================
# کیبوردها
# ============================================================
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add("🛒 خرید VPN", "⭐ خرید استارز")
    keyboard.add("👛 کیف پول من", "🎁 رفرال من")
    keyboard.add("📦 سفارش‌های من", "📞 پشتیبانی")
    keyboard.add("👤 حساب من")
    return keyboard

def admin_keyboard():
    keyboard = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add("📋 سفارشات در انتظار", "👥 لیست کاربران")
    keyboard.add("📨 پیام همگانی", "📊 آمار فروش")
    keyboard.add("🚫 بن/آنبن کاربر", "🔙 برگشت")
    return keyboard

def vpn_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🇫🇷 سرور فرانسه (۶,۰۰۰ تومان/گیگ)", callback_data="vpn_buy_france"))
    keyboard.add(InlineKeyboardButton("🌍 سرور مولتی ۱۸ کشور (۱۵,۰۰۰ تومان/گیگ)", callback_data="vpn_buy_multi"))
    keyboard.add(InlineKeyboardButton("🚀 سرور نامحدود (۳۹۹,۰۰۰ تومان)", callback_data="vpn_unlimited"))
    keyboard.add(InlineKeyboardButton("🔙 برگشت", callback_data="back"))
    return keyboard

def confirm_keyboard(user_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("✅ تایید", callback_data=f"confirm_{user_id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}")
    )
    return keyboard

def cancel_payment_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="cancel_payment"))
    return keyboard

def channel_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_LINK))
    keyboard.add(InlineKeyboardButton("✅ عضویت را تایید کردم", callback_data="check_membership"))
    return keyboard

def stars_type_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("👤 خودم", callback_data="stars_self"),
        InlineKeyboardButton("👥 شخص دیگر", callback_data="stars_other")
    )
    keyboard.add(InlineKeyboardButton("🔙 برگشت", callback_data="back"))
    return keyboard

def support_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("📋 سوالات متداول", callback_data="faq"),
        InlineKeyboardButton("🤖 پشتیبانی هوشمند", callback_data="support_ai"),
        InlineKeyboardButton("👤 ارتباط با ادمین", callback_data="support_admin")
    )
    keyboard.add(InlineKeyboardButton("🔙 برگشت", callback_data="back"))
    return keyboard

def ban_unban_keyboard(target_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🚫 بن کن", callback_data=f"doban_{target_id}"),
        InlineKeyboardButton("✅ آنبن کن", callback_data=f"unban_{target_id}")
    )
    return keyboard

def discount_prompt_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🏷 دارم", callback_data="discount_yes"),
        InlineKeyboardButton("➡️ ندارم، رد شو", callback_data="discount_no")
    )
    return keyboard

def payment_method_keyboard(can_use_wallet):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("💳 پرداخت کارتی", callback_data="pay_card"))
    if can_use_wallet:
        keyboard.add(InlineKeyboardButton("👛 پرداخت از کیف پول", callback_data="pay_wallet"))
    keyboard.add(InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="cancel_payment"))
    return keyboard

FAQ_TEXT = f"""📋 <b>سوالات متداول</b>
━━━━━━━━━━━━━━

❓ <b>سرور فرانسه و مولتی چه فرقی دارن؟</b>

🇫🇷 <b>فرانسه</b>
• ۶,۰۰۰ تومان/گیگ
• ۵ تا ۲۰۰ گیگ
• مدت دلخواه (چند روز تا ۱ سال)

🌍 <b>مولتی (۱۸ کشور)</b>
• ۱۵,۰۰۰ تومان/گیگ
• ۱۵ تا ۱۰۰ گیگ
• مدت ثابت ۳۰ روز

━━━━━━━━━━━━━━

❓ <b>سرور نامحدود چطوره؟</b>
حجم نامحدود، ۳۰ روزه، ۳۹۹,۰۰۰ تومان.
{UNLIMITED_DOWNTIME_NOTE}

❓ <b>کیف پول چیه؟</b>
حساب رو شارژ می‌کنی و از موجودیش برای خرید استفاده می‌کنی — بدون واریز دستی هر بار.

❓ <b>رفرال چطور کار می‌کنه؟</b>
به‌ازای هر خرید تایید‌شده‌ی زیرمجموعه‌ت، {REFERRAL_PERCENT}٪ به کیف پولت اضافه می‌شه.

❓ <b>روش‌های پرداخت چیه؟</b>
کارت‌به‌کارت، شبا (بالای ۱۵ میلیون تومان)، یا از کیف پول.

❓ <b>پشتیبانی از کجا؟</b>
{SUPPORT_ID}"""

AI_SYSTEM_PROMPT = f"""شما یک پشتیبان صمیمی و دقیق برای ربات Vpn IR هستید.

📌 قیمت‌ها (به تومان):
1️⃣ سرور فرانسه: هر گیگ = ۶,۰۰۰ تومان (۵ تا ۲۰۰ گیگ)
2️⃣ سرور مولتی: هر گیگ = ۱۵,۰۰۰ تومان (۱۵ تا ۱۰۰ گیگ)
3️⃣ سرور نامحدود: ۳۹۹,۰۰۰ تومان
4️⃣ استارز: هر عدد = ۴,۰۰۰ تومان

💡 امکانات: کیف پول، رفرال ({REFERRAL_PERCENT}٪)، کد تخفیف

پاسخ‌ها کوتاه، دقیق و صمیمی باشن."""

def ask_ai(user_id, question):
    try:
        history = user_conversations.setdefault(user_id, [])
        history.append({"role": "user", "content": question})
        if len(history) > 10:
            del history[:-10]
        messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}] + history
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json={"model": "openai/gpt-3.5-turbo", "messages": messages},
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        history.append({"role": "assistant", "content": answer})
        return answer
    except requests.exceptions.RequestException as e:
        log.warning(f"خطا در AI: {e}")
        return "❌ خطا در ارتباط با هوش مصنوعی. کمی بعد دوباره امتحان کن."
    except (KeyError, IndexError) as e:
        log.error(f"پاسخ غیرمنتظره از AI: {e}")
        return "❌ خطا در پردازش پاسخ."

def safe_edit(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            log.warning(f"edit failed: {e}")

_membership_cache = {}
MEMBERSHIP_CACHE_SECONDS = 300

def is_member(user_id):
    now = time.time()
    cached = _membership_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        result = member.status in ["member", "administrator", "creator"]
    except telebot.apihelper.ApiTelegramException:
        result = False
    except Exception as e:
        log.error(f"خطای غیرمنتظره در چک عضویت: {e}")
        result = False
    _membership_cache[user_id] = (result, now + MEMBERSHIP_CACHE_SECONDS)
    return result

def welcome_text(first_name):
    return f"""👋 <b>سلام {first_name} عزیز، خوش اومدی!</b>

🇮🇷 <b>ربات Vpn IR</b>
━━━━━━━━━━━━━━
🇫🇷 سرور فرانسه (زیر قیمت بازار)
🌍 سرور مولتی (۱۸ کشور)
🚀 سرور نامحدود
⭐ فروش استارز تلگرام
👛 کیف پول، رفرال و کد تخفیف
⚡️ تحویل فوری | پشتیبانی ۲۴/۷
━━━━━━━━━━━━━━

📢 کانال: {CHANNEL_ID}
🌍 سایت: {WEBSITE}

از دکمه‌های پایین شروع کن 👇"""

ADMIN_WELCOME_TEXT = """👋 <b>سلام ادمین عزیز، خوش اومدی!</b>

🇮🇷 <b>پنل مدیریت Vpn IR</b>
━━━━━━━━━━━━━━
📋 مدیریت سفارشات
👥 مدیریت کاربران
📨 پیام همگانی
📊 آمار فروش
━━━━━━━━━━━━━━

از دکمه‌های پایین استفاده کن 👇"""

def send_home(chat_id, user_id, first_name):
    if str(user_id) == str(ADMIN_ID):
        bot.send_message(chat_id, ADMIN_WELCOME_TEXT, reply_markup=admin_keyboard(), parse_mode="HTML")
    else:
        bot.send_message(chat_id, welcome_text(first_name), reply_markup=main_keyboard(), parse_mode="HTML")

ALL_MENU_BUTTON_TEXTS = {
    "🛒 خرید VPN", "⭐ خرید استارز", "👛 کیف پول من", "🎁 رفرال من",
    "📦 سفارش‌های من", "📞 پشتیبانی", "👤 حساب من",
    "📋 سفارشات در انتظار", "👥 لیست کاربران", "📨 پیام همگانی",
    "📊 آمار فروش", "🚫 بن/آنبن کاربر", "🔙 برگشت"
}

def intercept_flow_restart(message):
    text = (message.text or "").strip()
    if not text:
        return False

    if text.startswith("/"):
        _checkout_cache.pop(message.from_user.id, None)
        cmd = text.split()[0].lower()
        if cmd == "/start":
            start(message)
        elif cmd == "/help":
            help_cmd(message)
        else:
            bot.reply_to(message, "❌ عملیات قبلی لغو شد.")
        return True

    if text in ALL_MENU_BUTTON_TEXTS:
        _checkout_cache.pop(message.from_user.id, None)
        handle_buttons(message)
        return True

    return False

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    ref_payload = parts[1].strip() if len(parts) > 1 else None

    if is_banned(user_id):
        bot.reply_to(message, "🚫 شما بن هستید.")
        return
    if not is_member(user_id):
        bot.reply_to(message, f"⚠️ برای استفاده از ربات باید عضو کانال {CHANNEL_ID} بشی.", reply_markup=channel_keyboard())
        return
    create_or_update_user(user_id, message.from_user.username, start_payload=ref_payload)
    send_home(message.chat.id, user_id, message.from_user.first_name)

@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(message, """🆘 <b>راهنمای ربات</b>

/start — شروع مجدد ربات
🛒 خرید VPN — فرانسه / مولتی / نامحدود
⭐ خرید استارز — خرید استارز تلگرام
👛 کیف پول من — مشاهده و شارژ موجودی
🎁 رفرال من — لینک دعوت و پورسانت
📦 سفارش‌های من — پیگیری سفارش‌ها
👤 حساب من — اطلاعات حساب و ورود به پنل سایت
📞 پشتیبانی — سوالات متداول یا تماس با ادمین""", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "check_membership")
def check_membership(call):
    user_id = call.from_user.id
    if is_member(user_id):
        bot.answer_callback_query(call.id, "✅")
        create_or_update_user(user_id, call.from_user.username)
        safe_edit(call.message.chat.id, call.message.message_id, "✅ عضویت شما تایید شد!")
        send_home(call.message.chat.id, user_id, call.from_user.first_name)
    else:
        bot.answer_callback_query(call.id, "❌ هنوز عضو نشدی!", show_alert=True)

@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_buttons(message):
    user_id = message.from_user.id

    if is_banned(user_id):
        bot.reply_to(message, "🚫 شما بن هستید.")
        return
    if not is_member(user_id):
        bot.reply_to(message, f"⚠️ اول عضو کانال {CHANNEL_ID} شو.", reply_markup=channel_keyboard())
        return

    user = ensure_user_exists(user_id, message.from_user.username)
    if not user:
        bot.reply_to(message, "❌ خطا در شناسایی کاربر. لطفاً /start رو بزن.")
        return

    is_admin = str(user_id) == str(ADMIN_ID)

    if message.text == "📋 سفارشات در انتظار" and is_admin:
        show_pending_orders(message.chat.id); return
    if message.text == "👥 لیست کاربران" and is_admin:
        show_users_list(message.chat.id); return
    if message.text == "📨 پیام همگانی" and is_admin:
        msg = bot.reply_to(message, "📨 پیام همگانی رو بنویس (یا /cancel برای لغو):")
        bot.register_next_step_handler(msg, broadcast_message); return
    if message.text == "📊 آمار فروش" and is_admin:
        show_stats(message.chat.id); return
    if message.text == "🚫 بن/آنبن کاربر" and is_admin:
        msg = bot.reply_to(message, "✏️ آیدی عددی کاربر رو بفرست:")
        bot.register_next_step_handler(msg, ask_ban_target); return
    if message.text == "🔙 برگشت" and is_admin:
        bot.reply_to(message, "🔙 برگشتی.", reply_markup=main_keyboard()); return

    if message.text == "🛒 خرید VPN":
        bot.reply_to(message, VPN_MENU_TEXT, reply_markup=vpn_keyboard(), parse_mode="HTML")
    elif message.text == "⭐ خرید استارز":
        msg = bot.reply_to(message, f"""⭐ <b>خرید استارز</b>

تعداد استارز مورد نظرت رو بنویس (فقط عدد).

• هر عدد = {STARS_PRICE:,} تومان
• حداقل: {STARS_MIN} عدد
• حداکثر: {STARS_MAX:,} عدد

مثال: 100""", parse_mode="HTML")
        bot.register_next_step_handler(msg, get_stars_count)
    elif message.text == "👛 کیف پول من":
        show_wallet(message.chat.id, user_id)
    elif message.text == "🎁 رفرال من":
        show_referral(message.chat.id, user_id)
    elif message.text == "📦 سفارش‌های من":
        show_my_orders(message.chat.id, user_id)
    elif message.text == "📞 پشتیبانی":
        bot.reply_to(message, "📌 لطفاً یکی از گزینه‌های زیر رو انتخاب کن:", reply_markup=support_keyboard())
    elif message.text == "👤 حساب من":
        show_my_account(message.chat.id, user_id)

# ============================================================
# بخش VPN
# ============================================================
VPN_MENU_TEXT = f"""🌟 <b>یکی از گزینه‌های زیر رو انتخاب کن</b>
━━━━━━━━━━━━━━

🇫🇷 <b>سرور فرانسه</b>
• ۶,۰۰۰ تومان/گیگ
• {FRANCE_MIN_GB} تا {FRANCE_MAX_GB} گیگ
• مدت دلخواه: چند روز تا ۱ سال

🌍 <b>سرور مولتی (۱۸ کشور)</b>
• ۱۵,۰۰۰ تومان/گیگ
• {VPN_MIN_GB} تا {VPN_MAX_GB} گیگ
• مدت ثابت: ۳۰ روز

🚀 <b>نامحدود</b>
• ۳۹۹,۰۰۰ تومان — بدون محدودیت حجم
• {UNLIMITED_DOWNTIME_NOTE}
• مدت: ۳۰ روز
━━━━━━━━━━━━━━
💎 بدون محدودیت کاربری روی همه‌ی پلن‌ها"""

@bot.callback_query_handler(func=lambda call: call.data in ("vpn_buy_france", "vpn_buy_multi"))
def buy_vpn(call):
    bot.answer_callback_query(call.id, "📝")
    plan_key = "france" if call.data == "vpn_buy_france" else "multi"
    plan = VPN_PLAN_CONFIG[plan_key]
    duration_line = "خودت انتخاب می‌کنی (چند روز تا ۱ سال)" if plan['fixed_days'] is None else f"{plan['fixed_days']} روز"
    desc_lines = "\n".join(f"• {line}" for line in plan['desc'].split("\n"))
    text = f"""{plan['label']}
━━━━━━━━━━━━━━
{desc_lines}
• قیمت: {plan['price_per_gb']:,} تومان/گیگ
• حجم: {plan['min_gb']} تا {plan['max_gb']} گیگ
• مدت: {duration_line}
━━━━━━━━━━━━━━

✏️ حجم مورد نظرت رو به گیگ بنویس (فقط عدد):"""
    safe_edit(call.message.chat.id, call.message.message_id, text)
    bot.register_next_step_handler(call.message, get_vpn_volume, plan_key)

def get_vpn_volume(message, plan_key):
    plan = VPN_PLAN_CONFIG[plan_key]
    if not message or not message.text:
        bot.reply_to(message, "❌ لغو شد.")
        return
    if intercept_flow_restart(message):
        return
    text = message.text.strip()
    if not text.isdigit():
        msg = bot.reply_to(message, f"❌ فقط عدد بفرست، بین {plan['min_gb']} تا {plan['max_gb']}:")
        bot.register_next_step_handler(msg, get_vpn_volume, plan_key)
        return
    gb = int(text)
    if gb < plan['min_gb'] or gb > plan['max_gb']:
        msg = bot.reply_to(message, f"❌ بین {plan['min_gb']} تا {plan['max_gb']}:")
        bot.register_next_step_handler(msg, get_vpn_volume, plan_key)
        return

    if plan['fixed_days'] is not None:
        start_checkout(message.chat.id, message.from_user.id, plan_key, gb, plan['fixed_days'])
        return

    msg = bot.reply_to(message, f"✏️ مدت سرویس رو به روز بنویس (بین {FRANCE_MIN_DAYS} تا {FRANCE_MAX_DAYS} روز):")
    bot.register_next_step_handler(msg, get_vpn_duration, plan_key, gb)

def get_vpn_duration(message, plan_key, gb):
    if not message or not message.text:
        bot.reply_to(message, "❌ لغو شد.")
        return
    if intercept_flow_restart(message):
        return
    text = message.text.strip()
    if not text.isdigit():
        msg = bot.reply_to(message, f"❌ فقط عدد بفرست، بین {FRANCE_MIN_DAYS} تا {FRANCE_MAX_DAYS} روز:")
        bot.register_next_step_handler(msg, get_vpn_duration, plan_key, gb)
        return
    days = int(text)
    if days < FRANCE_MIN_DAYS or days > FRANCE_MAX_DAYS:
        msg = bot.reply_to(message, f"❌ بین {FRANCE_MIN_DAYS} تا {FRANCE_MAX_DAYS} روز:")
        bot.register_next_step_handler(msg, get_vpn_duration, plan_key, gb)
        return
    start_checkout(message.chat.id, message.from_user.id, plan_key, gb, days)

# ============================================================
# فرآیند تسویه‌حساب
# ============================================================
def start_checkout(chat_id, user_id, plan_key, gb, days):
    plan = VPN_PLAN_CONFIG[plan_key]
    base_amount = gb * plan['price_per_gb']
    product_name = f"{plan['label']} {gb} گیگ / {days} روز"
    _checkout_cache[user_id] = {
        "kind": "vpn", "plan_key": plan_key, "gb": gb, "days": days,
        "product": product_name, "base_amount": base_amount, "tracking_prefix": "VPN"
    }
    bot.send_message(chat_id, f"""📦 <b>{product_name}</b>
💰 مبلغ پایه: {base_amount:,} تومان

🏷 کد تخفیف داری؟""", reply_markup=discount_prompt_keyboard(), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data in ("discount_yes", "discount_no"))
def handle_discount_choice(call):
    user_id = call.from_user.id
    cart = _checkout_cache.get(user_id)
    if not cart:
        bot.answer_callback_query(call.id, "❌ سبد خریدی پیدا نشد.")
        return
    if call.data == "discount_no":
        bot.answer_callback_query(call.id)
        show_payment_options(call.message.chat.id, user_id)
    else:
        bot.answer_callback_query(call.id, "📝")
        msg = bot.send_message(call.message.chat.id, "✏️ کد تخفیف رو بنویس:")
        bot.register_next_step_handler(msg, apply_discount_code)

def apply_discount_code(message):
    user_id = message.from_user.id
    cart = _checkout_cache.get(user_id)
    if not cart:
        bot.reply_to(message, "❌ سبد خریدی پیدا نشد.")
        return
    if (message.text or "").strip().lower() == "/skip":
        show_payment_options(message.chat.id, user_id)
        return
    if intercept_flow_restart(message):
        return
    code = (message.text or "").strip().upper()
    discount, error = check_discount_code(code)
    if error:
        msg = bot.reply_to(message, f"{error}\n✏️ دوباره بنویس یا /skip برای رد کردن:")
        bot.register_next_step_handler(msg, apply_discount_code)
        return
    cart["discount_code"] = discount["code"]
    cart["discount_percent"] = discount["percent"]
    bot.reply_to(message, f"✅ کد تخفیف {discount['percent']}٪ اعمال شد!")
    show_payment_options(message.chat.id, user_id)

def show_payment_options(chat_id, user_id):
    cart = _checkout_cache.get(user_id)
    if not cart:
        return
    base = cart["base_amount"]
    percent = cart.get("discount_percent", 0)
    final_amount = round(base * (100 - percent) / 100)
    cart["final_amount"] = final_amount

    user = ensure_user_exists(user_id)
    wallet_balance = user["wallet_balance"] if user else 0
    can_use_wallet = wallet_balance >= final_amount

    discount_line = f"🏷 بعد از {percent}٪ تخفیف\n" if percent else ""
    text = f"""📦 <b>{cart['product']}</b>
━━━━━━━━━━━━━━
{discount_line}💰 مبلغ نهایی: {final_amount:,} تومان
👛 موجودی کیف پول: {wallet_balance:,} تومان
━━━━━━━━━━━━━━

روش پرداخت رو انتخاب کن:"""
    bot.send_message(chat_id, text, reply_markup=payment_method_keyboard(can_use_wallet), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data in ("pay_card", "pay_wallet"))
def handle_payment_method(call):
    user_id = call.from_user.id
    cart = _checkout_cache.get(user_id)
    if not cart:
        bot.answer_callback_query(call.id, "❌ سبد خریدی پیدا نشد.")
        return

    final_amount = cart["final_amount"]

    if call.data == "pay_wallet":
        user = ensure_user_exists(user_id)
        if not user or user["wallet_balance"] < final_amount:
            bot.answer_callback_query(call.id, "❌ موجودی کافی نیست.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "✅")
        order = create_order(
            user_id, cart["product"], cart["base_amount"], final_amount,
            cart["kind"], cart["tracking_prefix"], discount_code=cart.get("discount_code"),
            pay_method="wallet", gb=cart.get("gb"), days=cart.get("days"), plan=cart.get("plan_key"),
            status="confirmed"
        )
        if order:
            adjust_wallet(user_id, -final_amount, "order_payment", ref_order_id=order["id"])
            process_referral_commission(order)
            if cart.get("discount_code"):
                consume_discount_code(cart["discount_code"])
            safe_edit(call.message.chat.id, call.message.message_id, f"""✅ <b>پرداخت از کیف پول انجام شد!</b>
━━━━━━━━━━━━━━
📦 {cart['product']}
🔖 کد رهگیری: <code>{order['tracking_code']}</code>
━━━━━━━━━━━━━━
⏳ سرویس به‌زودی توسط ادمین ارسال می‌شه.""")
            notify_admin_new_order(order)
            del _checkout_cache[user_id]
        return

    bot.answer_callback_query(call.id, "💳")
    order = create_order(
        user_id, cart["product"], cart["base_amount"], final_amount,
        cart["kind"], cart["tracking_prefix"], discount_code=cart.get("discount_code"),
        pay_method="card", gb=cart.get("gb"), days=cart.get("days"), plan=cart.get("plan_key"),
        status="pending"
    )
    if order and cart.get("discount_code"):
        consume_discount_code(cart["discount_code"])
    if order:
        safe_edit(call.message.chat.id, call.message.message_id, f"""🛒 <b>سفارش شما</b>
━━━━━━━━━━━━━━
📦 {cart['product']}
💰 قیمت: {final_amount:,} تومان
🔖 کد رهگیری: <code>{order['tracking_code']}</code>
━━━━━━━━━━━━━━

{get_payment_info(final_amount)}

📤 بعد از واریز، عکس رسید رو همینجا بفرست.""", reply_markup=cancel_payment_keyboard())
    del _checkout_cache[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "cancel_payment")
def cancel_payment(call):
    bot.answer_callback_query(call.id, "🔙")
    _checkout_cache.pop(call.from_user.id, None)
    safe_edit(call.message.chat.id, call.message.message_id, "🔙 به منوی اصلی برگشتی.")
    bot.send_message(call.message.chat.id, "📋 منوی اصلی:", reply_markup=main_keyboard())

# ============================================================
# سرور نامحدود
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data == "vpn_unlimited")
def buy_unlimited(call):
    bot.answer_callback_query(call.id, "🚀")
    user_id = call.from_user.id
    _checkout_cache[user_id] = {
        "kind": "unlimited", "product": "🚀 سرور نامحدود", "base_amount": UNLIMITED_PRICE,
        "tracking_prefix": "UNL"
    }
    safe_edit(call.message.chat.id, call.message.message_id,
              f"📦 <b>🚀 سرور نامحدود</b>\n💰 مبلغ پایه: {UNLIMITED_PRICE:,} تومان\n\n🏷 کد تخفیف داری؟",
              reply_markup=discount_prompt_keyboard())

# ============================================================
# بخش استارز
# ============================================================
def get_stars_count(message):
    if not message or not message.text:
        bot.reply_to(message, "❌ لغو شد.")
        return
    if intercept_flow_restart(message):
        return
    text = message.text.strip()
    if not text.isdigit():
        msg = bot.reply_to(message, f"❌ عدد بین {STARS_MIN} تا {STARS_MAX}:")
        bot.register_next_step_handler(msg, get_stars_count)
        return
    count = int(text)
    if count < STARS_MIN or count > STARS_MAX:
        msg = bot.reply_to(message, f"❌ بین {STARS_MIN} تا {STARS_MAX}:")
        bot.register_next_step_handler(msg, get_stars_count)
        return
    _checkout_cache.setdefault(message.from_user.id, {})["stars_count"] = count
    bot.reply_to(message, "📌 استارز برای چه کسی؟", reply_markup=stars_type_keyboard())

@bot.callback_query_handler(func=lambda call: call.data in ["stars_self", "stars_other"])
def handle_stars_type(call):
    user_id = call.from_user.id
    cart = _checkout_cache.get(user_id)
    if not cart or "stars_count" not in cart:
        bot.answer_callback_query(call.id, "❌ اول تعداد رو وارد کن!")
        return
    count = cart["stars_count"]
    price = count * STARS_PRICE

    if call.data == "stars_self":
        target = call.from_user.username or str(user_id)
    else:
        bot.answer_callback_query(call.id, "📝")
        safe_edit(call.message.chat.id, call.message.message_id, "✏️ آیدی تلگرام شخص مورد نظر رو بنویس:")
        bot.register_next_step_handler(call.message, get_stars_other, count)
        return

    bot.answer_callback_query(call.id, "✅")
    _checkout_cache[user_id] = {
        "kind": "stars", "product": f"⭐ استارز {count} عددی برای @{target}",
        "base_amount": price, "tracking_prefix": "STAR"
    }
    safe_edit(call.message.chat.id, call.message.message_id,
              f"📦 <b>استارز {count} عددی</b>\n💰 مبلغ پایه: {price:,} تومان\n\n🏷 کد تخفیف داری؟",
              reply_markup=discount_prompt_keyboard())

def get_stars_other(message, count):
    if not message or not message.text:
        bot.reply_to(message, "❌ لغو شد.")
        return
    if intercept_flow_restart(message):
        return
    username = message.text.strip().lstrip("@")
    if not username or len(username) < 3:
        msg = bot.reply_to(message, "❌ آیدی معتبر نیست:")
        bot.register_next_step_handler(msg, get_stars_other, count)
        return
    price = count * STARS_PRICE
    _checkout_cache[message.from_user.id] = {
        "kind": "stars", "product": f"⭐ استارز {count} عددی برای @{username}",
        "base_amount": price, "tracking_prefix": "STAR"
    }
    bot.send_message(message.chat.id,
                      f"📦 <b>استارز {count} عددی برای @{username}</b>\n💰 مبلغ پایه: {price:,} تومان\n\n🏷 کد تخفیف داری؟",
                      reply_markup=discount_prompt_keyboard(), parse_mode="HTML")

# ============================================================
# کیف پول
# ============================================================
def show_wallet(chat_id, user_id):
    user = ensure_user_exists(user_id)
    if not user:
        bot.send_message(chat_id, "❌ خطا در دریافت اطلاعات. لطفاً /start رو بزن.")
        return
    balance = user["wallet_balance"]
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_topup"))
    bot.send_message(chat_id, f"""👛 <b>کیف پول شما</b>
━━━━━━━━━━━━━━
💰 موجودی: {balance:,} تومان""", reply_markup=keyboard, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "wallet_topup")
def wallet_topup(call):
    bot.answer_callback_query(call.id, "➕")
    msg = bot.send_message(call.message.chat.id, """✏️ <b>چند تومان می‌خوای شارژ کنی؟</b>

• فقط عدد بفرست، به تومان (نه ریال)
• مثال: 50000 یعنی ۵۰ هزار تومان
• حداقل مبلغ: ۱۰,۰۰۰ تومان""", parse_mode="HTML")
    bot.register_next_step_handler(msg, get_topup_amount)

def get_topup_amount(message):
    if intercept_flow_restart(message):
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 10000:
        msg = bot.reply_to(message, "❌ فقط عدد و به تومان بفرست (مثلاً 50000). حداقل ۱۰,۰۰۰ تومان:")
        bot.register_next_step_handler(msg, get_topup_amount)
        return
    amount = int(text)
    order = create_order(
        message.from_user.id, "👛 شارژ کیف پول", amount, amount,
        "wallet_topup", "TOPUP", pay_method="card", status="pending"
    )
    if order:
        bot.reply_to(message, f"""🛒 <b>درخواست شارژ ثبت شد</b>
━━━━━━━━━━━━━━
💰 مبلغ: {amount:,} تومان
🔖 کد رهگیری: <code>{order['tracking_code']}</code>
━━━━━━━━━━━━━━

{get_payment_info(amount)}

📤 بعد از واریز، عکس رسید رو همینجا بفرست.""", parse_mode="HTML", reply_markup=cancel_payment_keyboard())

# ============================================================
# رفرال
# ============================================================
def show_referral(chat_id, user_id):
    user = ensure_user_exists(user_id)
    if not user:
        bot.send_message(chat_id, "❌ خطا در دریافت اطلاعات. لطفاً /start رو بزن.")
        return
    ref_code = user["referral_code"]
    ref_link = f"https://t.me/{get_bot_username()}?start={ref_code}"

    try:
        referral_count = len(db.table("app_users").select("telegram_id").eq("referred_by", user_id).execute().data)
    except Exception as e:
        log.error(f"خطا در شمارش زیرمجموعه‌ها: {e}")
        referral_count = 0

    try:
        earned_rows = db.table("wallet_transactions").select("amount").eq("telegram_id", user_id).eq("reason", "referral_commission").execute().data
        total_earned = sum(r["amount"] for r in earned_rows)
    except Exception as e:
        log.error(f"خطا در محاسبه پورسانت: {e}")
        total_earned = 0

    bot.send_message(chat_id, f"""🎁 <b>سیستم رفرال</b>
━━━━━━━━━━━━━━

🔗 لینک دعوت شما:
<code>{ref_link}</code>

👥 تعداد زیرمجموعه‌ها: {referral_count}
💰 مجموع پورسانت دریافتی: {total_earned:,} تومان
━━━━━━━━━━━━━━

📌 به‌ازای هر خرید تایید‌شده‌ی زیرمجموعه‌هات، {REFERRAL_PERCENT}٪ به کیف پولت اضافه می‌شه.""", parse_mode="HTML")

# ============================================================
# پیگیری سفارش‌ها
# ============================================================
def show_my_orders(chat_id, user_id):
    try:
        res = db.table("orders").select("*").eq("telegram_id", user_id).order("created_at", desc=True).limit(15).execute()
        orders = res.data
    except Exception as e:
        log.error(f"خطا در دریافت سفارش‌ها: {e}")
        orders = []

    if not orders:
        bot.send_message(chat_id, "❌ هنوز سفارشی ثبت نکردی.")
        return
    status_labels = {"pending": "⏳ در انتظار", "confirmed": "✅ تایید شده", "delivered": "📬 تحویل داده شده", "rejected": "❌ رد شده"}
    text = "📦 <b>سفارش‌های شما</b>\n━━━━━━━━━━━━━━\n\n"
    for o in orders:
        status = status_labels.get(o["status"], o["status"])
        text += f"🔖 <code>{o['tracking_code']}</code>\n{o['product']}\n{o['final_amount']:,} تومان · {status}\n\n"
    bot.send_message(chat_id, text, parse_mode="HTML")

# ============================================================
# حساب من
# ============================================================
def show_my_account(chat_id, user_id):
    user = ensure_user_exists(user_id)
    if not user:
        bot.send_message(chat_id, "❌ خطا در دریافت اطلاعات. لطفاً /start رو بزن.")
        return

    try:
        orders = db.table("orders").select("id, status").eq("telegram_id", user_id).execute().data
        orders_count = len(orders)
        delivered_count = sum(1 for o in orders if o["status"] == "delivered")
    except Exception as e:
        log.error(f"خطا در دریافت آمار سفارش‌ها: {e}")
        orders_count = 0
        delivered_count = 0

    join_date = "—"
    if user.get("created_at"):
        join_date = user["created_at"][:16].replace("T", " ")

    text = f"""👤 <b>حساب من</b>
━━━━━━━━━━━━━━

🆔 آیدی عددی شما
<code>{user_id}</code>

👛 موجودی کیف پول
{user['wallet_balance']:,} تومان

📅 تاریخ عضویت
{join_date}

📦 تعداد سفارش‌ها
{orders_count} کل — {delivered_count} تحویل‌شده

━━━━━━━━━━━━━━
🌐 <b>ورود به پنل سایت</b>

آیدی بالا رو توی سایت وارد کن:
{WEBSITE}

یه کد ۶ رقمی همینجا برات ارسال می‌شه؛ اون کد رو توی سایت بزن تا وارد پنلت بشی."""
    bot.send_message(chat_id, text, parse_mode="HTML")

# ============================================================
# پشتیبانی
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data == "faq")
def show_faq(call):
    bot.answer_callback_query(call.id, "📋")
    safe_edit(call.message.chat.id, call.message.message_id, FAQ_TEXT)

@bot.callback_query_handler(func=lambda call: call.data == "support_ai")
def support_ai(call):
    bot.answer_callback_query(call.id, "🤖")
    safe_edit(call.message.chat.id, call.message.message_id,
              "🤖 <b>پشتیبانی هوشمند</b>\n\nسوالتو بنویس، هوش مصنوعی جواب می‌ده:")
    bot.register_next_step_handler(call.message, handle_ai_question)

def handle_ai_question(message):
    question = message.text or ""
    if "ad_vpnir" in question.lower() or "آیدی پشتیبانی" in question.lower():
        bot.reply_to(message, f"👤 آیدی پشتیبانی: {SUPPORT_ID}")
        return
    bot.send_chat_action(message.chat.id, "typing")
    answer = ask_ai(message.from_user.id, question)
    bot.reply_to(message, f"🤖 <b>پاسخ:</b>\n\n{answer}", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "support_admin")
def support_admin(call):
    bot.answer_callback_query(call.id, "👤")
    safe_edit(call.message.chat.id, call.message.message_id, f"""👤 <b>ارتباط با ادمین</b>
━━━━━━━━━━━━━━
📌 آیدی ادمین: {SUPPORT_ID}
⏳ پاسخگویی: حداکثر ۳ ساعت""")

# ============================================================
# دریافت عکس رسید
# ============================================================
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.from_user.id
    if is_banned(user_id):
        bot.reply_to(message, "🚫 شما بن هستید.")
        return
    if not is_member(user_id):
        bot.reply_to(message, f"⚠️ اول عضو کانال {CHANNEL_ID} شو.")
        return

    order = get_latest_pending_order(user_id)
    if not order:
        bot.reply_to(message, "❌ سفارش فعالی نداری.")
        return

    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        filename = f"receipt_{user_id}_{int(time.time())}.jpg"
        with open(filename, "wb") as f:
            f.write(downloaded_file)
        with open(filename, "rb") as f:
            bot.send_photo(ADMIN_ID, f, caption=f"""🔔 <b>رسید جدید</b>
━━━━━━━━━━━━━━
👤 {message.from_user.first_name}
🆔 {user_id}
📦 {order['product']}
💰 {order['final_amount']:,} تومان
🔖 {order['tracking_code']}""", reply_markup=confirm_keyboard(user_id), parse_mode="HTML")
        os.remove(filename)
        bot.reply_to(message, "✅ رسید شما دریافت شد! منتظر تایید ادمین باش.")
    except telebot.apihelper.ApiTelegramException as e:
        log.error(f"خطای تلگرام هنگام ارسال رسید: {e}")
        bot.reply_to(message, "❌ خطا در ارسال رسید به ادمین. دوباره امتحان کن.")
    except OSError as e:
        log.error(f"خطای فایل هنگام پردازش رسید: {e}")
        bot.reply_to(message, "❌ خطا در پردازش رسید. دوباره امتحان کن.")

def notify_admin_new_order(order):
    try:
        bot.send_message(ADMIN_ID, f"""🔔 <b>سفارش جدید (پرداخت از کیف پول)</b>
━━━━━━━━━━━━━━
📦 {order['product']}
💰 {order['final_amount']:,} تومان
🔖 {order['tracking_code']}
🆔 {order['telegram_id']}""", parse_mode="HTML")
    except telebot.apihelper.ApiTelegramException:
        pass

# ============================================================
# تایید و رد سفارش
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
def confirm_order_cb(call):
    user_id = int(call.data.replace("confirm_", ""))
    order = get_latest_pending_order(user_id)
    if not order:
        bot.answer_callback_query(call.id, "❌ سفارشی نیست!")
        return

    if order["type"] == "wallet_topup":
        bot.answer_callback_query(call.id, "✅")
        update_order_status(order["id"], "delivered")
        adjust_wallet(user_id, order["final_amount"], "topup", ref_order_id=order["id"])
        try:
            bot.send_message(user_id, f"✅ کیف پولت شارژ شد!\n💰 {order['final_amount']:,} تومان اضافه شد.")
        except telebot.apihelper.ApiTelegramException:
            pass
        try:
            bot.edit_message_caption(f"✅ شارژ کیف پول انجام شد!\n👤 {user_id}", call.message.chat.id, call.message.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass
        return

    update_order_status(order["id"], "confirmed")
    process_referral_commission(order)

    if order["type"] == "stars":
        try:
            bot.send_message(user_id, f"✅ خرید تایید شد!\n📦 {order['product']}")
        except telebot.apihelper.ApiTelegramException:
            pass
        update_order_status(order["id"], "delivered")
        try:
            bot.edit_message_caption(f"✅ استارز ارسال شد!\n👤 {user_id}", call.message.chat.id, call.message.message_id)
        except telebot.apihelper.ApiTelegramException:
            pass
        bot.answer_callback_query(call.id, "✅")
        return

    bot.answer_callback_query(call.id, "📤")
    try:
        bot.edit_message_caption(f"📝 سرور رو ارسال کن:\n👤 {user_id}\n📦 {order['product']}\n🔖 {order['tracking_code']}",
                                  call.message.chat.id, call.message.message_id)
    except telebot.apihelper.ApiTelegramException:
        pass
    msg = bot.send_message(call.message.chat.id, "📤 لطفاً سرور رو ارسال کن (متن یا عکس):")
    bot.register_next_step_handler(msg, send_server_to_user, order["id"], user_id)

def send_server_to_user(message, order_id, user_id):
    if intercept_flow_restart(message):
        return
    order = get_order(order_id)
    if not order:
        bot.reply_to(message, "❌ سفارشی نیست!")
        return
    if message.content_type not in ("photo", "text"):
        bot.reply_to(message, "❌ فقط متن یا عکس مجازه!")
        msg = bot.send_message(message.chat.id, "📤 لطفاً سرور رو ارسال کن (متن یا عکس):")
        bot.register_next_step_handler(msg, send_server_to_user, order_id, user_id)
        return

    days = order.get("days") or 30
    expiry_date = get_expiry_date(days)

    try:
        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            filename = f"server_{user_id}_{int(time.time())}.jpg"
            with open(filename, "wb") as f:
                f.write(downloaded_file)
            caption_text = message.caption or ""
            with open(filename, "rb") as f:
                bot.send_photo(user_id, f, caption=f"""✅ <b>خرید شما تایید شد!</b>
━━━━━━━━━━━━━━
📦 {order['product']}
🔖 {order['tracking_code']}
📅 خرید: {order['created_at'][:16]}
⏳ انقضا: {expiry_date}
━━━━━━━━━━━━━━
🌐 اطلاعات سرور:
{caption_text}""", parse_mode="HTML")
            os.remove(filename)
            update_order_status(order_id, "delivered", server_info=caption_text)
        else:
            server_text = message.text.strip()
            if not server_text:
                bot.reply_to(message, "❌ خالی بود، دوباره بفرست:")
                bot.register_next_step_handler(message, send_server_to_user, order_id, user_id)
                return
            bot.send_message(user_id, f"""✅ <b>خرید شما تایید شد!</b>
━━━━━━━━━━━━━━
📦 {order['product']}
🔖 {order['tracking_code']}
📅 خرید: {order['created_at'][:16]}
⏳ انقضا: {expiry_date}
━━━━━━━━━━━━━━
🌐 اطلاعات سرور:
{server_text}""", parse_mode="HTML")
            update_order_status(order_id, "delivered", server_info=server_text)

        bot.reply_to(message, "✅ سرور ارسال شد!")
    except telebot.apihelper.ApiTelegramException as e:
        log.error(f"خطای تلگرام هنگام ارسال سرور: {e}")
        bot.reply_to(message, "❌ نتونستم به کاربر پیام بدم. سفارش هنوز تاییدشده باقی می‌مونه.")
    except OSError as e:
        log.error(f"خطای فایل هنگام ارسال سرور: {e}")
        bot.reply_to(message, "❌ خطا در پردازش فایل. دوباره امتحان کن.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_"))
def reject_order_cb(call):
    bot.answer_callback_query(call.id, "❌")
    user_id = int(call.data.replace("reject_", ""))
    order = get_latest_pending_order(user_id)
    if order:
        update_order_status(order["id"], "rejected")
    try:
        bot.send_message(user_id, "❌ خرید شما رد شد. برای توضیحات با پشتیبانی تماس بگیرید.")
    except telebot.apihelper.ApiTelegramException:
        pass
    try:
        bot.edit_message_caption(f"❌ رد شد!\n👤 {user_id}", call.message.chat.id, call.message.message_id)
    except telebot.apihelper.ApiTelegramException as e:
        log.warning(f"edit_message_caption failed: {e}")

# ============================================================
# پنل ادمین
# ============================================================
def show_pending_orders(chat_id):
    try:
        res = db.table("orders").select("*").eq("status", "pending").order("created_at", desc=True).limit(30).execute()
        orders = res.data
    except Exception as e:
        log.error(f"خطا در دریافت سفارشات در انتظار: {e}")
        orders = []

    if not orders:
        bot.send_message(chat_id, "📋 هیچ سفارشی در انتظار نیست.")
        return
    text = "📋 <b>سفارشات در انتظار</b>\n━━━━━━━━━━━━━━\n\n"
    for o in orders:
        text += f"🆔 {o['telegram_id']}\n{o['product']}\n{o['final_amount']:,} تومان · 🔖 {o['tracking_code']}\n\n"
    bot.send_message(chat_id, text, parse_mode="HTML")

def show_users_list(chat_id):
    try:
        res = db.table("app_users").select("*").order("created_at", desc=True).limit(50).execute()
        users = res.data
    except Exception as e:
        log.error(f"خطا در دریافت لیست کاربران: {e}")
        users = []

    banned_count = sum(1 for u in users if u["is_banned"])
    text = f"👥 <b>لیست کاربران</b>\n━━━━━━━━━━━━━━\n\n📊 کل (۵۰ نفر آخر): {len(users)}\n🚫 بن‌شده: {banned_count}\n\n"
    for i, u in enumerate(users[:20], 1):
        status = "🚫" if u["is_banned"] else "✅"
        uname = u.get("username")
        text += f"{i}. {status} {u['telegram_id']}" + (f" (@{uname})" if uname else "") + f" | 👛 {u['wallet_balance']:,}\n"
    bot.send_message(chat_id, text, parse_mode="HTML")

def show_stats(chat_id):
    try:
        users_count = len(db.table("app_users").select("telegram_id").execute().data)
        confirmed_orders = db.table("orders").select("final_amount, type").in_("status", ["confirmed", "delivered"]).execute().data
        pending_count = len(db.table("orders").select("id").eq("status", "pending").execute().data)
    except Exception as e:
        log.error(f"خطا در دریافت آمار: {e}")
        users_count = 0
        confirmed_orders = []
        pending_count = 0

    total_sales = sum(o["final_amount"] for o in confirmed_orders)
    vpn_orders = sum(1 for o in confirmed_orders if o["type"] == "vpn")
    stars_orders = sum(1 for o in confirmed_orders if o["type"] == "stars")
    topup_total = sum(o["final_amount"] for o in confirmed_orders if o["type"] == "wallet_topup")

    bot.send_message(chat_id, f"""📊 <b>آمار فروش</b>
━━━━━━━━━━━━━━
👥 کل کاربران: {users_count}
📦 سفارشات تایید‌شده: {len(confirmed_orders)}
   • VPN: {vpn_orders} | ⭐ استارز: {stars_orders}
💰 کل فروش: {total_sales:,} تومان
👛 کل شارژ کیف پول: {topup_total:,} تومان
⏳ در انتظار: {pending_count}
━━━━━━━━━━━━━━
📅 {datetime.now().strftime("%Y-%m-%d %H:%M")}""", parse_mode="HTML")

def broadcast_message(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    if message.text and message.text.strip() == "/cancel":
        bot.reply_to(message, "❌ لغو شد.")
        return
    if intercept_flow_restart(message):
        return
    msg = (message.text or "").strip()
    if not msg:
        bot.reply_to(message, "❌ پیام خالی.")
        return

    try:
        users = db.table("app_users").select("telegram_id, is_banned").execute().data
        targets = [u["telegram_id"] for u in users if not u["is_banned"]]
    except Exception as e:
        log.error(f"خطا در دریافت لیست کاربران برای پیام همگانی: {e}")
        bot.reply_to(message, "❌ خطا در دریافت لیست کاربران.")
        return

    status_msg = bot.reply_to(message, f"📨 در حال ارسال به {len(targets)} کاربر...")
    sent, failed = 0, 0
    for uid in targets:
        try:
            bot.send_message(uid, f"📨 پیام از ادمین:\n\n{msg}")
            sent += 1
        except telebot.apihelper.ApiTelegramException:
            failed += 1
        time.sleep(0.05)
    safe_edit(status_msg.chat.id, status_msg.message_id, f"✅ ارسال تمام شد.\n📬 موفق: {sent}\n❌ ناموفق: {failed}")

def ask_ban_target(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    if intercept_flow_restart(message):
        return
    target = (message.text or "").strip()
    if not target.isdigit():
        bot.reply_to(message, "❌ آیدی باید عددی باشه.")
        return
    user = get_user(int(target))
    status = "🚫 بن است" if (user and user["is_banned"]) else "✅ بن نیست"
    bot.reply_to(message, f"کاربر {target}\n{status}\n\nچه کاری انجام بشه؟", reply_markup=ban_unban_keyboard(target))

@bot.callback_query_handler(func=lambda call: call.data.startswith("doban_"))
def cb_do_ban(call):
    if str(call.from_user.id) != str(ADMIN_ID):
        return
    bot.answer_callback_query(call.id, "✅")
    target = int(call.data.replace("doban_", ""))
    set_banned(target, True)
    safe_edit(call.message.chat.id, call.message.message_id, f"✅ کاربر {target} بن شد.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("unban_"))
def cb_do_unban(call):
    if str(call.from_user.id) != str(ADMIN_ID):
        return
    bot.answer_callback_query(call.id, "✅")
    target = int(call.data.replace("unban_", ""))
    set_banned(target, False)
    safe_edit(call.message.chat.id, call.message.message_id, f"✅ کاربر {target} آنبن شد.")

# ============================================================
# سیستم ارسال کد از سایت (OTP Worker)
# ============================================================
def otp_worker():
    """هر ۳ ثانیه چک می‌کنه که سایت درخواست کد جدید داده یا نه."""
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            res = db.table("site_link_codes").select("*").eq("delivered", False).eq("used", False).execute()
            rows = res.data if res.data else []

            for row in rows:
                if row["expires_at"] < now_iso:
                    continue
                try:
                    bot.send_message(row["telegram_id"], f"""🔐 <b>کد ورود به پنل سایت</b>
━━━━━━━━━━━━━━
کد شما (تا ۱۰ دقیقه معتبره):
<code>{row['code']}</code>
━━━━━━━━━━━━━━
این کد رو توی سایت {WEBSITE} وارد کن.""", parse_mode="HTML")
                    db.table("site_link_codes").update({"delivered": True}).eq("code", row["code"]).execute()
                    log.info(f"کد ورود سایت برای کاربر {row['telegram_id']} ارسال شد")
                except Exception as e:
                    log.error(f"خطا در ارسال کد OTP به {row['telegram_id']}: {e}")
        except Exception as e:
            log.error(f"خطا در OTP Worker: {e}")
        time.sleep(3)

# ============================================================
# دستورات ادمین
# ============================================================
@bot.message_handler(commands=["addcode"])
def addcode_cmd(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "❌ استفاده: /addcode CODE PERCENT [MAX_USES] [DAYS_VALID]")
        return
    code = args[1].strip().upper()
    try:
        percent = int(args[2])
    except ValueError:
        bot.reply_to(message, "❌ درصد باید عدد باشه.")
        return
    max_uses = int(args[3]) if len(args) > 3 and args[3].isdigit() else None
    expires_at = None
    if len(args) > 4 and args[4].isdigit():
        expires_at = (datetime.now(timezone.utc) + timedelta(days=int(args[4]))).isoformat()

    try:
        db.table("discount_codes").upsert({
            "code": code, "percent": percent, "max_uses": max_uses,
            "expires_at": expires_at, "active": True, "used_count": 0
        }).execute()
        bot.reply_to(message, f"✅ کد تخفیف {code} ({percent}٪) ساخته شد.")
    except Exception as e:
        log.error(f"خطا در ساخت کد تخفیف: {e}")
        bot.reply_to(message, "❌ خطا در ساخت کد تخفیف.")

@bot.message_handler(commands=["ban"])
def ban_cmd(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "❌ استفاده: /ban [user_id]")
        return
    set_banned(int(args[1]), True)
    bot.reply_to(message, f"✅ {args[1]} بن شد.")

@bot.message_handler(commands=["unban"])
def unban_cmd(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(message, "❌ استفاده: /unban [user_id]")
        return
    set_banned(int(args[1]), False)
    bot.reply_to(message, f"✅ {args[1]} آنبن شد.")

@bot.message_handler(commands=["deliver"])
def deliver_cmd(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ استفاده: /deliver TRACKING_CODE")
        return

    try:
        res = db.table("orders").select("*").eq("tracking_code", args[1]).execute()
        if not res.data:
            bot.reply_to(message, "❌ کد رهگیری پیدا نشد.")
            return
        order = res.data[0]
        msg = bot.reply_to(message, f"📤 سرور رو برای سفارش {order['tracking_code']} ارسال کن:")
        bot.register_next_step_handler(msg, send_server_to_user, order["id"], order["telegram_id"])
    except Exception as e:
        log.error(f"خطا در deliver: {e}")
        bot.reply_to(message, "❌ خطا در پیدا کردن سفارش.")

# ============================================================
# برگشت عمومی
# ============================================================
@bot.callback_query_handler(func=lambda call: call.data == "back")
def back(call):
    bot.answer_callback_query(call.id, "🔙")
    user_id = call.from_user.id
    safe_edit(call.message.chat.id, call.message.message_id, "🔙 برگشتی.")
    if str(user_id) == str(ADMIN_ID):
        bot.send_message(call.message.chat.id, "📋 منوی ادمین:", reply_markup=admin_keyboard())
    else:
        bot.send_message(call.message.chat.id, "📋 منوی اصلی:", reply_markup=main_keyboard())

# ============================================================
# اجرا
# ============================================================
if __name__ == "__main__":
    log.info("=" * 50)
    log.info("🤖 ربات Vpn IR (Supabase edition) روشن شد!")
    log.info(f"📢 کانال: {CHANNEL_ID}")
    log.info(f"👤 ادمین: {ADMIN_ID}")
    log.info("=" * 50)

    otp_thread = threading.Thread(target=otp_worker, daemon=True)
    otp_thread.start()
    log.info("✅ OTP Worker برای ارسال کد از سایت شروع شد.")

    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except Exception as e:
            log.error(f"ربات با خطا متوقف شد، ۵ ثانیه دیگه دوباره امتحان می‌کنیم: {e}")
            time.sleep(5)
