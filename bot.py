import logging
import os
import threading
import time
import sqlite3
import json
import requests
from flask import Flask
from telegram import Update, ChatPermissions
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Render မှာ Environment Variable အနေနဲ့ BOT_TOKEN ကို ထည့်ပေးရပါမယ်
TOKEN = os.environ.get("BOT_TOKEN", "7529003560:AAGIIp-RM4tPwbH8dxD5fc2cdz22pvuu-Cw")

# --- DATABASE SETUP ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS warns (chat_id TEXT, user_id TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS activity (chat_id TEXT, user_id TEXT, messages INTEGER DEFAULT 0, last_seen INTEGER, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS settings (chat_id TEXT, key TEXT, value TEXT, PRIMARY KEY (chat_id, key))")
cursor.execute("CREATE TABLE IF NOT EXISTS knowledge (chat_id TEXT, fact TEXT, value TEXT, PRIMARY KEY (chat_id, fact))")
conn.commit()

# --- HELPERS ---
def get_setting(chat_id, key, default=None):
    cursor.execute("SELECT value FROM settings WHERE chat_id=? AND key=?", (str(chat_id), key))
    r = cursor.fetchone()
    return r[0] if r else default

def set_setting(chat_id, key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, ?, ?)", (str(chat_id), key, str(value)))
    conn.commit()

def track_user(chat_id, user_id):
    now = int(time.time())
    chat_id, user_id = str(chat_id), str(user_id)
    cursor.execute("SELECT messages FROM activity WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    d = cursor.fetchone()
    if d:
        cursor.execute("UPDATE activity SET messages=?, last_seen=? WHERE chat_id=? AND user_id=?", (d[0]+1, now, chat_id, user_id))
    else:
        cursor.execute("INSERT INTO activity (chat_id, user_id, messages, last_seen) VALUES (?, ?, ?, ?)", (chat_id, user_id, 1, now))
    conn.commit()

async def is_admin(update: Update):
    if update.effective_chat.type == "private": return True
    member = await update.effective_chat.get_member(update.effective_user.id)
    return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]

# --- AI CHAT FUNCTION ---
async def get_ai_response(text, chat_id):
    bot_name = get_setting(chat_id, "bot_name", "အီတာ")
    
    # Check if it's a taught fact
    cursor.execute("SELECT value FROM knowledge WHERE chat_id=? AND ? LIKE '%' || fact || '%'", (str(chat_id), text.lower()))
    fact = cursor.fetchone()
    if fact:
        return fact[0]
    
    # Default AI-like response
    return f"ကျွန်တော် {bot_name} ပါ။ အခုလောလောဆယ်တော့ အခြေခံမေးခွန်းတွေကိုပဲ ဖြေနိုင်ပါသေးတယ်။ ဘာကူညီပေးရမလဲခင်ဗျာ?"

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = get_setting(update.effective_chat.id, "bot_name", "အီတာ")
    await update.message.reply_text(f"Hello! I am {bot_name}, your AI-powered group bot. Use /help to see commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = get_setting(update.effective_chat.id, "bot_name", "အီတာ")
    help_text = (
        f"**Current Bot Name: {bot_name}**\n\n"
        "**General Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/setname [name] - Change my name (Admin only)\n"
        "/away [reason] - Toggle Owner Away Mode\n"
        "/teach [fact] [value] - Teach me something\n"
        "/id - Get IDs\n\n"
        "**Admin Commands:**\n"
        "/ban, /kick, /mute (Reply to user)\n"
        "/warn, /warnings, /clearwarns\n"
        "/antilink [on/off]\n"
        "/welcome [on/off], /setwelcome [text]\n\n"
        "**Tools:**\n"
        "/stats - Group stats\n"
        "/active - Active users\n"
        "/tagall - Tag everyone\n"
        "/del - Delete replied message\n\n"
        f"Tip: Mention '{bot_name}' to talk to AI!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def set_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ - /setname [နာမည်]")
        return
    new_name = " ".join(context.args)
    set_setting(update.effective_chat.id, "bot_name", new_name)
    await update.message.reply_text(f"✅ Bot name ကို '{new_name}' အဖြစ် ပြောင်းလဲလိုက်ပါပြီ။")

async def away_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    chat_id = update.effective_chat.id
    current = get_setting(chat_id, "away", "off")
    if current == "off":
        reason = " ".join(context.args) if context.args else "Owner မအားသေးလို့ပါ"
        set_setting(chat_id, "away", "on")
        set_setting(chat_id, "away_reason", reason)
        await update.message.reply_text(f"💤 Away Mode ဖွင့်လိုက်ပါပြီ။ အကြောင်းပြချက် - {reason}")
    else:
        set_setting(chat_id, "away", "off")
        await update.message.reply_text("✅ Away Mode ပိတ်လိုက်ပါပြီ။")

async def teach_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if len(context.args) < 2:
        await update.message.reply_text("အသုံးပြုပုံ - /teach [အချက်အလက်] [အဖြေ]")
        return
    fact = context.args[0].lower()
    value = " ".join(context.args[1:])
    cursor.execute("INSERT OR REPLACE INTO knowledge (chat_id, fact, value) VALUES (?, ?, ?)", (str(update.effective_chat.id), fact, value))
    conn.commit()
    await update.message.reply_text(f"📝 '{fact}' အတွက် '{value}' လို့ မှတ်သားထားလိုက်ပါပြီ။")

# --- MODERATION ---
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message: return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.ban_member(user.id)
    await update.message.reply_text(f"🚫 {user.full_name} ကို Ban လိုက်ပါပြီ။")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message: return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.unban_member(user.id)
    await update.message.reply_text(f"👢 {user.full_name} ကို Kick လိုက်ပါပြီ။")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message: return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.restrict_member(user.id, permissions=ChatPermissions(can_send_messages=False))
    await update.message.reply_text(f"🔇 {user.full_name} ကို Mute လိုက်ပါပြီ။")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message: return
    user = update.message.reply_to_message.from_user
    await update.effective_chat.restrict_member(user.id, permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True))
    await update.message.reply_text(f"🔊 {user.full_name} ကို Unmute လိုက်ပါပြီ။")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not update.message.reply_to_message: return
    user = update.message.reply_to_message.from_user
    chat_id, user_id = str(update.effective_chat.id), str(user.id)
    cursor.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    d = cursor.fetchone()
    count = (d[0] + 1) if d else 1
    cursor.execute("INSERT OR REPLACE INTO warns (chat_id, user_id, count) VALUES (?, ?, ?)", (chat_id, user_id, count))
    conn.commit()
    await update.message.reply_text(f"⚠️ {user.full_name} ကို သတိပေးလိုက်ပါပြီ ({count}/3)")
    if count >= 3:
        await update.effective_chat.ban_member(user.id)
        await update.message.reply_text("သတိပေးချက် ၃ ကြိမ်ပြည့်၍ Ban လိုက်ပါပြီ။")
        cursor.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        conn.commit()

# --- MESSAGE HANDLERS ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    chat_id = update.effective_chat.id
    text = update.message.text if update.message.text else ""
    
    # Track activity
    track_user(chat_id, update.effective_user.id)
    
    # Away Mode Response
    if get_setting(chat_id, "away") == "on":
        if not await is_admin(update):
            reason = get_setting(chat_id, "away_reason", "Owner မအားသေးလို့ပါ")
            await update.message.reply_text(f"🤖 {reason}")
            return

    # AI Chat Feature (Mention bot name)
    bot_name = get_setting(chat_id, "bot_name", "အီတာ")
    if bot_name.lower() in text.lower():
        response = await get_ai_response(text, chat_id)
        await update.message.reply_text(response)
        return

    # Antilink
    if "http" in text.lower():
        if not await is_admin(update) and get_setting(chat_id, "antilink") == "on":
            await update.message.delete()
            return

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if get_setting(chat_id, "welcome") == "on":
        welcome_text = get_setting(chat_id, "welcometext", "Welcome {name}!")
        for member in update.message.new_chat_members:
            text = welcome_text.replace("{name}", member.full_name)
            await update.message.reply_text(text)

# --- FLASK ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running 24/7!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- MAIN ---
if __name__ == '__main__':
    if TOKEN:
        threading.Thread(target=run_flask).start()
        app_tg = ApplicationBuilder().token(TOKEN).build()
        
        app_tg.add_handler(CommandHandler("start", start))
        app_tg.add_handler(CommandHandler("help", help_cmd))
        app_tg.add_handler(CommandHandler("setname", set_bot_name))
        app_tg.add_handler(CommandHandler("away", away_mode))
        app_tg.add_handler(CommandHandler("teach", teach_bot))
        app_tg.add_handler(CommandHandler("ban", ban))
        app_tg.add_handler(CommandHandler("kick", kick))
        app_tg.add_handler(CommandHandler("mute", mute))
        app_tg.add_handler(CommandHandler("unmute", unmute))
        app_tg.add_handler(CommandHandler("warn", warn))
        
        app_tg.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
        app_tg.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_all))
        
        print("Bot started...")
        app_tg.run_polling()
