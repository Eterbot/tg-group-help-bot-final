import logging
import os
import threading
import time
import sqlite3
import json
import requests
import re
from flask import Flask
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TOKEN = os.environ.get("BOT_TOKEN", "7529003560:AAGXeHNr_ETFm4U0D6gKOQT2qj9A7ITLM1o")

# --- DATABASE SETUP ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS warns (chat_id TEXT, user_id TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS activity (chat_id TEXT, user_id TEXT, messages INTEGER DEFAULT 0, last_seen INTEGER, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS settings (chat_id TEXT, key TEXT, value TEXT, PRIMARY KEY (chat_id, key))")
cursor.execute("CREATE TABLE IF NOT EXISTS knowledge (chat_id TEXT, fact TEXT, value TEXT, PRIMARY KEY (chat_id, fact))")
cursor.execute("CREATE TABLE IF NOT EXISTS filters (chat_id TEXT, keyword TEXT, reply TEXT, PRIMARY KEY (chat_id, keyword))")
cursor.execute("CREATE TABLE IF NOT EXISTS notes (chat_id TEXT, note_name TEXT, content TEXT, PRIMARY KEY (chat_id, note_name))")
cursor.execute("CREATE TABLE IF NOT EXISTS rules (chat_id TEXT, rules_text TEXT, PRIMARY KEY (chat_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS connections (user_id TEXT PRIMARY KEY, chat_id TEXT, last_chat_id TEXT)")
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

async def get_connected_chat(user_id):
    cursor.execute("SELECT chat_id FROM connections WHERE user_id=?", (str(user_id),))
    r = cursor.fetchone()
    return r[0] if r else None

async def get_effective_chat_id(update: Update):
    if update.effective_chat.type == "private":
        connected = await get_connected_chat(update.effective_user.id)
        return connected if connected else str(update.effective_chat.id)
    return str(update.effective_chat.id)

async def is_admin(update: Update, target_chat_id=None):
    user_id = update.effective_user.id
    chat_id = target_chat_id or update.effective_chat.id
    try:
        member = await update.get_bot().get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False

# --- AI CHAT SIMULATION ---
def get_ai_response(text):
    text = text.lower().strip()
    cursor.execute("SELECT value FROM knowledge WHERE chat_id='GLOBAL' AND fact=?", (text,))
    r = cursor.fetchone()
    if r: return r[0]
    
    greetings = {
        "hi": "မင်္ဂလာပါခင်ဗျာ၊ ဘာကူညီပေးရမလဲ?",
        "hello": "Hello! နေကောင်းလားခင်ဗျာ?",
        "နေကောင်းလား": "နေကောင်းပါတယ်ခင်ဗျာ၊ လူကြီးမင်းရော နေကောင်းရဲ့လား?",
        "ကျေးဇူး": "ရပါတယ်ခင်ဗျာ၊ အမြဲတမ်း ကူညီဖို့ အသင့်ပါပဲ။"
    }
    for k, v in greetings.items():
        if k in text: return v
    return "နားမလည်လို့ ပြန်ပြောပေးပါဦးခင်ဗျာ။ ကျွန်တော့်ကို တစ်ခုခု သင်ပေးချင်ရင် /teach [အချက်အလက်] [အဖြေ] လို့ သုံးနိုင်ပါတယ်ခင်ဗျာ။"

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = get_setting(update.effective_chat.id, "bot_name", "အီတာ")
    await update.message.reply_text(f"Hello! I am {bot_name}, your AI-powered group bot. Use /help to see commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = get_setting(update.effective_chat.id, "bot_name", "အီတာ")
    help_text = f"""
<b>Current Bot Name:</b> {bot_name}

<b>General Commands:</b>
/start - Start the bot
/help - Show this message
/setname [name] - Change my name (Admin only)
/away - Toggle Owner Away Mode
/teach [fact] [value] - Teach me something
/id - Get IDs

<b>Admin Commands:</b>
/ban, /kick, /mute (Reply to user)
/warn, /warnings, /clearwarns

<b>Group Tools:</b>
/setwelcome [text] - Set welcome message
/welcome on/off - Toggle welcome
/tagall - Tag everyone

<i>Tip: Mention '{bot_name}' to talk to AI!</i>
"""
    await update.message.reply_html(help_text)

async def set_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ: /setname [နာမည်]")
        return
    new_name = " ".join(context.args)
    set_setting(update.effective_chat.id, "bot_name", new_name)
    await update.message.reply_text(f"Bot ရဲ့ နာမည်ကို '{new_name}' လို့ ပြောင်းလဲလိုက်ပါပြီ။")

async def teach_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("အသုံးပြုပုံ: /teach [အချက်အလက်] [အဖြေ]")
        return
    fact = context.args[0].lower()
    value = " ".join(context.args[1:])
    cursor.execute("INSERT OR REPLACE INTO knowledge (chat_id, fact, value) VALUES (?, ?, ?)", 
                   ('GLOBAL', fact, value))
    conn.commit()
    await update.message.reply_text(f"မှတ်သားထားလိုက်ပါပြီ! '{fact}' လို့ မေးရင် '{value}' လို့ ဖြေပေးပါ့မယ်။")

async def away_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update): return
    current = get_setting(update.effective_chat.id, "away_mode", "off")
    new_status = "on" if current == "off" else "off"
    set_setting(update.effective_chat.id, "away_mode", new_status)
    msg = "Owner အခု မအားသေးပါဘူး။ Bot က အစားဝင်ဖြေပေးပါ့မယ်။" if new_status == "on" else "Owner ပြန်ရောက်ပါပြီ။"
    await update.message.reply_text(msg)

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    chat_id, user_id, text = str(update.effective_chat.id), str(update.effective_user.id), update.message.text
    track_user(chat_id, user_id)
    bot_name = get_setting(chat_id, "bot_name", "အီတာ")
    away_mode = get_setting(chat_id, "away_mode", "off")
    if bot_name.lower() in text.lower() or (away_mode == "on" and update.effective_chat.type != "private"):
        math_pattern = re.compile(r'^[0-9+\-*/().\s×÷]+$')
        clean_text = text.lower().replace(bot_name.lower(), "").strip()
        if math_pattern.match(clean_text) and any(c in clean_text for c in "+-*/×÷"):
            try:
                safe_text = clean_text.replace('×', '*').replace('÷', '/')
                result = eval(safe_text, {"__builtins__": None}, {})
                await update.message.reply_text(f"အဖြေကတော့ {result} ဖြစ်ပါတယ်ခင်ဗျာ။")
                return
            except: pass
        response = get_ai_response(clean_text)
        await update.message.reply_text(response)

app = Flask(__name__)
@app.route('/')
def home(): return "Bot is running 24/7!"
def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app_tg = ApplicationBuilder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("help", help_cmd))
    app_tg.add_handler(CommandHandler("setname", set_bot_name))
    app_tg.add_handler(CommandHandler("away", away_mode))
    app_tg.add_handler(CommandHandler("teach", teach_bot))
    app_tg.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_messages))
    print("Bot is starting...")
    app_tg.run_polling()
