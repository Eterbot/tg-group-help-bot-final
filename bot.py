import logging
import os
import threading
import time
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TOKEN = "7529003560:AAGIIp-RM4tPwbH8dxD5fc2cdz22pvuu-Cw"
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")

# --- DATA STORAGE (In-memory) ---
# In a real production bot, you'd use a database like MongoDB or PostgreSQL.
# For simplicity here, we use a dictionary.
db = {} # {chat_id: {"welcome": str, "rules": str, "notes": {}, "filters": {}, "locks": []}}

def get_db(chat_id):
    if chat_id not in db:
        db[chat_id] = {
            "welcome": "Welcome to the group!",
            "rules": "No rules set yet.",
            "notes": {},
            "filters": {},
            "locks": [],
            "warns": {} # {user_id: count}
        }
    return db[chat_id]

# --- ADMIN CHECK ---
async def is_admin(update: Update):
    if update.effective_chat.type == "private":
        return True
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 မင်္ဂလာပါ! ကျွန်တော်က Rose လိုမျိုး ဘက်စုံသုံး Group Help Bot ပါ။\n\nအသုံးပြုနိုင်တဲ့ command တွေကိုကြည့်ဖို့ /help ကိုနှိပ်ပါ။")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠 **Admin Commands:**\n"
        "• /ban - User ကို ban ရန် (Reply ပြန်သုံးပါ)\n"
        "• /unban - User ကို unban ရန်\n"
        "• /kick - User ကို ထုတ်ရန်\n"
        "• /mute - စာရေးခွင့် ပိတ်ရန်\n"
        "• /unmute - စာရေးခွင့် ပြန်ဖွင့်ရန်\n"
        "• /promote - Admin ပေးရန်\n"
        "• /warn - သတိပေးရန်\n\n"
        "📌 **Pin & Tools:**\n"
        "• /pin - Message ကို pin ရန်\n"
        "• /unpin - Pin ဖြုတ်ရန်\n"
        "• /setwelcome [text] - Welcome message သတ်မှတ်ရန်\n"
        "• /setrules [text] - စည်းကမ်းချက်များ သတ်မှတ်ရန်\n"
        "• /rules - စည်းကမ်းချက်များ ကြည့်ရန်\n\n"
        "📝 **Notes & Filters:**\n"
        "• /save [name] [text] - Note မှတ်ရန် (Reply ပြန်သုံးနိုင်သည်)\n"
        "• /get [name] - မှတ်ထားသော note ပြန်ကြည့်ရန်\n"
        "• /filter [word] [reply] - စကားလုံး filter လုပ်ရန်\n"
        "• /stop [word] - filter ဖြုတ်ရန်\n\n"
        "🔒 **Locks:**\n"
        "• /lock [type] - ပိတ်ရန် (types: sticker, link, media, all)\n"
        "• /unlock [type] - ပြန်ဖွင့်ရန်"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# --- WELCOME & RULES ---
async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ - /setwelcome [စာသား]")
        return
    welcome_text = " ".join(context.args)
    get_db(update.effective_chat.id)["welcome"] = welcome_text
    await update.message.reply_text("Welcome message ကို ပြောင်းလဲလိုက်ပါပြီ။")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    welcome_msg = get_db(chat_id).get("welcome", "Welcome!")
    for member in update.message.new_chat_members:
        name = member.full_name
        text = welcome_msg.replace("{name}", name)
        await update.message.reply_text(text)

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ - /setrules [စာသား]")
        return
    rules_text = " ".join(context.args)
    get_db(update.effective_chat.id)["rules"] = rules_text
    await update.message.reply_text("Group rules တွေကို သတ်မှတ်လိုက်ပါပြီ။")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_text = get_db(update.effective_chat.id).get("rules", "No rules set.")
    await update.message.reply_text(f"📋 **Group Rules:**\n\n{rules_text}", parse_mode=ParseMode.MARKDOWN)

# --- ADMIN ACTIONS ---
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ban ချင်တဲ့သူရဲ့ message ကို reply ပြန်ပါ။")
        return
    user_id = update.message.reply_to_message.from_user.id
    await update.effective_chat.ban_member(user_id)
    await update.message.reply_text(f"User {update.message.reply_to_message.from_user.full_name} ကို Ban လိုက်ပါပြီ။")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Mute ချင်တဲ့သူရဲ့ message ကို reply ပြန်ပါ။")
        return
    user_id = update.message.reply_to_message.from_user.id
    from telegram import ChatPermissions
    await update.effective_chat.restrict_member(user_id, permissions=ChatPermissions(can_send_messages=False))
    await update.message.reply_text(f"User {update.message.reply_to_message.from_user.full_name} ကို Mute လိုက်ပါပြီ။")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Unmute လုပ်ချင်တဲ့သူရဲ့ message ကို reply ပြန်ပါ။")
        return
    user_id = update.message.reply_to_message.from_user.id
    from telegram import ChatPermissions
    await update.effective_chat.restrict_member(user_id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
    await update.message.reply_text(f"User {update.message.reply_to_message.from_user.full_name} ကို Unmute လိုက်ပါပြီ။")

# --- NOTES & FILTERS ---
async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if len(context.args) < 1:
        await update.message.reply_text("အသုံးပြုပုံ - /save [နာမည်] [စာသား]")
        return
    note_name = context.args[0]
    note_content = " ".join(context.args[1:])
    if update.message.reply_to_message and not note_content:
        note_content = update.message.reply_to_message.text
    get_db(update.effective_chat.id)["notes"][note_name] = note_content
    await update.message.reply_text(f"Note '{note_name}' ကို သိမ်းလိုက်ပါပြီ။ /get {note_name} နဲ့ ပြန်ကြည့်နိုင်ပါတယ်။")

async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    note_name = context.args[0]
    note = get_db(update.effective_chat.id)["notes"].get(note_name)
    if note:
        await update.message.reply_text(note)
    else:
        await update.message.reply_text("အဲ့ဒီ note မရှိပါဘူး။")

# --- MESSAGE HANDLER (Filters & Locks) ---
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    chat_id = update.effective_chat.id
    chat_db = get_db(chat_id)
    
    # 1. Check Filters
    if update.message.text:
        text = update.message.text.lower()
        for word, reply in chat_db["filters"].items():
            if word in text:
                await update.message.reply_text(reply)
                return

    # 2. Check Locks (Only for non-admins)
    if not await is_admin(update):
        if "sticker" in chat_db["locks"] and update.message.sticker:
            await update.message.delete()
        elif "link" in chat_db["locks"] and ("http" in (update.message.text or "")):
            await update.message.delete()

# --- WEB SERVER FOR KEEP-ALIVE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Rose-like Bot is live!"

def run_flask(): app.run(host='0.0.0.0', port=10000)

def keep_alive():
    while True:
        if RENDER_URL:
            try: requests.get(RENDER_URL)
            except: pass
        time.sleep(600)

# --- MAIN ---
if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    application = ApplicationBuilder().token(TOKEN).build()
    
    # Basic
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Welcome & Rules
    application.add_handler(CommandHandler("setwelcome", set_welcome))
    application.add_handler(CommandHandler("setrules", set_rules))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    
    # Admin
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("pin", pin))
    application.add_handler(CommandHandler("unpin", unpin))
    
    # Notes
    application.add_handler(CommandHandler("save", save_note))
    application.add_handler(CommandHandler("get", get_note))
    
    # Global Handler
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_all_messages))
    
    logger.info("Rose-like Bot started...")
    application.run_polling()
